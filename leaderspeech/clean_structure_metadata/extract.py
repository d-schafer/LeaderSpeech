"""The unified GPT extraction pass — the heart of the cleaner.

One structured call per speech replaces the old chain of separate scripts
(speaker-confirm + speech-classifier + structure-corrections + date-check). The
model reads the speech (in its ORIGINAL language — GPT reads non-English fine, so
translation is a later, separate stage) plus the scraped metadata and the
authoritative list of leaders known to be in office, and returns one JSON object
matching `SpeechMeta`. Deterministic post-processing (tenure crosscheck, gate)
happens downstream in pipeline.py; this module only talks to the model.
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel

# --- the fields the model returns; also the keys of every parsed dict ---
META_FIELDS = [
    "document_type", "is_first_person", "speaker", "speaker_attributed_correct",
    "speaker_type", "position", "date", "date_matches_metadata", "language",
    "audience", "speech_type", "venue", "confidence", "reasoning",
]

# document_type values. The first three "represent the leader" and are kept by default;
# "other" does not and is rejected. See the gate + docs/cleaning.md.
DOCUMENT_TYPES = ["speech", "interview", "official_statement", "other"]


class SpeechMeta(BaseModel):
    """Schema of record for the extraction output. Fields are permissive strings so a
    slightly off-spec model reply is preserved (and normalized downstream) rather than
    rejected. `parse_meta` is the dict-based parser actually used at runtime."""

    document_type: Optional[str] = None          # speech | interview | official_statement | other
    is_first_person: Optional[str] = None        # yes | no | unsure (recorded; not a gate)
    speaker: Optional[str] = None                # best name from text/title, or null
    speaker_attributed_correct: Optional[str] = None  # yes | no | unsure (vs scraped speaker)
    speaker_type: Optional[str] = None           # head_of_state|head_of_government|both|other_minister|foreign_visitor|other|unknown
    position: Optional[str] = None               # short title (President, Prime Minister, King...)
    date: Optional[str] = None                   # YYYY-MM-DD best estimate from text
    date_matches_metadata: Optional[str] = None  # yes | no | unsure
    language: Optional[str] = None               # ISO 639-1 of the text
    audience: Optional[str] = None               # one of the 7 audience classes
    speech_type: Optional[str] = None            # one of the 10 speech-type classes
    venue: Optional[str] = None                  # city / institution / event, or null
    confidence: Optional[str] = None             # very_high | high | medium | low
    reasoning: Optional[str] = None              # 1-2 sentences


SPEECH_TYPES = [
    "Press Conference/Statement", "Campaign Rally", "Parliamentary/Legislative Address",
    "TV/Radio Interview", "International Summit/Diplomatic", "Party Convention/Internal",
    "Ceremonial/State Event", "Policy Announcement", "Crisis Response", "Other",
]
AUDIENCES = [
    "General Public", "Political Elites/Officials", "Party Supporters/Base",
    "International Community", "Media/Journalists", "Specific Interest Groups", "Other",
]

SYSTEM_PROMPT = """You are a careful research assistant on a comparative-politics project building a dataset of speeches by NATIONAL LEADERS (heads of state and heads of government). For each document you are given the scraped text plus its metadata, and an authoritative list of leaders known to have been in office in that country around that date. Read the text and return ONE JSON object describing it.

You will be given: SPEAKER (attributed, may be blank), COUNTRY, DATE (approximate), POSITION (may be blank), TITLE (may be blank), CONTEXT (may be blank), SOURCE, CONFIRMED LEADERS IN OFFICE (authoritative), and TEXT (first ~500 words, in its original language).

Decide each field:

document_type: classify the document as EXACTLY one of:
  - "speech": remarks actually delivered/spoken by the leader — an address, speech, toast, or press-conference remarks the leader gave aloud (usually first person).
  - "interview": the leader answering questions in an interview.
  - "official_statement": a written statement, communiqué, declaration, message, condolence, tribute, or reaction ISSUED IN THE LEADER'S NAME (by the leader or their office) that conveys the LEADER'S OWN position, reaction, values, or policy stance. This INCLUDES third-person communiqués that report the leader's position (e.g. "The President learned with sadness... He reaffirms his determination to bring peace..."). What matters is that the content represents the leader's values, attitude, or policy — NOT whether it is grammatically first person.
  - "other": a document that does NOT represent the leader's own words or position — a news article reporting events, a biography, an agenda/schedule, a logistical or administrative notice, or a list — with no conveyed stance of the leader.
Prefer "official_statement" over "other" whenever the document expresses the leader's position/values/policy, even in the third person. Use "other" only when the leader's own voice or position is genuinely absent.

is_first_person: "yes" if the leader's own words are present (first-person remarks, quoted or reported), "no" if the document is wholly third-person, "unsure" otherwise. (Recorded for analysis only — an official_statement can be third-person and still be kept.)

