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

from . import msword, pdf
from .recipe import FieldSpec, KeepIf, Listing, Recipe

_INLINE_WS = re.compile(r"[ \t\f\v]+")


def clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.replace("\r", "\n")
    lines = [_INLINE_WS.sub(" ", line).strip() for line in s.split("\n")]
    return "\n".join(line for line in lines if line)


def _select(soup: BeautifulSoup, selector: str) -> list:
    """soup.select, tolerating a malformed selector (treated as matching nothing)."""
    try:
        return soup.select(selector)
    except Exception:
        return []


def first_match(soup: BeautifulSoup, spec: Optional[FieldSpec]) -> Optional[str]:
    """Return the value from the first selector in the chain that matches."""
    if spec is None:
        return None
    for selector in spec.selectors:
        elements = _select(soup, selector)
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
                if m:
                    value = m.group(0)
                elif spec.regex_required:
                    # An explicit "the regex IS the field" contract: a miss means this
                    # selector didn't really match, so keep walking the chain rather than
                    # returning the unfiltered blob (see FieldSpec.regex_required).
                    continue
            return value
    return None


def matched_selector(soup, spec: Optional[FieldSpec]) -> Optional[str]:
    """Which selector in the chain matched first — i.e. the one `first_match` used."""
    if spec is None:
        return None
    for selector in spec.selectors:
        if _select(soup, selector):
            return selector
    return None


# Fields that per-item metadata may supply, in the order run.py has always filled them.
META_FIELDS = ("text", "title", "date", "speaker")


def listing_meta(item, listing: Listing,
                 languages: Optional[list[str]] = None) -> dict:
    """Metadata read out of ONE listing block, for the speech link that block contains.

    `item` is a bs4 Tag, so `first_match`'s `.select` is scoped to that block — and the
    scoping is the whole point (see `recipe.Listing`).

    The date is parsed with the SOURCE's `date_languages`. This is the one place that
    differs from api/feed metadata on purpose: those dates arrive machine-formatted
    (ISO/RFC) and are deliberately parsed *without* a language hint, which would mis-order
    them; a listing date is written in the site's own language ("Oct. 6, 2023").

    Never returns `text` — see `recipe.Listing`. `_from` records which selector matched, so
    the probe can report provenance instead of "NO MATCH" over a value that resolved fine.
    """
    meta: dict = {}
    origin: dict = {}
    title = clean_text(first_match(item, listing.item_title) or "")
    if title:
        meta["title"] = title
        origin["title"] = f"listing: {matched_selector(item, listing.item_title)}"
    raw = first_match(item, listing.item_date)
    date = parse_date(raw, languages)
    if date:
        meta["date"] = date
        meta["date_raw"] = clean_text(raw)
        origin["date"] = f"listing: {matched_selector(item, listing.item_date)}"
    if meta:
        meta["_from"] = origin
    return meta


def apply_entry_meta(rec: dict, entry: Optional[dict]) -> list[str]:
    """Fill any field the page extraction left EMPTY from per-item metadata carried
    alongside the URL — an api/feed row, or the HTML listing block the link came from.
    Mutates `rec`; returns the names the metadata actually supplied.

    One rule, and the safety of the whole feature rests on it: this only ever fills a
    blank. A value the page produced always wins. Returning the filled names is what lets
    the probe say WHERE a value came from rather than printing "✗ NO MATCH" over a field
    that resolved perfectly well.
    """
    if not entry:
        return []
    filled = []
    for name in META_FIELDS:
        if rec.get(name):
            continue
        value = entry.get(name)
        if not value:
            continue
        rec[name] = value
        filled.append(name)
    return filled


def entry_source(entry: Optional[dict], name: str) -> str:
    """How to name the carried metadata that supplied `name`: the listing selector that
    matched, else a generic label. Shared so run's log and probe's report agree."""
    return ((entry or {}).get("_from") or {}).get(name) or "carried entry metadata"


def should_keep(spec: Optional[KeepIf], soup: Optional[BeautifulSoup] = None,
                text: str = "") -> bool:
    """Does this fetched page belong to the source? True whenever there's no `keep_if`.

    Evaluated per page, after fetch and before a row is written, so it behaves identically
    for `wayback`, `api`/`feed` and ordinary listings — `wayback` in particular never
    crawls a listing (it enumerates CDX captures and treats each as a speech page), so an
    on-page category is the ONLY category signal an archive harvest has. See
    `recipe.KeepIf` for the modes.
    """
    if spec is None:
        return True
    if spec.selectors:
        if soup is None:
            # No DOM to evaluate — a PDF, or api/feed text carried without a page fetch.
            # Keeping the page is the safe answer: a selector predicate cannot be judged
            # here, and silently rejecting an entire source is far worse than passing a
            # few rows to the cleaner's gate. Use a selector-less keep_if to filter these.
            return True
        hay = "\n".join(el.get_text(" ") for sel in spec.selectors for el in _select(soup, sel))
    else:
        # No selectors: test the whole document — the page's full text, or a PDF's
        # extracted text. Deliberately independent of the field selectors, so the verdict
        # can't change with the generic-extractor fallback.
        hay = soup.get_text(" ") if soup is not None else (text or "")
    hit = bool(re.search(spec.pattern, hay)) if spec.pattern else bool(hay.strip())
    return not hit if spec.negate else hit


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


