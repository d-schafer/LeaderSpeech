"""Field extraction + text cleanup from a single speech page.

Given a speech page's HTML and its recipe, pull title / text / date / speaker /
context using each field's fallback chain of selectors, parse the date (in the
source's language), and clean the text the same way the old R scrapers did:
strip carriage returns, collapse runs of whitespace, drop empty lines.
"""

from __future__ import annotations

import re
from typing import Optional

import dateparser
from bs4 import BeautifulSoup
from dateparser.search import search_dates

from .recipe import FieldSpec, Recipe

_INLINE_WS = re.compile(r"[ \t\f\v]+")


def clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.replace("\r", "\n")
    lines = [_INLINE_WS.sub(" ", line).strip() for line in s.split("\n")]
    return "\n".join(line for line in lines if line)


def first_match(soup: BeautifulSoup, spec: Optional[FieldSpec]) -> Optional[str]:
    """Return the value from the first selector in the chain that matches."""
    if spec is None:
        return None
    for selector in spec.selectors:
        try:
            elements = soup.select(selector)
        except Exception:
            continue  # tolerate a malformed selector, try the next
        if not elements:
            continue
        if spec.attr:
            value = elements[0].get(spec.attr)
        else:
            # join all matches so multi-paragraph bodies come through whole
            value = "\n".join(el.get_text("\n") for el in elements)
        if value:
            if spec.regex:
                m = re.search(spec.regex, value)
                value = m.group(0) if m else value
            return value
    return None


def parse_date(raw: Optional[str], languages: Optional[list[str]] = None) -> Optional[str]:
    """Parse a date in the source's language. First try the whole string; if that
    fails (e.g. the date is wrapped in noise like 'Buenos Aires, 25 de mayo de
    2024' or 'Publié le 14 juillet 2023'), search for a date inside it."""
    if not raw:
        return None
    langs = languages or None
    dt = dateparser.parse(raw, languages=langs)
    if dt is None:
        try:
            found = search_dates(raw, languages=langs)
        except Exception:
            found = None
        if found:
            dt = found[0][1]
    return dt.date().isoformat() if dt else None


def extract_record(html: str, url: str, recipe: Recipe) -> dict:
    """Return the raw per-speech fields (doc_id is assigned later, by run.py)."""
    soup = BeautifulSoup(html, "lxml")

    speaker = clean_text(first_match(soup, recipe.speaker)) if recipe.speaker else ""
    if not speaker and recipe.speaker_default:
        speaker = recipe.speaker_default

    date_raw = first_match(soup, recipe.date)
    return {
        "title": clean_text(first_match(soup, recipe.title)),
        "text": clean_text(first_match(soup, recipe.text)),
        "date": parse_date(date_raw, recipe.date_languages),
        "date_raw": date_raw,
        "speaker": speaker,
        "context": clean_text(first_match(soup, recipe.context)) if recipe.context else "",
        "source": url,
    }
