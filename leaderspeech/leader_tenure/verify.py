"""Verify proposed tenure additions before they reach the researcher's outbox.

Consolidates `gpt_verify_proposed_additions.py` (+ the separate ceremonial pass) into one
call per proposal: did this person actually serve as the TOP leader of THIS country during
this period, and is the office ceremonial or executive? Uses the strong verify model (real
world knowledge). With `use_wikipedia`, each proposal is first grounded against the live
Wikipedia summary API and that extract is handed to the model — a tougher, sourced check.
"""

from __future__ import annotations

import asyncio
import json

import pandas as pd

from ..clean_structure_metadata import llm

SYSTEM_PROMPT = """You are a political science expert verifying whether a person served as head of state or head of government of a SPECIFIC country during a specific period.

Decide:
1. Did this person actually serve as the TOP executive or highest-office leader (president, prime minister, king, sultan, emir, supreme leader, chancellor) of the LISTED COUNTRY during the listed years? It must be their OWN country, not a foreign leader visiting.
2. Is that office CEREMONIAL (a figurehead head of state in a parliamentary system, e.g. the President of India/Germany/Israel) or EXECUTIVE (holds real governing power)?

Count: ceremonial presidents (still heads of state), supreme leaders, reigning kings/sultans/emirs. Do NOT count: Governor-Generals, foreign leaders, company/sports/NGO "presidents", first ladies/spouses.

If a WIKIPEDIA EXTRACT is provided, use it as evidence but apply your own judgment.

Respond with JSON only:
{"is_leader_of_this_country": true/false, "actual_role": "President/PM/King/etc or null", "is_ceremonial": true/false/null, "confidence": "high/medium/low", "reasoning": "1-2 sentence explanation"}"""


def wikipedia_summary(title: str, timeout: float = 8.0) -> str | None:
    """Return the lead extract from the English Wikipedia REST summary API, or None."""
    import httpx
    slug = str(title).strip().replace(" ", "_")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}"
    try:
        r = httpx.get(url, timeout=timeout, headers={"User-Agent": "LeaderSpeech/0.1 (research)"})
        if r.status_code == 200:
            return (r.json().get("extract") or "").strip() or None
    except Exception:
        return None
    return None


def _user_message(row, wiki_extract: str | None) -> str:
    def s(v):
        return "not available" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()
    msg = (f"PERSON: {s(row.get('speaker'))}\nCOUNTRY: {s(row.get('country'))}\n"
           f"LISTED_ROLE: {s(row.get('role'))}\n"
           f"YEARS_ACTIVE_IN_DATA: {s(row.get('min_year'))} - {s(row.get('max_year'))}\n"
           f"NUMBER_OF_SPEECHES: {s(row.get('n_speeches'))}")
    if wiki_extract:
        msg += f"\n\nWIKIPEDIA EXTRACT:\n{wiki_extract[:1500]}"
    return msg


async def verify_one(client, model, config, row, sem) -> dict:
    wiki = wikipedia_summary(row.get("speaker")) if config.use_wikipedia else None
    async with sem:
        await asyncio.sleep(config.rate_limit_delay)
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": _user_message(row, wiki)}],
            temperature=config.temperature, max_tokens=config.max_tokens,
            response_format={"type": "json_object"},
        )
        out = _parse(resp.choices[0].message.content)
        out["wikipedia_extract"] = wiki or ""
        return out


def _parse(content) -> dict:
    empty = {"gpt_is_leader": None, "gpt_actual_role": None, "is_ceremonial": None,
             "gpt_confidence": None, "gpt_reasoning": None}
    if not content:
        return empty
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return empty
    return {
        "gpt_is_leader": data.get("is_leader_of_this_country"),
        "gpt_actual_role": data.get("actual_role"),
        "is_ceremonial": data.get("is_ceremonial"),
        "gpt_confidence": data.get("confidence"),
        "gpt_reasoning": data.get("reasoning"),
    }


def verify_proposals(df: pd.DataFrame, config, *, client=None, model=None) -> pd.DataFrame:
    """Add gpt_is_leader / gpt_actual_role / is_ceremonial / gpt_confidence / gpt_reasoning
    (+ wikipedia_extract) to each proposed addition. No-op (all None) if no client is given."""
    df = df.copy().reset_index(drop=True)
    cols = ["gpt_is_leader", "gpt_actual_role", "is_ceremonial", "gpt_confidence",
            "gpt_reasoning", "wikipedia_extract"]
    for c in cols:
        if c not in df.columns:
            df[c] = None
    if df.empty or client is None:
        return df

    model = model or config.verify_model
    idx = list(df.index)
    rows = [df.loc[i] for i in idx]

    async def _worker(item, sem):
        i, r = item
        return i, await verify_one(client, model, config, r, sem)

    results: list = []
    asyncio.run(llm.run_async_batches(
        list(zip(idx, rows)), _worker,
        batch_size=config.batch_size, chunk_size=config.chunk_size,
        on_chunk=lambda chunk, res: results.extend(res),
    ))
    for item in results:
        if isinstance(item, Exception):
            continue
        i, parsed = item
        for c in cols:
            df.at[i, c] = parsed.get(c)
    return df
