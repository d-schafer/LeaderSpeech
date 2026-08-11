"""A running index of what's been scraped, for merging the per-source CSVs.

Output files are named after the *site* (e.g. `arg_casarosada.csv`), which makes a
folder of them hard to read and to merge. This builds `scraped_progress_log.xlsx`
in the scrape root: one row per source CSV, recording its country, website, file
path, coverage, and provenance — so a merge step can just read the index and
concatenate every `csv_file` it lists.

It is a **machine-generated, regenerable artifact** — unlike the researcher-curated
`data/sources/master_sources.xlsx`, this file is rebuilt from scratch each time (so
it never goes stale), and is safe for the engine to overwrite.

    python -m leaderspeech.text_scraper.index            # rebuild on demand
    python -m leaderspeech.text_scraper.index --out-root data/scraped --recipes-dir recipes

It is also rebuilt automatically at the end of every `run.scrape_recipe`.
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import pandas as pd

from . import links as linksmod
from .recipe import load_recipe

log = logging.getLogger(__name__)

INDEX_NAME = "scraped_progress_log.xlsx"
SHEET_SOURCES = "sources"
SHEET_PENDING = "harvested_not_scraped"

# Column order in the workbook.
COLUMNS = [
    "source_id", "country", "ISO3N", "iso3_prefix",
    "main_website", "start_url",
    "source_language", "dataset", "position",
    "pagination_type", "renderer",
    "n_speeches", "n_unique_links", "percent_scraped", "links_status",
    "date_min", "date_max", "n_bad_or_missing_date",
    "doc_id_first", "doc_id_last",
    "recipe_file", "csv_file", "last_updated", "links_last_harvested", "notes",
]

# Sources that have harvested links on disk but no CSV yet — a SECOND sheet, never rows on
# the first. `merge` reads sheet 0 and `.exists()`-checks every `csv_file`; a blank one would
# fire its "N file(s) listed in the index are missing — rebuild it" warning on every merge,
# which is the project's designated stale-index signal and must not cry wolf.
PENDING_COLUMNS = [
    "source_id", "country", "n_unique_links", "links_status",
    "links_last_harvested", "recipe_file",
]


def _first(series) -> str:
    for v in series:
        if pd.notna(v) and str(v).strip():
            return str(v).strip()
    return ""


def _coverage(df: pd.DataFrame) -> tuple[str, str, int]:
    """Plausible date span + a count of bad/missing dates (year outside 1900..now+1
    or unparseable), as a quality signal. A bad min like 0001-11-30 won't skew it."""
    if "date" not in df.columns or df.empty:
        return "", "", len(df)
    parsed = pd.to_datetime(df["date"], errors="coerce")
    max_year = datetime.now().year + 1
    plausible = parsed[(parsed.dt.year >= 1900) & (parsed.dt.year <= max_year)]
    bad = len(df) - len(plausible)
    if plausible.empty:
        return "", "", bad
    return (plausible.min().date().isoformat(),
            plausible.max().date().isoformat(), int(bad))


def date_floor(csv_path: Path) -> Optional[str]:
    """Earliest *plausible* date (YYYY-MM-DD) in a source CSV, or None if the file is
    unreadable/empty or has no parseable date. Reuses `_coverage`'s plausible-year
    filter, so a bogus min like `0001-11-30` can't drag the floor down. Used by the
    `wayback_extend` continuation to bound the archive harvest at the live floor."""
    try:
        df = pd.read_csv(csv_path, dtype=str)
    except Exception:
        return None
    date_min, _, _ = _coverage(df)
    return date_min or None


def _audio_marker(csv_path: Path) -> Optional[tuple[str, str]]:
    """If this source has an audio sidecar (`<id>_media.csv`, written by the
    video_audio_scraper), return (renderer, pagination_type) for the index — e.g.
    ("audio:faster-whisper", "playlist") — read from its first row. Else None.

    Audio sources need no recipe (yt-dlp does the per-site work), so the marker lives
    in the always-written sidecar rather than in a recipe YAML."""
    media_path = csv_path.with_name(csv_path.stem + "_media.csv")
    if not media_path.exists():
        return None
    try:
        m = pd.read_csv(media_path, dtype=str, nrows=1)
    except Exception:
        return ("audio", "")
    backend = _first(m.get("backend", pd.Series(dtype=str))) if not m.empty else ""
    kind = _first(m.get("kind", pd.Series(dtype=str))) if not m.empty else ""
    renderer = f"audio:{backend}" if backend else "audio"
    return (renderer, kind)


