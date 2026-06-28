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

from .extract import clean_text, extract_record
from .fallback_generic import extract_generic
from .fetch import Fetcher
from .paginate import extract_links, harvest_links
from .recipe import FieldSpec, PaginationType, load_recipe
from . import wayback

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


def probe(recipe_path: str, n: int = 2, spread: bool = False) -> dict:
    recipe = load_recipe(recipe_path)
    report: dict = {
        "recipe": recipe.source_id, "country": recipe.country,
        "renderer": recipe.renderer.value, "listing": {}, "pages": [],
    }
    fetcher = Fetcher(renderer=recipe.renderer.value, respect_robots=False, pause_every=0,
                      verify_ssl=recipe.verify_ssl)
    try:
        if recipe.pagination.type == PaginationType.wayback:
            entries = wayback.list_snapshots_for_queries(
                recipe.start_urls,
                from_date=recipe.pagination.wayback_from,
                to_date=recipe.pagination.wayback_to,
                limit=recipe.pagination.wayback_limit,
                match_type=recipe.pagination.wayback_match_type,
                collapse=recipe.pagination.wayback_collapse,
            )
            if n < len(entries):
                step = max(len(entries) // n, 1)
                sample = [entries[min(int(i * step), len(entries) - 1)] for i in range(n)]
            else:
                sample = entries
            report["listing"] = {
                "mode": "wayback snapshots",
                "snapshots_found": len(entries),
                "sampled": len(sample),
                "sample": [entry["original"] for entry in sample if entry.get("original")],
            }
        elif spread:
            # Sample across the WHOLE history (oldest..newest) to catch structural
            # drift — a recipe can pass for recent pages but break on old ones. This
            # harvests every link first (slow for big sites; instant for sitemaps).
            links = harvest_links(recipe, fetcher)
            if n < len(links):
                step = max(len(links) // n, 1)
                sample = [links[min(int(i * step), len(links) - 1)] for i in range(n)]
            else:
                sample = links
            report["listing"] = {"mode": "spread (full history)",
                                  "links_found": len(links), "sampled": len(sample)}
        else:
            first = recipe.start_urls[0]
            links = extract_links(fetcher.get(first), first, recipe.listing)
            sample = links[:n]
            report["listing"] = {"url": first, "links_found": len(links), "sample": links[:3]}

        for item in sample:
            try:
                if recipe.pagination.type == PaginationType.wayback:
                    entry = item
                    url = entry["original"]
                    phtml = wayback.fetch_snapshot(entry, delay=0.0)
                else:
                    url = item
                    phtml = fetcher.get(url)
            except Exception as e:
                bad_url = item.get("original") if isinstance(item, dict) else item
                report["pages"].append({"url": bad_url, "error": f"{type(e).__name__}: {e}"})
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
        fetcher.close()
    return report


def _print(report: dict):
    ok = "✓"
    no = "✗"
    print(f"\nRECIPE  {report['recipe']}  ({report['country']}, renderer={report['renderer']})")
    L = report["listing"]
    flag = ok if L.get("links_found") else no
    where = L["mode"] if "mode" in L else f"from {L.get('url')}"
    extra = f" (sampled {L['sampled']} across history)" if "sampled" in L else ""
    print(f"LISTING {flag} {L.get('links_found', 0)} link(s) {where}{extra}")
    if not L.get("links_found"):
        print("        -> 0 links: check listing.link_selector / link_pattern and pagination.")
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
