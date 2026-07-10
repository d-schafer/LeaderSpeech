"""Field extraction + text cleanup from a single speech page.

Given a speech page's HTML and its recipe, pull title / text / date / speaker /
context using each field's fallback chain of selectors, parse the date (in the
source's language), and clean the text the same way the old R scrapers did:
strip carriage returns, collapse runs of whitespace, drop empty lines.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import dateparser
from bs4 import BeautifulSoup
from dateparser.search import search_dates

from . import pdf
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


def match_url(spec: Optional[FieldSpec], url: Optional[str]) -> Optional[str]:
    """Extract a field value from the page URL via `spec.url_regex`. Returns group(1) when
    the regex captures, else the whole match. Used when there's no DOM (PDFs) or as a
    fallback when no selector matched. None if there's no url_regex or no match."""
    if spec is None or not spec.url_regex or not url:
        return None
    m = re.search(spec.url_regex, url)
    if not m:
        return None
    return m.group(1) if m.groups() else m.group(0)


def _iso_from_named_groups(m: re.Match) -> Optional[str]:
    """If a date url_regex captured named year/month/day groups, assemble an ISO date
    directly — this sidesteps dateparser's DD/MM ambiguity for numeric archive paths like
    `/2003/18-06-...`. Returns None if the groups are absent or don't form a real date."""
    gd = m.groupdict()
    if not (gd.get("year") and gd.get("month") and gd.get("day")):
        return None
    try:
        dt = datetime(int(gd["year"]), int(gd["month"]), int(gd["day"]))
    except (ValueError, TypeError):
        return None
    if dt.year < 1900 or dt.year > datetime.now().year + 1:
        return None
    return dt.date().isoformat()


def date_from_url(spec: Optional[FieldSpec], url: Optional[str],
                  languages: Optional[list[str]] = None) -> Optional[str]:
    """Parse a date out of the page URL via `spec.url_regex`. Prefers named
    year/month/day groups (assembled unambiguously as ISO); otherwise parses the matched
    substring with `parse_date`. None if there's no url_regex or no usable date."""
    if spec is None or not spec.url_regex or not url:
        return None
    m = re.search(spec.url_regex, url)
    if not m:
        return None
    iso = _iso_from_named_groups(m)
    if iso:
        return iso
    raw = m.group(1) if m.groups() else m.group(0)
    return parse_date(raw, languages)


def parse_date(raw: Optional[str], languages: Optional[list[str]] = None) -> Optional[str]:
    """Parse a date in the source's language. First try the whole string; if that
    fails (e.g. the date is wrapped in noise like 'Buenos Aires, 25 de mayo de
    2024' or 'Publié le 14 juillet 2023'), search for a date inside it."""
    if not raw:
        return None
    text = raw.strip()
    dt = None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = None

    langs = languages or None
    if dt is None:
        dt = dateparser.parse(text, languages=langs)
    if dt is None:
        try:
            found = search_dates(text, languages=langs)
        except Exception:
            found = None
        if found:
            dt = found[0][1]
    if dt is None:
        return None
    # Reject implausible parses (e.g. dateparser returning year 0001 from a date
    # fragment with no real year). A blank date is honest; a wrong one corrupts any
    # time-series. The leader-tenure key / cleanup step can fill these later.
    if dt.year < 1900 or dt.year > datetime.now().year + 1:
        return None
    return dt.date().isoformat()


def extract_record(html: str, url: str, recipe: Recipe) -> dict:
    """Return the raw per-speech fields (doc_id is assigned later, by run.py)."""
    soup = BeautifulSoup(html, "lxml")

    # Each field: try the selector chain first, then fall back to the URL (url_regex) —
    # purely additive, since existing recipes set no url_regex.
    def field(spec):
        return first_match(soup, spec) or match_url(spec, url)

    speaker = clean_text(field(recipe.speaker)) if recipe.speaker else ""
    if not speaker and recipe.speaker_default:
        speaker = recipe.speaker_default

    date_raw = first_match(soup, recipe.date)
    date = parse_date(date_raw, recipe.date_languages)
    if date is None:
        date = date_from_url(recipe.date, url, recipe.date_languages)
    return {
        "title": clean_text(field(recipe.title)),
        "text": clean_text(first_match(soup, recipe.text)),
        "date": date,
        "date_raw": date_raw,
        "speaker": speaker,
        "context": clean_text(field(recipe.context)) if recipe.context else "",
        "source": url,
    }


def _first_line(text: str, limit: int = 200) -> str:
    """The first non-empty line of a body, capped — a rough title for PDFs that carry no
    URL/selector title (the metadata-cleaning step refines it later)."""
    for line in (text or "").split("\n"):
        line = line.strip()
        if line:
            return line[:limit]
    return ""


def extract_pdf_record(data: bytes, url: str, recipe: Recipe) -> dict:
    """Build a per-speech record from PDF bytes. The body comes from the PDF text; there's
    no DOM, so title/date/speaker are pulled from the URL via each field's `url_regex`
    (with the usual `speaker_default`), and the title falls back to the PDF's first line."""
    text = clean_text(pdf.pdf_bytes_to_text(data))

    title = clean_text(match_url(recipe.title, url)) or _first_line(text)
    date = date_from_url(recipe.date, url, recipe.date_languages)
    speaker = clean_text(match_url(recipe.speaker, url)) if recipe.speaker else ""
    if not speaker and recipe.speaker_default:
        speaker = recipe.speaker_default
    context = clean_text(match_url(recipe.context, url)) if recipe.context else ""
    return {
        "title": title,
        "text": text,
        "date": date,
        "date_raw": "",
        "speaker": speaker,
        "context": context,
        "source": url,
    }
