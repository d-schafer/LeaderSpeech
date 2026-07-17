"""Diagnose a recipe against the live site — without a full run.

Fetches one listing page and a couple of speech pages and reports, per field,
*which selector matched* (and a preview) or that none did, plus whether the
generic fallback would rescue the page. This is the fast way for a person — or an
agent working a recipe issue — to see why extraction is failing and exactly which
selector to fix, instead of guessing from a full crawl.

    python -m leaderspeech.text_scraper.probe --recipe recipes/fra_elysee.yml
    python -m leaderspeech.text_scraper.probe --recipe recipes/fra_elysee.yml --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from .extract import (clean_text, date_from_url, extract_pdf_record, extract_record,
                      first_match, match_url, parse_date)
from .fallback_generic import extract_generic
from .fetch import Fetcher
from .paginate import extract_links, harvest_links
from .pdf import is_pdf_url, looks_like_pdf
from .recipe import ContentType, FieldSpec, PaginationType, WaybackExtend, load_recipe
from . import api, feed, index, wayback

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FIELDS = ("title", "text", "date", "speaker", "context")


def _which_selector(soup, spec: FieldSpec | None):
    """Return (matched_selector | None, n_elements) for the first selector that hits."""
    if spec is None:
        return None, 0
    for sel in spec.selectors:
        try:
            els = soup.select(sel)
        except Exception:
            continue
        if els:
            return sel, len(els)
    return None, 0


def _tried(recipe, name: str, spec: FieldSpec | None) -> list[str]:
    """Everything the recipe would try for this field, in order — selectors, then the
    field's `url_regex`, then `speaker_default`. Reported as-is when a field resolves to
    nothing, so "NO MATCH (tried: [])" can't happen for a field that has a url_regex."""
    out = list(spec.selectors) if spec else []
    if spec and spec.url_regex:
        out.append(f"url_regex: {spec.url_regex}")
    if name == "speaker" and recipe.speaker_default:
        out.append(f"speaker_default: {recipe.speaker_default}")
    return out


def _field_sources(recipe, name: str, spec: FieldSpec | None, soup, url: str):
    """Candidate (label, value) pairs in exactly the precedence `extract.extract_record`
    uses. The first pair with a value is where the field's value actually came from.

    This exists so the probe reports the *mechanism* that resolved a field rather than
    just "did a CSS selector match" (issue #54). A field with no selectors that gets its
    value from `url_regex` is a supported, deliberate design — several recipes depend on
    it (`aus_gg_wayback`, `tha_royaloffice_wayback`, every PDF recipe) precisely because a
    body-date selector would be WRONG there — and flagging it ✗ invites a reviewer to
    "fix" a working recipe by bolting a date selector back on.
    """
    sel, _ = _which_selector(soup, spec)
    raw = first_match(soup, spec)
    url_label = f"url_regex: {spec.url_regex}" if spec and spec.url_regex else None

    if name == "text":                       # text has no url_regex arm (see extract_record)
        return [(sel, clean_text(raw))]
    if name == "date":                       # selector text must PARSE, else the URL wins
        return [(sel, parse_date(raw, recipe.date_languages)),
                (url_label, date_from_url(spec, url, recipe.date_languages))]

    cands = [(sel, clean_text(raw or "")), (url_label, clean_text(match_url(spec, url) or ""))]
    if name == "speaker" and recipe.speaker_default:
        cands.append((f"speaker_default: {recipe.speaker_default}", recipe.speaker_default))
    return cands


def _html_field_report(recipe, name: str, soup, url: str, rec: dict) -> dict:
    spec = getattr(recipe, name)
    sel, ncount = _which_selector(soup, spec)
    source = next((label for label, value in _field_sources(recipe, name, spec, soup, url)
                   if value and label), None)
    note = None
    # A date selector that matched but whose text won't parse is otherwise invisible: the
    # field either resolves via url_regex (looking like the selector was never needed) or
    # blanks with no stated reason.
    if name == "date" and sel and source != sel:
        note = (f"selector {sel!r} matched {clean_text(first_match(soup, spec))[:40]!r} "
                f"but it did not parse as a date")
    return {
        "matched_selector": source,
        "n_elements": ncount,
        "tried": _tried(recipe, name, spec),
        "note": note,
        "value_preview": clean_text(rec[name])[:100] if name != "text" else "",
        "text_len": len(rec["text"]) if name == "text" else None,
    }


