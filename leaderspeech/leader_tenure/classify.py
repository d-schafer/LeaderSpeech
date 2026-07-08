"""Classify unmatched speakers as leaders vs non-leaders.

A cheap two-stage filter, consolidating `gpt_classify_leaders.py`:
  1. Position-based regex pre-filter (no API): obvious includes (President, PM, King...) and
     excludes (ministers, ambassadors, governors, judges, royals-not-reigning...).
  2. GPT classification for the ambiguous remainder (a cheap model is enough here).
Only the position function and the prompt are leader-curation-specific; the async plumbing is
reused from `clean_structure_metadata.llm`.
"""

from __future__ import annotations

import asyncio
import json
import re

import pandas as pd

from ..clean_structure_metadata import llm

# --- position regexes (from gpt_classify_leaders.py) ---
_EXCLUDE = [
    r"\bminister\s+of\b", r"\bminister\s+for\b", r"\bdeputy\s+(prime\s+)?minister\b",
    r"\bforeign\s+minister\b", r"\bdefen[cs]e\s+minister\b", r"\bfinance\s+minister\b",
    r"\binterior\s+minister\b", r"\bambassador\b", r"\bsecretary[\s-]general\b",
    r"\bdirector\b", r"\bcommissioner\b", r"\bgovernor[\s-]*general\b", r"\bgovernor\b",
    r"\bmayor\b", r"\bsenator\b", r"\bmember\s+of\s+parliament\b", r"\b(mp|m\.p\.)\b",
    r"\bgeneral\b(?!.*\b(secretary|assembly)\b)", r"\bcolonel\b", r"\badmiral\b", r"\bmarshal\b",
    r"\bchief\s+of\s+(staff|defense|defence)\b", r"\battorney\s+general\b", r"\bchief\s+justice\b",
    r"\bjudge\b", r"\bspeaker\b", r"\bchairman\b(?!.*\bstate\b)", r"\bchairperson\b",
    r"\bchairwoman\b", r"\bsecretary\s+of\s+state\b", r"\bvice[\s-]president\b", r"\bdeputy\b",
    r"\benvoy\b", r"\bconsul\b", r"\bdiplomat\b", r"\brepresentative\b", r"\bdelegate\b",
    r"\bcoach\b", r"\bathlete\b", r"\bchief\s+executive\b(?!.*\bgovernment\b)", r"\bcounsel\s+to\b",
    r"\bmunicipal\s+president\b", r"\bcop\d+\s+president\b",
    r"\bpresident\s+of\s+(the\s+)?(european|commission|council|assembly|senate|parliament|committee|"
    r"court|corporation|company|bank|university|federation|foundation|association|olympic)",
]
_ROYAL_EXCLUDE = [
    r"\bqueen\s+consort\b", r"\bprincess\b", r"\blady\b", r"\bduchess\b", r"\bcountess\b",
    r"\bprince\b(?!\s*(regent|crown|regnant))",
]
_INCLUDE = [
    r"\bprime\s+minister\b", r"\bpresident\b", r"\bchancellor\b(?!.*\b(exchequer)\b)",
    r"\bsupreme\s+leader\b", r"\bemir\b", r"\bsultan\b",
]
_MONARCH = [r"^king$", r"^king\b", r"\bking\s+of\b", r"\bcrown\s+prince\b", r"\bruler\b"]


def classify_by_position(speaker, position, country=None) -> tuple[bool | None, str | None, str]:
    """(is_leader, role, method). method == 'gpt' means "ambiguous — send to the model".
    Excludes are checked before includes so 'Deputy PM' / 'Vice President' are set aside first."""
    if position is None or str(position).strip() == "" or pd.isna(position):
        return None, None, "gpt"
    pos = str(position).strip().lower()

    for pat in _EXCLUDE + _ROYAL_EXCLUDE:
        if re.search(pat, pos):
            return False, str(position).strip(), "auto_exclude"
    for pat in _INCLUDE + _MONARCH:
        if re.search(pat, pos):
            return True, str(position).strip(), "auto_include"
    return None, None, "gpt"


