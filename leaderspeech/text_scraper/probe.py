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
from .paginate import extract_links
from .recipe import FieldSpec, load_recipe

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


def probe(recipe_path: str, n: int = 2) -> dict:
    recipe = load_recipe(recipe_path)
    report: dict = {
        "recipe": recipe.source_id, "country": recipe.country,
        "renderer": recipe.renderer.value, "listing": {}, "pages": [],
    }
    fetcher = Fetcher(renderer=recipe.renderer.value, respect_robots=False, pause_every=0)
    try:
        first = recipe.start_urls[0]
        html = fetcher.get(first)
        links = extract_links(html, first, recipe.listing)
        report["listing"] = {"url": first, "links_found": len(links), "sample": links[:3]}

        for url in links[:n]:
            try:
                phtml = fetcher.get(url)
            except Exception as e:
                report["pages"].append({"url": url, "error": f"{type(e).__name__}: {e}"})
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
    print(f"LISTING {flag} {L.get('links_found', 0)} link(s) from {L.get('url')}")
    if not L.get("links_found"):
        print("        -> 0 links: check listing.link_selector / link_pattern and pagination.")
    for s in L.get("sample", []):
        print(f"          - {s}")

    for page in report["pages"]:
        print(f"\nPAGE    {page['url']}")
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
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = probe(args.recipe, n=args.n)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print(report)


if __name__ == "__main__":
    main()