def docid_sort_key(doc_id: str) -> tuple[str, int]:
    """Sort `UKR0001`-style ids by their NUMBER, not as text.

    A plain string sort is wrong the moment a country passes 9,999, because the counter
    is `f"{alpha3}{n:04d}"` and `:04d` is a *minimum* width — so it widens to 5 digits
    rather than wrapping. Lexically that puts `UKR9999` after `UKR18996`, and the index
    then reports Ukraine's last doc_id as UKR9999 when it is really UKR18996. Only the
    reported range was ever wrong (the ids themselves stay unique), but it reads exactly
    like a counter that wrapped and silently collided — so it is worth not saying."""
    m = re.search(r"(\d+)$", doc_id)
    return (doc_id[: m.start()], int(m.group(1))) if m else (doc_id, -1)


def _link_columns(universe, n_scraped: int, audio: bool = False) -> tuple:
    """The four link columns for one row: (n_unique_links, percent_scraped, links_status,
    links_last_harvested).

    `n_unique_links` and `percent_scraped` are **None (blank), never 0**, when there is no
    link list at all — a source scraped before link lists were saved knows of no links, and
    printing `0` there says the opposite of the truth. A list that exists but is *empty*
    does report 0, so "we looked and found nothing" stays distinguishable.

    The percentage is deliberately uncapped: above 100 means the lists are stale or narrower
    than the recipe, and `links_status` says `stale_links`. Clamping would hide the one
    condition that proves the denominator is wrong.
    """
    if universe is None:
        return None, None, "", ""
    n_links = universe.n_unique if universe.found else None
    pct = round(100 * n_scraped / n_links, 1) if n_links else None
    status = universe.status(n_scraped=n_scraped, audio=audio)
    harvested = (datetime.fromtimestamp(universe.newest).date().isoformat()
                 if universe.newest else "")
    return n_links, pct, status, harvested


def _summarize(source_id, csv_path: Path, df: pd.DataFrame, recipe, yml: Optional[Path]) -> dict:
    date_min, date_max, n_bad = _coverage(df)
    doc_ids = sorted((str(x) for x in df.get("doc_id", pd.Series(dtype=str)).dropna()
                      if str(x).strip()), key=docid_sort_key)
    doc_first = doc_ids[0] if doc_ids else ""
    doc_last = doc_ids[-1] if doc_ids else ""
    iso3_prefix = re.sub(r"\d+$", "", doc_first) if doc_first else ""

    country = (recipe.country if recipe else "") or _first(df.get("country", pd.Series(dtype=str)))
    start_url = (recipe.start_urls[0] if recipe and recipe.start_urls else "")
    main_site = urlparse(start_url).netloc if start_url else ""
    if not main_site:  # fall back to the source URL recorded in the data
        main_site = urlparse(_first(df.get("source", pd.Series(dtype=str)))).netloc

    # audio-transcription sources carry their marker in the sidecar, not a recipe
    audio = _audio_marker(csv_path)
    pagination_type = audio[1] if audio else (recipe.pagination.type.value if recipe else "")
    renderer = audio[0] if audio else (recipe.renderer.value if recipe else "")

    # What we KNOW how to fetch, from the link lists this source has left on disk (see
    # `links.py`). A disk hiccup must never sink the index — a failed scan yields blanks.
    try:
        universe = linksmod.link_universe(csv_path.parent, source_id, recipe=recipe)
    except Exception as e:  # noqa: BLE001
        log.warning("index: link scan failed for %s :: %s", source_id, e)
        universe = None
    n_links, pct, links_status, harvested = _link_columns(universe, len(df), bool(audio))

    return {
        "source_id": source_id,
        "country": country,
        "ISO3N": (recipe.iso3n if recipe and recipe.iso3n else "") or _first(df.get("ISO3N", pd.Series(dtype=str))),
        "iso3_prefix": iso3_prefix,
        "main_website": main_site,
        "start_url": start_url,
        "source_language": (recipe.source_language if recipe else "") or _first(df.get("source_language", pd.Series(dtype=str))),
        "dataset": (recipe.dataset if recipe else "") or _first(df.get("dataset", pd.Series(dtype=str))),
        "position": (recipe.position if recipe else "") or _first(df.get("position", pd.Series(dtype=str))),
        "pagination_type": pagination_type,
        "renderer": renderer,
        "n_speeches": len(df),
        "n_unique_links": n_links,
        "percent_scraped": pct,
        "links_status": links_status,
        "date_min": date_min,
        "date_max": date_max,
        "n_bad_or_missing_date": n_bad,
        "doc_id_first": doc_first,
        "doc_id_last": doc_last,
        "recipe_file": yml.as_posix() if yml else "",
        "csv_file": csv_path.as_posix(),
        "last_updated": datetime.fromtimestamp(csv_path.stat().st_mtime).isoformat(timespec="seconds"),
        "links_last_harvested": harvested,
        "notes": (recipe.notes or "") if recipe else "",
    }


