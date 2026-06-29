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
import logging
import sys
from datetime import datetime
from pathlib import Path

import pycountry

from .extract import extract_record
from .fallback_generic import extract_generic
from .fetch import Fetcher
from .paginate import harvest_links
from .recipe import PaginationType, Recipe, load_recipe
from . import api, feed, index, wayback

# fixed name (not __name__): under `python -m`, __name__ is "__main__", which would
# sit outside the "leaderspeech" logger tree where _add_log_file attaches handlers.
log = logging.getLogger("leaderspeech.text_scraper.run")

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
ERROR_COLUMNS = ["timestamp", "url", "error"]


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
        state = json.loads(path.read_text(encoding="utf-8"))
    else:
        state = {"last_doc_num": 0, "seen_urls": []}
    # seen_urls = successfully scraped; failed_urls = errored/empty (retried on demand)
    state.setdefault("failed_urls", [])
    return state


def _add_log_file(out_dir: Path, source_id: str):
    """Attach a per-run timestamped log file to the package logger (plus a console
    handler if none yet). Returns (path, handler) so the caller can detach it."""
    pkg = logging.getLogger("leaderspeech")
    pkg.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    if not any(type(h) is logging.StreamHandler for h in pkg.handlers):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        pkg.addHandler(sh)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{source_id}_{ts}.log"
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    pkg.addHandler(fh)
    return path, fh


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


def _record_from_entry(entry: dict, url: str, recipe: Recipe) -> dict:
    """Build a speech record straight from a harvested api/feed entry, for when the
    JSON/feed already carries the full text (so no page fetch is needed). Same shape
    as extract.extract_record."""
    speaker = entry.get("speaker", "") or (recipe.speaker_default or "")
    return {
        "title": entry.get("title", ""),
        "text": entry.get("text", ""),
        "date": entry.get("date"),
        "date_raw": "",
        "speaker": speaker,
        "context": "",
        "source": url,
    }


def _harvest_wayback_entries(recipe: Recipe) -> list[dict]:
    entries = wayback.list_snapshots_for_queries(
        recipe.start_urls,
        from_date=recipe.pagination.wayback_from,
        to_date=recipe.pagination.wayback_to,
        limit=recipe.pagination.wayback_limit,
        match_type=recipe.pagination.wayback_match_type,
        collapse=recipe.pagination.wayback_collapse,
    )
    return wayback.filter_entries_for_recipe(
        entries,
        recipe.listing.link_pattern,
        start_urls=recipe.start_urls,
    )