def _sample_evenly(entries: list, n: int) -> list:
    """Pick `n` roughly even samples; return all entries when `n` is large enough."""
    if n < len(entries):
        step = max(len(entries) // n, 1)
        return [entries[min(i * step, len(entries) - 1)] for i in range(n)]
    return list(entries)


def _pdf_page_report(recipe, url: str, rec: dict) -> dict:
    """Per-page diagnostics for a PDF sample. PDFs have no DOM, so a field can only
    resolve from its url_regex (or, for text, the extracted PDF body; for title, the
    body's first line); the shape mirrors the HTML page report so `_print` renders it the
    same way."""
    fields = {}
    for name in FIELDS:
        spec = getattr(recipe, name)
        if name == "text":
            matched = "(pdf body)" if rec["text"] else None
            tried = ["(PDF body extraction)"]
        else:
            # Same precedence as extract_pdf_record: url_regex, then the per-field
            # fallbacks. Naming the mechanism keeps ✗ meaning "resolved to nothing".
            url_regex = getattr(spec, "url_regex", None) if spec else None
            # `date` must be compared through date_from_url, NOT match_url: extract_pdf_record
            # PARSES the url_regex match into an ISO date, so rec["date"] is "2022-12-06"
            # while match_url returns the raw first group ("12"). Comparing those never
            # matches, which reported a resolved date as ✗ NO MATCH — the very thing #54 is
            # about, in the PDF path.
            from_url = (date_from_url(spec, url, recipe.date_languages) if name == "date"
                        else clean_text(match_url(spec, url) or ""))
            matched = None
            if not rec.get(name):
                matched = None
            elif url_regex and from_url and from_url == rec[name]:
                matched = f"url_regex: {url_regex}"
            elif name == "speaker" and rec[name] == recipe.speaker_default:
                matched = f"speaker_default: {recipe.speaker_default}"
            elif name == "title":
                matched = "(pdf body first line)"
            tried = _tried(recipe, name, spec)
            if name == "title":
                tried.append("(pdf body first line)")
        fields[name] = {
            "matched_selector": matched,
            "n_elements": 0,
            "tried": tried,
            "note": None,
            "value_preview": clean_text(rec[name])[:100] if name != "text" else "",
            "text_len": len(rec["text"]) if name == "text" else None,
        }
    return {
        "url": url,
        "parsed_date": rec["date"],
        "recipe_text_len": len(rec["text"]),
        "generic_text_len": 0,
        "keep": rec.get("keep", True),
        "fields": fields,
    }


def _listing_count(report_listing: dict) -> tuple[str, int]:
    if "snapshots_found" in report_listing:
        return "snapshot(s)", report_listing.get("snapshots_found", 0)
    return "link(s)", report_listing.get("links_found", 0)


def _diagnose_pages(sample, recipe, *, fetcher=None, wayback_client=None,
                    is_wayback: bool = False) -> list[dict]:
    """Fetch each sampled item and report where every field's value came from.

    `sample` holds CDX capture dicts when `is_wayback`, else speech-page URLs. `recipe`
    supplies the selectors — for a `wayback_extend` probe that is the recipe *with the
    extend overrides applied*, so what gets validated is exactly what the run will use.
    """
    pages = []
    for item in sample:
        pdf_data = None
        try:
            url = item["original"] if is_wayback else item
            want_pdf = recipe.content_type == ContentType.pdf or (
                recipe.content_type == ContentType.auto and is_pdf_url(url))
            if is_wayback and want_pdf:
                _, data = wayback.fetch_snapshot_bytes(item, delay=0.0, client=wayback_client)
                pdf_data = data if looks_like_pdf(data) else None
                phtml = None if pdf_data else data.decode("utf-8", "replace")
            elif is_wayback:
                phtml = wayback.fetch_snapshot(item, delay=0.0, client=wayback_client)
            elif want_pdf:
                _, data = fetcher.get_bytes(url)
                pdf_data = data if looks_like_pdf(data) else None
                phtml = None if pdf_data else data.decode("utf-8", "replace")
            else:
                phtml = fetcher.get(url)
        except Exception as e:
            bad_url = item.get("original") if isinstance(item, dict) else item
            pages.append({"url": bad_url, "error": f"{type(e).__name__}: {e}"})
            continue
        if pdf_data is not None:
            pages.append(_pdf_page_report(recipe, url, extract_pdf_record(pdf_data, url, recipe)))
            continue
        soup = BeautifulSoup(phtml, "lxml")
        rec = extract_record(phtml, url, recipe)              # what the recipe yields
        gen = extract_generic(phtml, url)                     # what generic would yield
        pages.append({
            "url": url,
            "parsed_date": rec["date"],
            "recipe_text_len": len(rec["text"]),
            "generic_text_len": len(gen["text"]),
            "keep": rec.get("keep", True),      # False => keep_if would drop this page
            "fields": {name: _html_field_report(recipe, name, soup, url, rec)
                       for name in FIELDS},
        })
    return pages


def _keep_if_summary(recipe, pages: list) -> dict:
    """How the recipe's `keep_if` judged the sampled pages. The count is the point: a
    keep_if that quietly matches nothing empties the source, and a probe that only showed
    per-field ticks would look perfectly healthy while doing it (issue #52)."""
    judged = [p for p in pages if "error" not in p]
    kept = [p for p in judged if p.get("keep", True)]
    return {
        "selectors": list(recipe.keep_if.selectors),
        "pattern": recipe.keep_if.pattern,
        "negate": recipe.keep_if.negate,
        "sampled": len(judged),
        "kept": len(kept),
        "filtered_out": len(judged) - len(kept),
    }


def _extend_to_date(recipe, ext, out_root: str, override: str | None) -> tuple[str | None, str]:
    """The CDX `to` bound for a wayback_extend probe, and where it came from.

    A real run bounds the archive at the earliest date the LIVE crawl scraped — a value
    that only exists after that crawl. A probe has to approximate it: an explicit
    override, else the recipe's `wayback_to`, else the floor of an already-scraped CSV.
    With none of those the archive is unbounded, which is worth saying out loud (see
    `_print`): the sample then includes recent captures whose layout still matches the
    live site, which is precisely the case a probe cannot catch drift in.
    """
    if override:
        return override, "--wayback-to"
    if ext.wayback_to:
        return ext.wayback_to, "recipe wayback_extend.wayback_to"
    floor = index.date_floor(Path(out_root) / recipe.country / f"{recipe.source_id}.csv")
    if floor:
        return floor.replace("-", ""), f"date_floor of the scraped CSV ({floor})"
    return None, "unbounded (nothing scraped yet, no wayback_to)"


def probe(recipe_path: str, n: int = 2, spread: bool = False, extend_wayback: bool = False,
          wayback_to: str | None = None, out_root: str = "data/scraped") -> dict:
    recipe = load_recipe(recipe_path)
    report: dict = {
        "recipe": recipe.source_id, "country": recipe.country,
        "renderer": recipe.renderer.value, "listing": {}, "pages": [],
    }
    fetcher = Fetcher(renderer=recipe.renderer.value, respect_robots=False, pause_every=0,
                      verify_ssl=recipe.verify_ssl, user_agent=recipe.user_agent)
    wayback_client = None
    try:
        if recipe.pagination.type == PaginationType.wayback:
            wayback_client = wayback.create_client()
            entries = wayback.list_snapshots_for_queries(
                recipe.start_urls,
                from_date=recipe.pagination.wayback_from,
                to_date=recipe.pagination.wayback_to,
                limit=recipe.pagination.wayback_limit,
                match_type=recipe.pagination.wayback_match_type,
                collapse=recipe.pagination.wayback_collapse,
                filters=recipe.pagination.wayback_filter,
            )
            entries = wayback.filter_entries_for_recipe(
                entries,
                recipe.listing.link_pattern,
                start_urls=recipe.start_urls,
            )
            sample = _sample_evenly(entries, n)
            report["listing"] = {
                "mode": "wayback snapshots",
                "snapshots_found": len(entries),
                "sampled": len(sample),
                "sample": [entry["original"] for entry in sample if entry.get("original")],
            }
        elif recipe.pagination.type in (PaginationType.api, PaginationType.feed):
            # api/feed harvest their own entries (carrying metadata); probe samples the
            # URLs and runs the usual per-page selector diagnostics on the speech pages.
            module = api if recipe.pagination.type == PaginationType.api else feed
            items = module.harvest_entries(recipe)
            links = [it["url"] for it in items]
            sample = _sample_evenly(links, n) if spread else links[:n]
            report["listing"] = {
                "mode": f"{recipe.pagination.type.value} entries",
                "links_found": len(links),
                "sampled": len(sample),
                "sample": links[:3],
            }
        elif spread:
            # Sample across the WHOLE history (oldest..newest) to catch structural
            # drift — a recipe can pass for recent pages but break on old ones. This
            # harvests every link first (slow for big sites; instant for sitemaps).
            harvest_stats: dict = {}
            links = harvest_links(recipe, fetcher, stats=harvest_stats)
            sample = _sample_evenly(links, n)
            report["listing"] = {"mode": "spread (full history)",
                                  "links_found": len(links), "sampled": len(sample),
                                  # a truncated harvest otherwise looks like a short archive
                                  "stopped_early": bool(harvest_stats.get("stopped_early")),
                                  "stop_reason": harvest_stats.get("stop_reason")}
        else:
            first = recipe.start_urls[0]
            links = extract_links(fetcher.get(first), first, recipe.listing)
            sample = links[:n]
            report["listing"] = {"url": first, "links_found": len(links), "sample": links[:3]}

        report["pages"] = _diagnose_pages(
            sample, recipe, fetcher=fetcher, wayback_client=wayback_client,
            is_wayback=recipe.pagination.type == PaginationType.wayback,
        )
        if recipe.keep_if is not None:
            report["keep_if"] = _keep_if_summary(recipe, report["pages"])

        # --- wayback_extend: sample the archived continuation the run would perform ------
        # Until now this ran ONLY inside a full `run` (it needs the live floor date), so a
        # recipe's archived-layout selectors could not be checked before paying for the
        # whole crawl — and archived pages are exactly where selectors drift. Probed here
        # with the same prefix/link_pattern/overrides the run derives (issue #54).
        ext = recipe.wayback_extend
        if (ext is None or not ext.enabled) and extend_wayback:
            ext = WaybackExtend()                 # flag-only: reuse the live recipe wholesale
        if ext is not None and ext.enabled and recipe.pagination.type != PaginationType.wayback:
            to_date, to_source = _extend_to_date(recipe, ext, out_root, wayback_to)
            if wayback_client is None:
                wayback_client = wayback.create_client()
            ext_entries = wayback.harvest_extend_entries(recipe, ext, to_date)
            ext_sample = _sample_evenly(ext_entries, n)
            ext_recipe = wayback.extend_recipe(recipe, ext)
            report["wayback_extend"] = {
                "prefix": wayback.extend_prefix(recipe, ext),
                "link_pattern": wayback.extend_link_pattern(recipe, ext),
                "to_date": to_date,
                "to_date_source": to_source,
                "overrides": [f for f in wayback.EXTEND_OVERRIDE_FIELDS
                              if getattr(ext, f) is not None],
                "snapshots_found": len(ext_entries),
                "sampled": len(ext_sample),
                "sample": [e["original"] for e in ext_sample[:3] if e.get("original")],
            }
            report["extend_pages"] = _diagnose_pages(
                ext_sample, ext_recipe, wayback_client=wayback_client, is_wayback=True,
            )
    finally:
        if wayback_client is not None:
            wayback_client.close()
        fetcher.close()
    return report


def _print(report: dict):
    ok = "✓"
    no = "✗"
    print(f"\nRECIPE  {report['recipe']}  ({report['country']}, renderer={report['renderer']})")
    L = report["listing"]
    count_label, count = _listing_count(L)
    flag = ok if count else no
    where = L["mode"] if "mode" in L else f"from {L.get('url')}"
    extra = f" (sampled {L['sampled']} across history)" if "sampled" in L else ""
    print(f"LISTING {flag} {count} {count_label} {where}{extra}")
    if not count:
        print(f"        -> 0 {count_label}: check listing.link_selector / link_pattern and pagination.")
    if L.get("stopped_early"):
        print(f"        {no} PAGINATION STOPPED EARLY ({L.get('stop_reason')}) — this count is "
              f"NOT the size of the archive, it is where the pager broke. See the warning "
              f"logged above; fix pagination before trusting any coverage number.")
    for s in L.get("sample", []):
        print(f"          - {s}")

    k = report.get("keep_if")
    if k:
        flag = ok if k["kept"] else no
        print(f"KEEP_IF {flag} kept {k['kept']} of {k['sampled']} sampled page(s), "
              f"filtered out {k['filtered_out']}"
              f"{'  (negated)' if k['negate'] else ''}")
        print(f"        selectors={k['selectors'] or '(whole page text)'}  "
              f"pattern={k['pattern']!r}")
        if not k["kept"] and k["sampled"]:
            print("        -> kept NOTHING: a real run would write 0 rows. Check that the "
                  "selectors exist on these pages and that the pattern matches their text "
                  "(a selector that matches nothing counts as 'no evidence' => drop).")
        elif not k["filtered_out"] and k["sampled"]:
            print("        -> filtered out nothing in this sample: either the harvest is "
                  "already clean (link_pattern did the work — then keep_if is redundant) or "
                  "the pattern is too loose. Sample more with --n / --spread.")

    _print_pages(report["pages"], label="PAGE")

    ext = report.get("wayback_extend")
    if ext:
        print(f"\nWAYBACK-EXTEND  {'✓' if ext['snapshots_found'] else '✗'} "
              f"{ext['snapshots_found']} archived capture(s) under {ext['prefix']}")
        print(f"        to={ext['to_date']}  ({ext['to_date_source']})")
        print(f"        link_pattern={ext['link_pattern']}")
        print(f"        selector overrides: {ext['overrides'] or 'none (reuses the live recipe)'}")
        if not ext["to_date"]:
            print("        ! UNBOUNDED: with no live floor to stop at, this sampled the WHOLE "
                  "archive — including recent captures whose layout still matches the live "
                  "site. Pass --wayback-to YYYYMMDD to check the historical slice a real run "
                  "would reach.")
        if not ext["snapshots_found"]:
            print("        -> 0 captures: check wayback_extend.prefix / link_pattern. A real "
                  "run would add nothing.")
        for s in ext.get("sample", []):
            print(f"          - {s}")
        _print_pages(report.get("extend_pages", []), label="ARCHIVED")


def _print_pages(pages: list, label: str):
    ok, no = "✓", "✗"
    for page in pages:
        date = page.get("parsed_date")
        print(f"\n{label}    [{date}]  {page['url']}")
        if "error" in page:
            print(f"        {no} fetch error: {page['error']}")
            continue
        if page.get("keep") is False:
            print(f"        {no} FILTERED OUT by keep_if — this page would NOT become a row")
        for name in FIELDS:
            f = page["fields"][name]
            mark = ok if f["matched_selector"] else no
            if name == "text":
                detail = f"{page['recipe_text_len']} chars"
            else:
                detail = f["value_preview"] or ""
            sel = f["matched_selector"] or f"NO MATCH (tried: {f['tried']})"
            print(f"        {mark} {name:8} <- {sel}")
            if detail:
                print(f"              {detail}")
            if f.get("note"):
                print(f"              ! {f['note']}")
        print(f"        parsed_date: {page['parsed_date']}")
        if page["recipe_text_len"] == 0 and page["generic_text_len"] > 0:
            print(f"        ! recipe got 0 chars but generic fallback would recover "
                  f"{page['generic_text_len']} — fix the `text` selector.")


def main():
    ap = argparse.ArgumentParser(description="Diagnose a recipe against the live site")
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--n", type=int, default=2, help="how many speech pages to inspect")
    ap.add_argument("--spread", action="store_true",
                    help="sample the --n pages evenly across the FULL history (catches "
                         "structural drift on older pages); harvests all links first")
    ap.add_argument("--extend-wayback", action="store_true",
                    help="also sample the archived continuation (as `run --extend-wayback` "
                         "would), to check the recipe's selectors against the OLDER archived "
                         "layout before paying for a full run. Automatic when the recipe "
                         "already declares `wayback_extend`.")
    ap.add_argument("--wayback-to", default=None, metavar="YYYYMMDD",
                    help="bound the wayback_extend sample at this date instead of the live "
                         "floor — use it to probe the historical slice before anything is "
                         "scraped (there is no floor yet)")
    ap.add_argument("--out-root", default="data/scraped",
                    help="where scraped CSVs live; read only to find the live date floor "
                         "that bounds a wayback_extend probe")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = probe(args.recipe, n=args.n, spread=args.spread,
                   extend_wayback=args.extend_wayback, wayback_to=args.wayback_to,
                   out_root=args.out_root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print(report)


if __name__ == "__main__":
    main()
