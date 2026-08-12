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
    "document_type", "is_first_person", "is_substantive", "speaker", "speaker_attributed_correct",
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
    is_substantive: Optional[str] = None         # yes | no | unsure — position/policy/values vs pure courtesy
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

SYSTEM_PROMPT = """You are a careful research assistant on a comparative-politics project building a dataset of speeches by NATIONAL LEADERS (heads of state and heads of government). For each document you are given the scraped text plus its metadata, and a list of leaders KNOWN to have been in office in that country around that date — a reference that may be INCOMPLETE (a new administration, regime change, or a leader added mid-term can be missing). Read the text and return ONE JSON object describing it.

You will be given: SPEAKER (attributed, may be blank), COUNTRY, DATE (approximate, and sometimes "not available"), POSITION (may be blank), TITLE (may be blank), CONTEXT (may be blank), SOURCE, KNOWN LEADERS IN OFFICE (may be incomplete), and TEXT (first ~500 words, in its original language).

Some documents come from ARCHIVED copies of a government website (the Internet Archive), and those often carry NO date of their own. For them you may also be given:
  - CANDIDATE DATE FROM TEXT: a date found by a crude pattern match on the first lines of the body. It is UNVERIFIED and is sometimes a date mentioned in passing rather than the date of the document. Confirm it against the text, or correct it.
  - ARCHIVE CAPTURE DATE: the date the Internet Archive CRAWLED the page. The document was published on or BEFORE this date, and usually not more than a few years earlier. It is a BOUND, never the answer. Do NOT return it as the date unless the text itself independently supports that date.

Decide each field:

document_type: classify the document as EXACTLY one of:
  - "speech": remarks actually delivered/spoken by the leader — an address, speech, toast, or press-conference remarks the leader gave aloud (usually first person).
  - "interview": the leader answering questions in an interview.
  - "official_statement": a written statement, communiqué, declaration, message, condolence, tribute, or reaction ISSUED IN THE LEADER'S NAME (by the leader or their office) that conveys the LEADER'S OWN position, reaction, values, or policy stance. This INCLUDES third-person communiqués that report the leader's position (e.g. "The President learned with sadness... He reaffirms his determination to bring peace..."). What matters is that the content represents the leader's values, attitude, or policy — NOT whether it is grammatically first person.
  - "other": a document that does NOT represent the leader's own words or position — a news article reporting events, a biography, an agenda/schedule, a logistical or administrative notice, or a list — with no conveyed stance of the leader.
Prefer "official_statement" over "other" whenever the document expresses the leader's position/values/policy, even in the third person. Use "other" only when the leader's own voice or position is genuinely absent.

is_first_person: "yes" if the leader's own words are present (first-person remarks, quoted or reported), "no" if the document is wholly third-person, "unsure" otherwise. (Recorded for analysis only — an official_statement can be third-person and still be kept.)

is_substantive: does the document convey a SUBSTANTIVE expression of the leader's position — a stance, argument, commitment, priority, value, or view on a public matter (governance, policy, the economy, security, foreign affairs, society, ideology, national identity, or support for a group or cause)?
  - "yes": it expresses such a position or reasoning, even briefly — a policy statement, a values-laden address, a reaction that takes a side, a pledge of support to a group or cause.
  - "no": it is pure courtesy, ceremony, protocol, or logistics carrying NO such stance — e.g. a birthday/anniversary/holiday greeting, a routine congratulation or condolence, a thank-you or good-wishes message, a formulaic honorific, or a bare notice of an appointment/schedule/meeting.
  - "unsure": genuinely borderline, or too little text to tell.
  Judge the CONTENT, not the format or document_type: a ceremonial-event speech that articulates values or policy is "yes"; a one-line congratulatory message is "no". Recorded for downstream filtering — it does NOT by itself change document_type or whether the row is kept.

speaker: the actual person whose position the document represents, as a clean full name (no title). Determine from the text and title. A title in front of a name does NOT make a different person ("President X" IS X). Accent/transliteration variants are the same person. If the document is clearly a DIFFERENT named individual than the attributed SPEAKER (e.g. a visiting foreign leader's own speech hosted on this government site, or a minister speaking, not the president), give the ACTUAL person. If no person can be identified, null.

speaker_attributed_correct: compared to the scraped SPEAKER — "yes" if they are the same person (ignore titles/accents/spelling), "no" if a genuinely different person spoke, "unsure" if unclear or SPEAKER was blank.
  ⚠ SPEAKER IS OFTEN NOT A BYLINE. For most sources it is a per-source DEFAULT, filled in because the website belongs to one leader and the collection window falls inside that leader's term — it is a surmise from the source and the date, NOT something read off the page. So treat SPEAKER as a PRIOR, not as evidence: it is the expected speaker, and the document itself outranks it. Where the text names a different person, follow the text and answer "no" without hesitation. This matters most on whole-of-government sites, where a ministry or spokesperson item can arrive stamped with the head of government's name.

speaker_type: the actual speaker's role AT THE TIME — one of: "head_of_state", "head_of_government", "both" (e.g. an executive president who is both), "other_minister" (any cabinet minister/official who is not the leader), "foreign_visitor" (a leader/official of ANOTHER country), "other" (anyone else), or "unknown".

position: the actual speaker's short official title (e.g. "President", "Prime Minister", "King", "Foreign Minister"), or null.

date: your best estimate of the delivery date as YYYY-MM-DD, derived FROM THE DOCUMENT ITSELF. Look first for an explicit dateline at the top of the text, then for a date stated in the body, then infer from what is described (events, anniversaries, named conferences such as COP26=2021, the pandemic=2020+, elections, named officeholders). If only a year is known, use YYYY-01-01. If you genuinely cannot tell, null — do NOT fall back to the ARCHIVE CAPTURE DATE, and do not simply repeat a given DATE you cannot corroborate.
date_matches_metadata: judge the given DATE (not the capture date) — "yes" if it is consistent with the text, "no" if the text clearly indicates a different date, "unsure" otherwise. If DATE is "not available", answer "unsure".

language: ISO 639-1 two-letter code of the TEXT (e.g. "es", "fr", "en").

speech_type: choose the single best fit from EXACTLY this list: %s.
audience: the primary intended audience — choose from EXACTLY this list: %s.
venue: a short free-text venue/place/event if identifiable (city, institution, or event name), else null.

confidence: your overall confidence — "very_high", "high", "medium", or "low".
reasoning: one or two sentences explaining your key judgments (especially any speaker correction or not-a-speech call).

Guidance: most documents on these government sites ARE genuine speeches or official statements correctly attributed to the listed leader. Set document_type="other" or change the speaker only on clear evidence. If the SPEAKER appears in the KNOWN LEADERS IN OFFICE list, that strongly supports correct attribution. But the list may be INCOMPLETE: if the text shows the speaker is a national leader (head of state or head of government) who simply is NOT on the list — a new administration, a change of regime, or a leader the reference hasn't caught up with — still classify them as a leader (set speaker_type accordingly). Do NOT downgrade a genuine leader to "other_minister"/"foreign_visitor"/"other" merely because their name is absent from the list.

Respond with JSON only, exactly these keys: {"document_type","is_first_person","is_substantive","speaker","speaker_attributed_correct","speaker_type","position","date","date_matches_metadata","language","audience","speech_type","venue","confidence","reasoning"}. Use null for unknown values.""" % (
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


def _truncate(text: str, max_words: int) -> str:
    words = text.split()
    return " ".join(words[:max_words]) + " [...]" if len(words) > max_words else text


def _date_evidence_lines(row: dict) -> str:
    """The candidate/bound lines, each stated WITH its provenance.

    This is the fix for the bug that made the model's date check ornamental: the capture date used
    to be written straight into `DATE:`, so the model was handed a crawl timestamp presented as the
    document's own date and agreed with it 83-99% of the time. It is now labelled for what it is.
    """
    out = ""
    regex_date = (row.get("date_regex_recovered") or "").strip()
    if regex_date:
        out += (f"CANDIDATE DATE FROM TEXT (crude pattern match on the first lines -- UNVERIFIED; "
                f"confirm against the text or correct it): {regex_date}\n")
    capture = (row.get("wayback_capture") or "").strip()
    if capture:
        out += (f"ARCHIVE CAPTURE DATE: {capture} -- the date the Internet Archive CRAWLED this "
                f"page. The document was published on or BEFORE it, usually not more than a few "
                f"years earlier. A BOUND, NOT the answer.\n")
    return out


def build_user_message(row: dict, leaders_info: str, max_words: int = 500) -> str:
    """Assemble the per-speech prompt: scraped metadata + known leaders + truncated text.

    `DATE:` carries only a date we actually trust (the site's own field, or one confirmed by the
    date pre-pass). The archive capture date is NEVER rendered there -- see `_date_evidence_lines`.
    """
    text = _truncate(_pick_text(row), max_words)
    return (
        f"SPEAKER (expected, may be a per-source default — see the rules): "
        f"{_safe(row.get('speaker'))}\n"
        f"COUNTRY: {_safe(row.get('country'))}\n"
        f"DATE: {_safe(row.get('date'))}\n"
        f"{_date_evidence_lines(row)}"
        f"POSITION: {_safe(row.get('position'))}\n"
        f"TITLE: {_safe(_pick(row, 'title'))}\n"
        f"CONTEXT: {_safe(_pick(row, 'context'))}\n"
        f"SOURCE: {_safe(row.get('source'))}\n"
        f"KNOWN LEADERS IN OFFICE (may be incomplete): {leaders_info or 'not available'}\n\n"
        f"TEXT (first ~{max_words} words):\n{text or 'not available'}"
    )


# --------------------------------------------------------------------- PASS 1: date only
DATE_META_FIELDS = ["date", "date_confidence", "date_basis"]

DATE_SYSTEM_PROMPT = """You are a careful research assistant dating documents from national-leader websites, many of them recovered from ARCHIVED copies of those sites. Your ONLY job is to determine when the document was delivered or issued.

You will be given COUNTRY, TITLE, SOURCE (the URL), the start of the TEXT, and sometimes:
  - CANDIDATE DATE FROM TEXT: a date found by a crude pattern match on the first lines. It is UNVERIFIED -- it may be the document's dateline, or it may be a date merely mentioned in passing, or a date belonging to an unrelated item in a sidebar. Confirm it against the text, or correct it.
  - ARCHIVE CAPTURE DATE: when the Internet Archive CRAWLED the page. The document was published on or BEFORE this date, and usually not more than a few years earlier. It is a BOUND, NOT the answer. NEVER return it as the date unless the text independently supports that exact date.

How to decide, in order:
  1. An explicit DATELINE at the top of the text (very often the first or second line) -- the strongest evidence.
  2. A date stated in the body ("today, 5 December 2016", "on this 20th anniversary of...").
  3. A date embedded in the SOURCE url (e.g. /2017/05/28/).
  4. Inference from what is described: named events and summits (COP26=2021), the pandemic (2020+), an election, a named officeholder and when they held office, a stated anniversary plus a known founding year.
Beware of dates that belong to something OTHER than this document: a historical event being commemorated, a law or decree being cited, a person's biography, or a list of other articles.

Return ONE JSON object, exactly these keys:
  date: "YYYY-MM-DD", or "YYYY-01-01" if only the year is known, or null if you genuinely cannot tell. Do not guess the capture date.
  date_confidence: "high" if an explicit dateline or clearly stated date fixes it; "medium" if inferred from described events; "low" if it is little more than a guess.
  date_basis: one short sentence naming the evidence you used (e.g. "dateline '05.12.2016' on the first line", "refers to COP26"), or null.

JSON only."""


def build_date_message(row: dict, max_words: int = 200) -> str:
    """PASS 1's prompt. Deliberately carries NO leader roster: the roster is chosen from the year
    this call establishes, so including it here would reintroduce the circularity the pre-pass
    exists to break (a wrong year hands the model the wrong leaders, which then corrupts speaker
    attribution). Only the head of the text is sent -- the dateline lives there."""
    text = _truncate(_pick_text(row), max_words)
    return (
        f"COUNTRY: {_safe(row.get('country'))}\n"
        f"TITLE: {_safe(_pick(row, 'title'))}\n"
        f"SOURCE: {_safe(row.get('source'))}\n"
        f"{_date_evidence_lines(row)}"
        f"\nTEXT (first ~{max_words} words):\n{text or 'not available'}"
    )


def empty_date_meta() -> dict:
    return {k: None for k in DATE_META_FIELDS}


def parse_date_meta(content: Optional[str]) -> dict:
    """Parse PASS 1's reply into {date, date_confidence, date_basis}. Mirrors `parse_meta`:
    an unparseable reply degrades to all-None (the row then simply has no model date) rather
    than raising."""
    if not content:
        return empty_date_meta()
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return empty_date_meta()
    out = {}
    for k in DATE_META_FIELDS:
        v = data.get(k) if isinstance(data, dict) else None
        if v is None:
            out[k] = None
        elif isinstance(v, str):
            out[k] = v.strip() or None
        else:
            out[k] = str(v)
    return out


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


async def _call(client, config, system_prompt: str, user_message: str, semaphore, max_tokens: int):
    """One async, rate-limited, JSON-mode call. Raises on API error (caught by the batch runner's
    return_exceptions)."""
    import asyncio
    async with semaphore:
        await asyncio.sleep(config.rate_limit_delay)
        resp = await client.chat.completions.create(
            model=config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=config.temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content


async def extract_one(client, config, user_message: str, semaphore) -> dict:
    """One async, rate-limited, JSON-mode extraction call. Returns a parsed meta dict."""
    content = await _call(client, config, SYSTEM_PROMPT, user_message, semaphore, config.max_tokens)
    return parse_meta(content)


async def extract_date_one(client, config, user_message: str, semaphore) -> dict:
    """PASS 1: one date-only call. Returns {date, date_confidence, date_basis}."""
    content = await _call(client, config, DATE_SYSTEM_PROMPT, user_message, semaphore,
                          getattr(config, "date_pass_max_tokens", 200))
    return parse_date_meta(content)