def _expand_two_digit_year(raw: str) -> str:
    """Widen a 2-digit year with the POSIX pivot (69-99 -> 19xx, 00-68 -> 20xx).

    Vintage government sites often date a speech in the FILENAME as DDMMYY —
    presidentofindia.nic.in's `/sp010108.html` is 1 January 2008, and there are ~1,000 of
    them. Without this, `int("08")` is year 8, the <1900 sanity check rejects it, and the
    date silently falls through to a body-text regex (the failure mode that dated Koizumi's
    2003 press conference to 2001-09-11). Only ever applied to an exactly-2-digit group, so
    4-digit years are untouched."""
    return ("19" if int(raw) >= 69 else "20") + raw


def _iso_from_named_groups(m: re.Match) -> Optional[str]:
    """If a date url_regex captured named year/month/day groups, assemble an ISO date
    directly — this sidesteps dateparser's DD/MM ambiguity for numeric archive paths like
    `/2003/18-06-...`. A 2-digit year group is widened (see _expand_two_digit_year), which
    is what makes DDMMYY filenames usable. Returns None if the groups are absent or don't
    form a real date."""
    gd = m.groupdict()
    if not (gd.get("year") and gd.get("month") and gd.get("day")):
        return None
    year = gd["year"]
    if len(year) == 2 and year.isdigit():
        year = _expand_two_digit_year(year)
    try:
        dt = datetime(int(year), int(gd["month"]), int(gd["day"]))
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
    gd = m.groupdict()
    if gd.get("year") and gd.get("month") and gd.get("day"):
        # The recipe asked for an unambiguous assembled date. If the captured parts don't
        # form a real one, that is a MISS — do NOT fall through to parse_date, which would
        # be handed group(1) (a bare day or year) and let dateparser fill the rest of the
        # date from TODAY. A blank date beats a plausible wrong one: the resolved date
        # picks the tenure roster, so a wrong year corrupts speaker attribution too.
        return _iso_from_named_groups(m)
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
        # Not a schema column (like date_raw) — run.py reads it to decide whether this
        # page becomes a row at all.
        "keep": should_keep(recipe.keep_if, soup),
    }


def _first_line(text: str, limit: int = 200) -> str:
    """The first non-empty line of a body, capped — a rough title for PDFs that carry no
    URL/selector title (the metadata-cleaning step refines it later)."""
    for line in (text or "").split("\n"):
        line = line.strip()
        if line:
            return line[:limit]
    return ""


def looks_like_document(data) -> bool:
    """True if these bytes are a binary speech document the engine can route to
    :func:`document_to_text` — a PDF, a .docx, or a legacy .doc. Used to decide whether a
    `content_type: pdf` payload is a real document (else it's parsed as HTML)."""
    return pdf.looks_like_pdf(data) or msword.looks_like_docx(data) or msword.looks_like_doc(data)


def document_to_text(data: bytes, recipe: Recipe) -> str:
    """Extract text from binary document bytes, dispatching by file type: .docx and legacy
    .doc via :mod:`msword`, everything else via :mod:`pdf` (with the recipe's OCR settings).
    A `content_type: pdf` recipe can thus mix PDF and Word speech files (e.g. Botswana gov.bw)."""
    if msword.looks_like_docx(data):
        return msword.docx_bytes_to_text(data)
    if msword.looks_like_doc(data):
        return msword.doc_bytes_to_text(data)
    return pdf.pdf_bytes_to_text(data, ocr=recipe.pdf_ocr, ocr_language=recipe.pdf_ocr_language)


def extract_pdf_record(data: bytes, url: str, recipe: Recipe) -> dict:
    """Build a per-speech record from binary document bytes (PDF or Word). The body comes from
    the document text; there's no DOM, so title/date/speaker are pulled from the URL via each
    field's `url_regex` (with the usual `speaker_default`), and the title falls back to the
    document's first line."""
    text = clean_text(document_to_text(data, recipe))

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
        # No DOM here: a selector-based keep_if is a no-op, a pattern-only one tests the
        # PDF's extracted text.
        "keep": should_keep(recipe.keep_if, None, text),
    }
