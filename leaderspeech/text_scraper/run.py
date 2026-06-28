"""Orchestrator + CLI.

For one recipe: harvest the speech links, fetch and extract each, map the result
into the standardized LeaderSpeech schema, and append to a per-country CSV. The
run is resumable: a per-country state file remembers which URLs have been seen
and the last doc_id number used, so re-running continues where it left off and
keeps doc_ids unique and contiguous across runs and across sources in a country.

Usage:
    python -m leaderspeech.text_scraper.run --recipe recipes/arg_casarosada.yml \
        --max-pages 2 --limit 10
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import pycountry

from .extract import extract_record
from .fallback_generic import extract_generic
from .fetch import Fetcher
from .paginate import harvest_links
from .recipe import Recipe, load_recipe

# survive non-ASCII speaker/title names on the Windows console
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# The standardized schema (see _examples_code/02-combine_and_standardize_data.R).
# Unsuffixed title/text/context hold ENGLISH; *_originlanguage hold the original.
SCHEMA_COLUMNS = [
    "doc_id", "country", "ISO3N", "speaker", "position",
    "context", "context_originlanguage",
    "title", "title_originlanguage",
    "text", "text_originlanguage",
    "date", "source", "source_language", "dataset",
]
ERROR_COLUMNS = ["source", "error"]


def alpha3_for(country: str) -> str:
    try:
        return pycountry.countries.lookup(country).alpha_3
    except Exception:
        return "XXX"


def is_english(language: str) -> bool:
    lang = (language or "").strip().lower()
    return lang.startswith("english") or lang == "en"


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"last_doc_num": 0, "seen_urls": []}


def save_state(path: Path, state: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def map_to_schema(rec: dict, recipe: Recipe, doc_id: str) -> dict:
    row = {col: "" for col in SCHEMA_COLUMNS}
    row.update(
        doc_id=doc_id,
        country=recipe.country,
        ISO3N=recipe.iso3n or "",
        speaker=rec["speaker"],
        position=recipe.position or "",
        date=rec["date"] or "",
        source=rec["source"],
        source_language=recipe.source_language,
        dataset=recipe.dataset,
    )
    if is_english(recipe.source_language):
        row["title"], row["text"], row["context"] = rec["title"], rec["text"], rec["context"]
    else:
        row["title_originlanguage"] = rec["title"]
        row["text_originlanguage"] = rec["text"]
        row["context_originlanguage"] = rec["context"]
    return row


def _append(path: Path, rows: list[dict], columns: list[str]):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)


def scrape_recipe(
    recipe_path: str,
    out_root: str = "data/scraped",
    state_root: str = "data/state",
    max_pages: int | None = None,
    max_links: int | None = None,
    limit: int | None = None,
    respect_robots: bool = False,
    save_every: int = 25,
) -> dict:
    recipe = load_recipe(recipe_path)
    alpha3 = alpha3_for(recipe.country)
    out_path = Path(out_root) / recipe.country / f"{recipe.source_id}.csv"
    err_path = Path(out_root) / recipe.country / f"{recipe.source_id}_errors.csv"
    state_path = Path(state_root) / f"{recipe.country}.json"

    state = load_state(state_path)
    seen = set(state["seen_urls"])

    fetcher = Fetcher(
        renderer=recipe.renderer.value,
        delay_range=tuple(recipe.politeness.delay_range),
        pause_every=recipe.politeness.pause_every,
        pause_seconds=recipe.politeness.pause_seconds,
        retries=recipe.politeness.retries,
        backoff=recipe.politeness.backoff,
        respect_robots=respect_robots,
    )

    n_scraped = n_generic = n_failed = 0
    pending_rows: list[dict] = []
    errors: list[dict] = []
    try:
        links = harvest_links(recipe, fetcher, max_pages=max_pages, max_links=max_links)
        todo = [url for url in links if url not in seen]
        if limit:
            todo = todo[:limit]

        for i, url in enumerate(todo, 1):
            try:
                html = fetcher.get(url)
                rec = extract_record(html, url, recipe)
                # Recipes are tuned to a site's CURRENT layout; older/archived pages
                # often used a different structure and yield nothing. Before giving up,
                # fall back to structure-agnostic generic extraction.
                via_generic = False
                if not rec["text"]:
                    gen = extract_generic(html, url)
                    if gen["text"]:
                        rec["text"] = gen["text"]
                        rec["title"] = rec["title"] or gen["title"]
                        rec["date"] = rec["date"] or gen["date"]
                        rec["speaker"] = rec["speaker"] or gen["speaker"]
                        via_generic = True
                if not rec["text"]:
                    errors.append({"source": url, "error": "empty_text"})
                    seen.add(url)
                    n_failed += 1
                    continue
                state["last_doc_num"] += 1
                doc_id = f"{alpha3}{state['last_doc_num']:04d}"
                pending_rows.append(map_to_schema(rec, recipe, doc_id))
                seen.add(url)
                n_scraped += 1
                if via_generic:
                    n_generic += 1
                    # log (not as an error) so generic-extracted rows are auditable
                    errors.append({"source": url, "error": "ok_recovered_via_generic"})
            except Exception as e:
                errors.append({"source": url, "error": str(e)[:300]})
                n_failed += 1

            if i % save_every == 0:  # intermediate checkpoint
                _append(out_path, pending_rows, SCHEMA_COLUMNS)
                _append(err_path, errors, ERROR_COLUMNS)
                pending_rows, errors = [], []
                state["seen_urls"] = sorted(seen)
                save_state(state_path, state)
    finally:
        fetcher.close()

    _append(out_path, pending_rows, SCHEMA_COLUMNS)
    _append(err_path, errors, ERROR_COLUMNS)
    state["seen_urls"] = sorted(seen)
    save_state(state_path, state)

    return {
        "source_id": recipe.source_id,
        "country": recipe.country,
        "links_found": len(links),
        "scraped_this_run": n_scraped,
        "via_generic_fallback": n_generic,  # watch this: high => recipe selectors drifting
        "empty_or_failed": n_failed,
        "last_doc_num": state["last_doc_num"],
        "output": str(out_path),
    }


def main():
    ap = argparse.ArgumentParser(description="LeaderSpeech text scraper")
    ap.add_argument("--recipe", required=True, help="path to a recipe YAML file")
    ap.add_argument("--out-root", default="data/scraped")
    ap.add_argument("--state-root", default="data/state")
    ap.add_argument("--max-pages", type=int, default=None, help="cap listing pages crawled")
    ap.add_argument("--max-links", type=int, default=None, help="cap speech links harvested")
    ap.add_argument("--limit", type=int, default=None, help="cap speeches scraped this run")
    ap.add_argument("--respect-robots", action="store_true",
                    help="honor robots.txt (off by default for this public-record project)")
    args = ap.parse_args()

    result = scrape_recipe(
        args.recipe, args.out_root, args.state_root,
        args.max_pages, args.max_links, args.limit,
        respect_robots=args.respect_robots,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
