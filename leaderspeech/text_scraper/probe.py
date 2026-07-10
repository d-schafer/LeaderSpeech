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

from bs4 import BeautifulSoup

from .extract import clean_text, extract_pdf_record, extract_record
from .fallback_generic import extract_generic
from .fetch import Fetcher
from .paginate import extract_links, harvest_links
from .pdf import is_pdf_url, looks_like_pdf
from .recipe import ContentType, FieldSpec, PaginationType, load_recipe
from . import api, feed, wayback

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


def _sample_evenly(entries: list, n: int) -> list:
    """Pick `n` roughly even samples; return all entries when `n` is large enough."""
    if n < len(entries):
        step = max(len(entries) // n, 1)
        return [entries[min(i * step, len(entries) - 1)] for i in range(n)]
    return list(entries)


def _pdf_page_report(recipe, url: str, rec: dict) -> dict:
    """Per-page diagnostics for a PDF sample. PDFs have no DOM, so 'matched' means the
    field's url_regex hit (or, for text, the PDF body extracted); the shape mirrors the
    HTML page report so `_print` renders it the same way."""
    fields = {}
    for name in FIELDS:
        spec = getattr(recipe, name)
        if name == "text":
            matched = "(pdf body)" if rec["text"] else None
            tried = ["(PDF body extraction)"]
        else:
            url_regex = getattr(spec, "url_regex", None) if spec else None
            matched = f"url_regex: {url_regex}" if (url_regex and rec.get(name)) else None
            tried = [f"url_regex: {url_regex}"] if url_regex else (["speaker_default"]
                     if name == "speaker" and recipe.speaker_default else [])
        fields[name] = {
            "matched_selector": matched,
            "n_elements": 0,
            "tried": tried,
            "value_preview": clean_text(rec[name])[:100] if name != "text" else "",
            "text_len": len(rec["text"]) if name == "text" else None,
        }
    return {
        "url": url,
        "parsed_date": rec["date"],
        "recipe_text_len": len(rec["text"]),
        "generic_text_len": 0,
        "fields": fields,
    }


def _listing_count(report_listing: dict) -> tuple[str, int]:
    if "snapshots_found" in report_listing:
        return "snapshot(s)", report_listing.get("snapshots_found", 0)
    return "link(s)", report_listing.get("links_found", 0)


def probe(recipe_path: str, n: int = 2, spread: bool = False) -> dict:
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
            links = harvest_links(recipe, fetcher)
            sample = _sample_evenly(links, n)
            report["listing"] = {"mode": "spread (full history)",
                                  "links_found": len(links), "sampled": len(sample)}
        else:
            first = recipe.start_urls[0]
            links = extract_links(fetcher.get(first), first, recipe.listing)
            sample = links[:n]
            report["listing"] = {"url": first, "links_found": len(links), "sample": links[:3]}

        for item in sample:
            pdf_data = None
            try:
                is_wayback = recipe.pagination.type == PaginationType.wayback
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
                report["pages"].append({"url": bad_url, "error": f"{type(e).__name__}: {e}"})
                continue
            if pdf_data is not None:
                report["pages"].append(_pdf_page_report(recipe, url, extract_pdf_record(pdf_data, url, recipe)))
                continue
            soup = BeautifulSoup(phtml, "lxml")
            rec = extract_record(phtml, url, recipe)              # what the recipe yields
            gen = extract_generic(phtml, url)                     # what generic would yield
            fields = {}
            for name in FIELDS:
                sel, ncount = _which_selector(soup, getattr(recipe, name))
                fields[name] = {
                    "matched_selector": sel,
                    "n_elements": ncount,
                    "tried": list(getattr(recipe, name).selectors) if getattr(recipe, name) else [],
                    "value_preview": clean_text(rec[name])[:100] if name != "text" else "",
                    "text_len": len(rec["text"]) if name == "text" else None,
                }
            report["pages"].append({
                "url": url,
                "parsed_date": rec["date"],
                "recipe_text_len": len(rec["text"]),
                "generic_text_len": len(gen["text"]),
                "fields": fields,
            })
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
    for s in L.get("sample", []):
        print(f"          - {s}")

    for page in report["pages"]:
        date = page.get("parsed_date")
        print(f"\nPAGE    [{date}]  {page['url']}")
        if "error" in page:
            print(f"        {no} fetch error: {page['error']}")
            continue
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
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = probe(args.recipe, n=args.n, spread=args.spread)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print(report)


if __name__ == "__main__":
    main()