SYSTEM_PROMPT = """You are a political science research assistant. Determine whether a person is a HEAD OF STATE or HEAD OF GOVERNMENT of their country.

We want ONLY: Presidents (executive, or ceremonial if that is the highest office), Prime Ministers/Premiers/Chancellors, reigning Kings/Sultans/Emirs, Crown Princes who serve as de facto head of state, Supreme Leaders, and equivalent top executive leaders.

We do NOT want: ministers, deputy/vice presidents, ambassadors/diplomats/envoys, members of parliament/senators, sub-national governors, military officers (unless they ARE the head of state), judges/attorneys general, royal family members who are NOT the reigning monarch/de facto ruler, heads of international organizations, athletes/celebrities/religious leaders (unless head of state), and Governor-Generals (unless de facto head of state).

Respond with JSON only:
{"is_leader": true/false, "role": "President/Prime Minister/King/etc. or null", "reasoning": "brief 1-sentence explanation"}"""


def _user_message(row) -> str:
    def s(v):
        return "not available" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
    return (f"SPEAKER: {s(row.get('speaker'))}\nCOUNTRY: {s(row.get('country'))}\n"
            f"POSITION: {s(row.get('position'))}\nNUMBER_OF_SPEECHES: {s(row.get('n_speeches'))}\n"
            f"YEARS_ACTIVE: {s(row.get('min_year'))} - {s(row.get('max_year'))}")


async def classify_one(client, model, config, row, sem) -> dict:
    """One async, JSON-mode classification call. Returns {'is_leader','role','reasoning'}."""
    async with sem:
        await asyncio.sleep(config.rate_limit_delay)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": _user_message(row)}],
            temperature=config.temperature, max_tokens=config.max_tokens,
            response_format={"type": "json_object"},
        )
        return _parse(resp.choices[0].message.content)


def _parse(content) -> dict:
    empty = {"is_leader": None, "role": None, "reasoning": None}
    if not content:
        return empty
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return empty
    return {"is_leader": data.get("is_leader"), "role": data.get("role"),
            "reasoning": data.get("reasoning")}


def classify_unmatched(df: pd.DataFrame, config, *, client=None, model=None) -> pd.DataFrame:
    """Add is_leader / role / reasoning / classification_method to unmatched speakers.
    Position pre-filter first; the ambiguous remainder goes to GPT only if a `client` is given."""
    df = df.copy().reset_index(drop=True)
    df["is_leader"] = None
    df["role"] = None
    df["reasoning"] = None
    df["classification_method"] = None

    gpt_idx = []
    for i, row in df.iterrows():
        is_leader, role, method = classify_by_position(row.get("speaker"), row.get("position"), row.get("country"))
        df.at[i, "classification_method"] = method
        if method == "auto_include":
            df.at[i, "is_leader"], df.at[i, "role"] = True, role
            df.at[i, "reasoning"] = f"Position indicates head of state/government: {role}"
        elif method == "auto_exclude":
            df.at[i, "is_leader"], df.at[i, "role"] = False, role
            df.at[i, "reasoning"] = f"Position indicates non-leader: {role}"
        else:
            gpt_idx.append(i)

    if gpt_idx and client is not None:
        model = model or config.classify_model
        rows = [df.loc[i] for i in gpt_idx]

        async def _worker(item, sem):
            i, r = item
            return i, await classify_one(client, model, config, r, sem)

        results: list = []

        def _on_chunk(chunk, res):
            results.extend(res)

        asyncio.run(llm.run_async_batches(
            list(zip(gpt_idx, rows)), _worker,
            batch_size=config.batch_size, chunk_size=config.chunk_size, on_chunk=_on_chunk,
        ))
        for item in results:
            if isinstance(item, Exception):
                continue
            i, parsed = item
            df.at[i, "is_leader"] = parsed["is_leader"]
            df.at[i, "role"] = parsed["role"]
            df.at[i, "reasoning"] = parsed["reasoning"]
    return df
