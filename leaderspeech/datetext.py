"""Parse a delivery date off the HEAD of a speech body — conservatively.

Many archived pages carry no machine-readable date (the recipe's `date` selector misses and the
generic/trafilatura fallback supplies the body), yet the date is sitting in plain sight as the
first line of the text:

    05.12.2016
    The following congratulatory message has come from President of the Russian Federation...

WHY THIS IS SO STRICT
---------------------
The obvious implementation — "find the first date in the first few hundred characters" — was
prototyped against rows that already carry a known-good scraped date (free ground truth) and got
the YEAR WRONG 45-64% of the time on arm_president_wayback / blr_president_english_wayback /
aze_president_english_wayback. It grabs prose:

    "20 January 1990 went down in the history of modern Azerbaijan as one of the most tragic..."
    "By the Presidential decree of December 27, 2008 Vakhtang Darchinian..."

Those are dates IN the text, not the date OF the text. So this module accepts a date only when a
whole HEAD LINE *is* a date — nothing else on the line but punctuation, a weekday name, or a
"Published:"-style label — and the line is short. Measured under that rule: 99.1% hit rate on
Uzbekistan, zero dates-after-the-capture corpus-wide, and 98.9%/100% agreement with known-good
scraped dates on ind_pmindia / ukr_president_english.

A looser variant that also accepted a date at the END of a line (the Nigeria shape,
"...counter-Terrorism Campaign. March 4, 2015") gained 76 rows and dropped ind_pmindia's precision
from 98.9% to 60.3%. It is deliberately NOT implemented; that shape is left to the model.

WHAT THIS IS FOR
----------------
The result is a CANDIDATE, never an answer. It is shown to the model labelled as an unverified
pattern match to confirm or correct, and it is stored win-or-lose in `date_regex_recovered`. The
model outranks it (see clean_structure_metadata.pipeline.resolve_date).

`parse_text_head(text)` returns (date_str, precision):
  * ("YYYY-MM-DD", "day") — a head line that IS a date
  * (None, None)          — no unambiguous head date. Bare years are NEVER returned.

Shared by both `text_scraper` (writes the column) and `clean_structure_metadata` (adjudicates it),
which is why it lives at the package root. Pure; `dateparser` is used only for tier 2 and is
optional at runtime.
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache

# --- tier 1: month names ----------------------------------------------------------------------
_MONTH_NAMES: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTHS_RE = "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))

# Everything a real date line is allowed to carry BESIDES the date itself: punctuation used as
# separators/decoration by CMS templates (Belarus wraps its date in table pipes: "| 19.11.2010 |"),
# label words, and weekday names (Azerbaijan: "Friday, November 08, 2013").
_NOISE = re.compile(
    r"^(?:[\s|/\\\-–—,.:;()\[\]*«»\"'#]|"
    r"published|posted|updated|last|modified|date[d]?|on|at|time|print|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)*$",
    re.IGNORECASE,
)

# ISO: negative lookarounds keep it out of URL slugs like /wp-content/uploads/2015-07-20/x
_ISO = re.compile(r"(?<![\d/\-])(\d{4})-(\d{1,2})-(\d{1,2})(?![\d/\-])")
# Dotted numerics are ALWAYS day-first. No government CMS in this corpus writes MM.DD.YYYY, and
# this is what makes Uzbekistan/Belarus/Georgia parse correctly.
_DOTTED = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")
_D_MONTH_Y = re.compile(
    rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTHS_RE})\.?,?\s+(\d{{4}})(?!\d)",
    re.IGNORECASE,
)
_MONTH_D_Y = re.compile(
    rf"({_MONTHS_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})(?!\d)",
    re.IGNORECASE,
)
# Slash-separated numerics: accepted ONLY when a component > 12 settles DD/MM vs MM/DD. See below.
_SLASHED = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")

# tier 2 gate: a 4-digit year plus at least one letter (all-numeric shapes belong to tier 1, so
# dateparser's DATE_ORDER ambiguity never comes into play here).
_HAS_YEAR = re.compile(r"(?<!\d)\d{4}(?!\d)")
_HAS_ALPHA = re.compile(r"[^\W\d_]", re.UNICODE)

_MIN_YEAR = 1990   # see parse_text_head docstring


def head_lines(text, lines: int = 4) -> list[str]:
    """The first `lines` non-empty, stripped lines of a body."""
    if not isinstance(text, str) or not text:
        return []
    out: list[str] = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        out.append(s)
        if len(out) >= lines:
            break
    return out


def _valid(y: int, m: int, d: int, min_year: int, max_year: int) -> str | None:
    """ISO string if (y, m, d) is a real date inside the plausibility window, else None."""
    if not (min_year <= y <= max_year):
        return None
    try:
        datetime(y, m, d)
    except ValueError:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def _tier1(line: str, min_year: int, max_year: int) -> str | None:
    """A date occupying the WHOLE line (modulo noise), via unambiguous regex shapes."""
    for rx, order in (
        (_ISO, "ymd"),
        (_DOTTED, "dmy"),
        (_D_MONTH_Y, "d_name_y"),
        (_MONTH_D_Y, "name_d_y"),
        (_SLASHED, "slash"),
    ):
        m = rx.search(line)
        if not m:
            continue
        # the rest of the line must be pure decoration -- this is the whole safety property
        rest = line[: m.start()] + line[m.end():]
        if not _NOISE.match(rest):
            continue
        if order == "ymd":
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif order == "dmy":
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif order == "d_name_y":
            d, mo, y = int(m.group(1)), _MONTH_NAMES[m.group(2).lower()], int(m.group(3))
        elif order == "name_d_y":
            mo, d, y = _MONTH_NAMES[m.group(1).lower()], int(m.group(2)), int(m.group(3))
        else:
            # Slash numerics are genuinely ambiguous: 05/12/2016 is 5 Dec in Europe and 12 May in
            # the US, and `source_language` cannot settle it (it reads "English" for Uzbekistan,
            # Albania AND Nigeria -- a language, not a locale). Guessing would be indefensible in
            # a research dataset, so accept ONLY when one component is > 12.
            a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if a > 12 and b <= 12:
                d, mo = a, b
            elif b > 12 and a <= 12:
                mo, d = a, b
            else:
                continue
        if iso := _valid(y, mo, d, min_year, max_year):
            return iso
    return None


@lru_cache(maxsize=4096)
def _tier2_cached(line: str, langs: tuple[str, ...] | None) -> str | None:
    """dateparser with STRICT_PARSING, for non-English month names. Cached: archived page heads
    repeat heavily across captures, and this is the only part that costs anything."""
    try:
        import dateparser
    except Exception:
        return None
    try:
        dt = dateparser.parse(
            line,
            languages=list(langs) if langs else None,
            settings={"STRICT_PARSING": True},
        )
    except Exception:
        return None
    if dt is None:
        return None
    return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"


def parse_text_head(
    text,
    *,
    lines: int = 4,
    max_line_chars: int = 60,
    min_year: int = _MIN_YEAR,
    max_year: int | None = None,
    languages: list[str] | None = None,
    use_dateparser: bool = True,
) -> tuple[str | None, str | None]:
    """Best Gregorian date sitting on a DATE LINE in the head of `text`.

    A "date line" is a head line that IS a date apart from punctuation, a weekday name, or a label
    word, and is at most `max_line_chars` long. Prose that merely CONTAINS a date is refused --
    that distinction is the entire point of this module (see the module docstring).

    `min_year` defaults to 1990 rather than the scraper's 1900: a head-line date older than that on
    a government CMS is nearly always junk, and ~30 wayback CSVs carry no `wayback_capture` column,
    so the caller's capture cross-check silently no-ops for them and cannot be relied on as the
    only guard. Bare years are never returned; the caller gets a full date or nothing.
    """
    if not isinstance(text, str) or not text:
        return None, None
    if max_year is None:
        max_year = datetime.now().year + 1
    langs = tuple(languages) if languages else None

    for line in head_lines(text, lines):
        if len(line) > max_line_chars:
            continue
        if iso := _tier1(line, min_year, max_year):
            return iso, "day"
        if not use_dateparser:
            continue
        if not (_HAS_YEAR.search(line) and _HAS_ALPHA.search(line)):
            continue
        iso = _tier2_cached(line, langs)
        if iso:
            y, mo, d = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
            if _valid(y, mo, d, min_year, max_year):
                return iso, "day"
    return None, None


def lang_hint(row: dict) -> list[str] | None:
    """ISO-639-1 hint for dateparser, from a row's detected/declared language.

    Reuses the translator's `resolve_src_lang` (detected_language > source_language name -> ISO)
    rather than duplicating that mapping. Returns None on any doubt — dateparser then searches all
    languages, which is the safe default; a WRONG hint is worse than none.
    """
    if not isinstance(row, dict):
        return None
    try:
        from .translate.pipeline import resolve_src_lang
        code = resolve_src_lang(row)
    except Exception:
        return None
    if code and len(str(code)) == 2 and str(code).isalpha():
        return [str(code).lower()]
    return None