def build_index(out_root: str = "data/scraped", recipes_dir: str = "recipes",
                out_name: str = INDEX_NAME) -> Optional[Path]:
    """(Re)build the scrape index from every per-source CSV under `out_root`, matched
    to its recipe in `recipes_dir`. Returns the written path, or None if no CSVs."""
    out_root = Path(out_root)

    recipes = {}
    for yml in sorted(Path(recipes_dir).glob("*.yml")):
        try:
            recipes[load_recipe(yml).source_id] = yml
        except Exception as e:  # a malformed recipe shouldn't sink the index
            log.warning("index: skipping unreadable recipe %s :: %s", yml, e)

    rows = []
    for csv_path in sorted(out_root.glob("*/*.csv")):
        # skip the per-source sidecars, not sources themselves
        if csv_path.name.endswith("_errors.csv") or csv_path.name.endswith("_media.csv"):
            continue
        source_id = csv_path.stem
        try:
            df = pd.read_csv(csv_path, dtype=str)
        except Exception as e:
            log.warning("index: skipping unreadable csv %s :: %s", csv_path, e)
            continue
        yml = recipes.get(source_id)
        recipe = load_recipe(yml) if yml else None
        rows.append(_summarize(source_id, csv_path, df, recipe, yml))

    if not rows:
        log.info("index: no scraped CSVs under %s — nothing to write", out_root)
        return None

    df_out = pd.DataFrame(rows, columns=COLUMNS).sort_values(["country", "source_id"])
    # A column of ints holding any blank becomes float64 and can render as "1234.0". pandas'
    # nullable integer keeps both: real integer cells, and genuinely empty ones. This only
    # works because `_link_columns` emits None — astype("Int64") over an object column
    # containing "" raises.
    df_out["n_unique_links"] = df_out["n_unique_links"].astype("Int64")

    df_pending = _pending_sources(Path(out_root), recipes, set(df_out["source_id"]))

    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / out_name
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df_out.to_excel(writer, sheet_name=SHEET_SOURCES, index=False)
        if not df_pending.empty:
            df_pending.to_excel(writer, sheet_name=SHEET_PENDING, index=False)

    known = int(df_out["n_unique_links"].sum())
    scraped = int(df_out["n_speeches"].sum())
    log.info("index: wrote %d source(s) to %s | %s of %s known links scraped (%.1f%%)",
             len(rows), out_path, f"{scraped:,}", f"{known:,}",
             (100 * scraped / known) if known else 0.0)
    if not df_pending.empty:
        log.info("index: + %d source(s) harvested but never scraped (%s links) on the '%s' "
                 "sheet", len(df_pending),
                 f"{int(df_pending['n_unique_links'].sum()):,}", SHEET_PENDING)
    return out_path


def _pending_sources(out_root: Path, recipes: dict, already: set) -> pd.DataFrame:
    """Sources with harvested links on disk but no CSV — invisible to a `*/*.csv` glob.

    Worth surfacing (78k links on this tree) but NOT as rows on the main sheet: see
    :data:`PENDING_COLUMNS`. Failure here must not cost the index, so it degrades to empty.
    """
    try:
        discovered = linksmod.discover_sources(out_root)
    except Exception as e:  # noqa: BLE001
        log.warning("index: could not scan for unscraped harvests :: %s", e)
        return pd.DataFrame(columns=PENDING_COLUMNS)

    rows = []
    for source_id, country_dir in sorted(discovered.items()):
        if source_id in already:
            continue
        yml = recipes.get(source_id)          # `recipes` maps source_id -> recipe PATH
        try:
            recipe = load_recipe(yml) if yml else None
            universe = linksmod.link_universe(country_dir, source_id, recipe=recipe)
        except Exception as e:  # noqa: BLE001
            log.warning("index: link scan failed for %s :: %s", source_id, e)
            continue
        n_links, _, links_status, harvested = _link_columns(universe, 0)
        rows.append({
            "source_id": source_id,
            "country": country_dir.name,
            "n_unique_links": n_links,
            "links_status": links_status,
            "links_last_harvested": harvested,
            "recipe_file": yml.as_posix() if yml else "",
        })
    df = pd.DataFrame(rows, columns=PENDING_COLUMNS)
    if not df.empty:
        df["n_unique_links"] = df["n_unique_links"].astype("Int64")
    return df


def main():
    ap = argparse.ArgumentParser(description="Rebuild the scraped-data index workbook")
    ap.add_argument("--out-root", default="data/scraped")
    ap.add_argument("--recipes-dir", default="recipes")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    path = build_index(args.out_root, args.recipes_dir)
    print(f"wrote {path}" if path else "no CSVs found; nothing written")


if __name__ == "__main__":
    main()