def scrape_recipe(
    recipe_path: str,
    out_root: str = "data/scraped",
    state_root: str = "data/state",
    max_pages: int | None = None,
    max_links: int | None = None,
    limit: int | None = None,
    respect_robots: bool = False,
    retry_failed: bool = False,
    max_consecutive_failures: int = 25,
    save_every: int = 25,
) -> dict:
    recipe = load_recipe(recipe_path)
    alpha3 = alpha3_for(recipe.country)
    out_dir = Path(out_root) / recipe.country
    out_path = out_dir / f"{recipe.source_id}.csv"
    err_path = out_dir / f"{recipe.source_id}_errors.csv"
    state_path = Path(state_root) / f"{recipe.country}.json"

    log_path, log_handler = _add_log_file(out_dir, recipe.source_id)
    log.info("START %s (%s) | max_pages=%s max_links=%s limit=%s retry_failed=%s respect_robots=%s",
             recipe.source_id, recipe.country, max_pages, max_links, limit, retry_failed, respect_robots)

    state = load_state(state_path)
    seen = set(state["seen_urls"])       # already scraped — never re-fetched
    failed = set(state["failed_urls"])   # errored/empty — re-fetched only with retry_failed

    fetcher = Fetcher(
        renderer=recipe.renderer.value,
        delay_range=tuple(recipe.politeness.delay_range),
        pause_every=recipe.politeness.pause_every,
        pause_seconds=recipe.politeness.pause_seconds,
        retries=recipe.politeness.retries,
        backoff=recipe.politeness.backoff,
        respect_robots=respect_robots,
        verify_ssl=recipe.verify_ssl,
        user_agent=recipe.user_agent,
    )
    wayback_client = None

    def stamp() -> str:
        return datetime.now().isoformat(timespec="seconds")

    n_scraped = n_generic = n_failed = 0
    consecutive_fail = 0
    aborted_early = False
    links: list[str] = []
    meta_by_url: dict[str, dict] = {}   # api/feed: per-URL metadata carried from the source
    pending_rows: list[dict] = []
    errors: list[dict] = []
    try:
        ptype = recipe.pagination.type
        wayback_mode = ptype == PaginationType.wayback
        if wayback_mode:
            wayback_client = wayback.create_client()
            entries = _harvest_wayback_entries(recipe)
            links = [entry["original"] for entry in entries if entry.get("original")]
        elif ptype in (PaginationType.api, PaginationType.feed):
            entries = []
            module = api if ptype == PaginationType.api else feed
            items = module.harvest_entries(recipe, max_links=max_links)
            links = [it["url"] for it in items]
            meta_by_url = {it["url"]: it for it in items}
        else:
            entries = []
            links = harvest_links(recipe, fetcher, max_pages=max_pages, max_links=max_links)

        # Persist the harvested list immediately (before any scraping) — a record of
        # what was found, and insurance against a crash mid-scrape.
        if links:
            links_path = out_dir / f"{recipe.source_id}_links.txt"
            links_path.parent.mkdir(parents=True, exist_ok=True)
            links_path.write_text("\n".join(links) + "\n", encoding="utf-8")
            log.info("saved %d harvested links to %s", len(links), links_path.name)

        skip = seen if retry_failed else (seen | failed)
        if wayback_mode:
            todo_entries = [entry for entry in entries if entry.get("original") not in skip]
            if limit:
                todo_entries = todo_entries[:limit]
            log.info("harvested %d archived capture(s); %d to scrape (%d done, %d known-failed%s)",
                     len(entries), len(todo_entries), len(seen), len(failed),
                     "; retrying failures" if retry_failed else "")
            todo = todo_entries
        else:
            todo = [url for url in links if url not in skip]
            if limit:
                todo = todo[:limit]
            log.info("harvested %d link(s); %d to scrape (%d done, %d known-failed%s)",
                     len(links), len(todo), len(seen), len(failed),
                     "; retrying failures" if retry_failed else "")

        for i, todo_item in enumerate(todo, 1):
            try:
                via_generic = False
                entry: dict = {}
                html = None
                if wayback_mode:
                    url = todo_item["original"]
                    html = wayback.fetch_snapshot(
                        todo_item,
                        delay=recipe.pagination.wayback_delay,
                        client=wayback_client,
                    )
                else:
                    url = todo_item
                    entry = meta_by_url.get(url, {})
                    # When the JSON/feed already carries the full text, use it directly
                    # and skip the page fetch; otherwise fetch the speech page.
                    if not entry.get("text"):
                        html = fetcher.get(url)

                if html is not None:
                    rec = extract_record(html, url, recipe)
                    # Recipes are tuned to a site's CURRENT layout; older/archived pages
                    # often used a different structure and yield nothing. Before giving up,
                    # fall back to structure-agnostic generic extraction.
                    if not rec["text"]:
                        gen = extract_generic(html, url)
                        if gen["text"]:
                            rec["text"] = gen["text"]
                            rec["title"] = rec["title"] or gen["title"]
                            rec["date"] = rec["date"] or gen["date"]
                            rec["speaker"] = rec["speaker"] or gen["speaker"]
                            via_generic = True
                else:
                    rec = _record_from_entry(entry, url, recipe)

                # Fill any field the page extraction left empty from the carried api/feed
                # metadata (e.g. SharePoint's reliable Write date when a page selector missed).
                if entry:
                    rec["text"] = rec["text"] or entry.get("text", "")
                    rec["title"] = rec["title"] or entry.get("title", "")
                    rec["date"] = rec["date"] or entry.get("date")
                    rec["speaker"] = rec["speaker"] or entry.get("speaker", "")

                if not rec["text"]:
                    errors.append({"timestamp": stamp(), "url": url,
                                   "error": "empty_text (no recipe match; generic also empty)"})
                    failed.add(url)         # NOT seen -> retried after a recipe fix
                    n_failed += 1
                    consecutive_fail += 1
                    log.warning("empty: %s", url)
                else:
                    state["last_doc_num"] += 1
                    doc_id = f"{alpha3}{state['last_doc_num']:04d}"
                    pending_rows.append(map_to_schema(rec, recipe, doc_id))
                    seen.add(url)
                    failed.discard(url)      # in case this was a previously-failed retry
                    n_scraped += 1
                    consecutive_fail = 0
                    if via_generic:
                        n_generic += 1
                        log.info("recovered via generic extractor: %s", url)
            except Exception as e:
                detail = f"{type(e).__name__}: {e}"
                errors.append({"timestamp": stamp(), "url": url, "error": detail[:300]})
                failed.add(url)
                n_failed += 1
                consecutive_fail += 1
                log.warning("error: %s :: %s", url, detail[:160])

            # circuit breaker: a long unbroken run of failures means we're blocked or the
            # recipe/site broke — stop with a clear signal instead of hammering on.
            if consecutive_fail >= max_consecutive_failures:
                aborted_early = True
                log.error("ABORTING after %d consecutive failures — likely blocked, or the "
                          "recipe/site changed. See the errors file. Fix, then --retry-failed.",
                          consecutive_fail)
                break

            if i % save_every == 0:  # checkpoint: flush rows, errors, and state
                _append(out_path, pending_rows, SCHEMA_COLUMNS)
                _append(err_path, errors, ERROR_COLUMNS)
                pending_rows, errors = [], []
                state["seen_urls"], state["failed_urls"] = sorted(seen), sorted(failed)
                save_state(state_path, state)
                log.info("progress %d/%d | scraped=%d generic=%d failed=%d",
                         i, len(todo), n_scraped, n_generic, n_failed)
    except Exception:
        log.exception("FATAL during harvest/scrape — partial results flushed below")
        raise
    finally:
        if wayback_client is not None:
            wayback_client.close()
        fetcher.close()
        _append(out_path, pending_rows, SCHEMA_COLUMNS)
        _append(err_path, errors, ERROR_COLUMNS)
        state["seen_urls"], state["failed_urls"] = sorted(seen), sorted(failed)
        save_state(state_path, state)
        attempted = n_scraped + n_failed
        if attempted and n_failed / attempted > 0.5:
            log.warning("HIGH FAILURE RATE: %d/%d failed — check the recipe selectors / pagination "
                        "(or the site may be blocking).", n_failed, attempted)
        log.info("DONE %s | scraped=%d generic=%d failed=%d%s | last_doc_num=%d | out=%s",
                 recipe.source_id, n_scraped, n_generic, n_failed,
                 " | ABORTED EARLY" if aborted_early else "", state["last_doc_num"], out_path)
        # Refresh the running scrape index (one row per source CSV; for merging). Never
        # let an index hiccup (e.g. the xlsx open in Excel) break the scrape itself.
        try:
            index.build_index(out_root, recipes_dir=str(Path(recipe_path).parent))
        except Exception as e:
            log.warning("could not update scrape index: %s", e)
        logging.getLogger("leaderspeech").removeHandler(log_handler)
        log_handler.close()

    return {
        "source_id": recipe.source_id,
        "country": recipe.country,
        "links_found": len(links),
        "scraped_this_run": n_scraped,
        "via_generic_fallback": n_generic,   # high => recipe selectors are drifting
        "failed_this_run": n_failed,
        "failed_pending_retry": len(failed),  # re-run with --retry-failed after a fix
        "aborted_early": aborted_early,       # circuit breaker tripped (likely blocked/broken)
        "last_doc_num": state["last_doc_num"],
        "output": str(out_path),
        "log": str(log_path),
        "errors_file": str(err_path),
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
    ap.add_argument("--retry-failed", action="store_true",
                    help="re-attempt URLs that previously errored/were empty (use after fixing a recipe)")
    args = ap.parse_args()

    result = scrape_recipe(
        args.recipe, args.out_root, args.state_root,
        args.max_pages, args.max_links, args.limit,
        respect_robots=args.respect_robots,
        retry_failed=args.retry_failed,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