speaker: the actual person whose position the document represents, as a clean full name (no title). Determine from the text and title. A title in front of a name does NOT make a different person ("President X" IS X). Accent/transliteration variants are the same person. If the document is clearly a DIFFERENT named individual than the attributed SPEAKER (e.g. a visiting foreign leader's own speech hosted on this government site, or a minister speaking, not the president), give the ACTUAL person. If no person can be identified, null.

speaker_attributed_correct: compared to the scraped SPEAKER — "yes" if they are the same person (ignore titles/accents/spelling), "no" if a genuinely different person spoke, "unsure" if unclear or SPEAKER was blank.

speaker_type: the actual speaker's role AT THE TIME — one of: "head_of_state", "head_of_government", "both" (e.g. an executive president who is both), "other_minister" (any cabinet minister/official who is not the leader), "foreign_visitor" (a leader/official of ANOTHER country), "other" (anyone else), or "unknown".

position: the actual speaker's short official title (e.g. "President", "Prime Minister", "King", "Foreign Minister"), or null.

date: your best estimate of the delivery date as YYYY-MM-DD from clues in the text (events, anniversaries, named conferences such as COP26=2021, the pandemic=2020+, elections). If only a year is known, use YYYY-01-01. If you cannot tell, null.
date_matches_metadata: "yes" if the given DATE is consistent with the text, "no" if the text clearly indicates a different date, "unsure" otherwise.

language: ISO 639-1 two-letter code of the TEXT (e.g. "es", "fr", "en").

speech_type: choose the single best fit from EXACTLY this list: %s.
audience: the primary intended audience — choose from EXACTLY this list: %s.
venue: a short free-text venue/place/event if identifiable (city, institution, or event name), else null.

confidence: your overall confidence — "very_high", "high", "medium", or "low".
reasoning: one or two sentences explaining your key judgments (especially any speaker correction or not-a-speech call).

Guidance: most documents on these government sites ARE genuine speeches or official statements correctly attributed to the listed leader. Set document_type="other" or change the speaker only on clear evidence. If the SPEAKER appears in the CONFIRMED LEADERS IN OFFICE list, that strongly supports correct attribution.

Respond with JSON only, exactly these keys: {"document_type","is_first_person","speaker","speaker_attributed_correct","speaker_type","position","date","date_matches_metadata","language","audience","speech_type","venue","confidence","reasoning"}. Use null for unknown values.""" % (
    ", ".join(SPEECH_TYPES),
    ", ".join(AUDIENCES),
)


def _safe(val) -> str:
    if val is None:
        return "not available"
    s = str(val).strip()
    return s if s else "not available"


def _pick_text(row: dict) -> str:
    """Speech text lives in `text` (English sources) or `text_originlanguage` (others)."""
    for key in ("text", "text_originlanguage"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v)
    return ""


def _pick(row: dict, base: str) -> str:
    for key in (base, f"{base}_originlanguage"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v)
    return ""


def build_user_message(row: dict, leaders_info: str, max_words: int = 500) -> str:
    """Assemble the per-speech prompt: scraped metadata + known leaders + truncated text."""
    text = _pick_text(row)
    if text:
        words = text.split()
        if len(words) > max_words:
            text = " ".join(words[:max_words]) + " [...]"
    return (
        f"SPEAKER: {_safe(row.get('speaker'))}\n"
        f"COUNTRY: {_safe(row.get('country'))}\n"
        f"DATE: {_safe(row.get('date'))}\n"
        f"POSITION: {_safe(row.get('position'))}\n"
        f"TITLE: {_safe(_pick(row, 'title'))}\n"
        f"CONTEXT: {_safe(_pick(row, 'context'))}\n"
        f"SOURCE: {_safe(row.get('source'))}\n"
        f"CONFIRMED LEADERS IN OFFICE (authoritative): {leaders_info or 'not available'}\n\n"
        f"TEXT (first ~{max_words} words):\n{text or 'not available'}"
    )


def empty_meta() -> dict:
    return {k: None for k in META_FIELDS}


def parse_meta(content: Optional[str]) -> dict:
    """Parse the model's JSON reply into a dict with every META_FIELDS key. Returns an
    all-None dict on any failure (so a bad reply degrades to 'unknown', never crashes)."""
    if not content:
        return empty_meta()
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return empty_meta()
    out = {}
    for k in META_FIELDS:
        v = data.get(k) if isinstance(data, dict) else None
        if v is None:
            out[k] = None
        elif isinstance(v, str):
            out[k] = v.strip() or None
        else:
            out[k] = str(v)
    return out


async def extract_one(client, config, user_message: str, semaphore) -> dict:
    """One async, rate-limited, JSON-mode extraction call. Returns a parsed meta dict.
    Raises on API error (caught by the batch runner's return_exceptions)."""
    import asyncio
    async with semaphore:
        await asyncio.sleep(config.rate_limit_delay)
        resp = await client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            response_format={"type": "json_object"},
        )
        return parse_meta(resp.choices[0].message.content)
