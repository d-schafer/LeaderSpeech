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

from .recipe import load_recipe

log = logging.getLogger(__name__)

INDEX_NAME = "scraped_progress_log.xlsx"

# Column order in the workbook.
COLUMNS = [
    "source_id", "country", "ISO3N", "iso3_prefix",
    "main_website", "start_url",
    "source_language", "dataset", "position",
    "pagination_type", "renderer",
    "n_speeches", "date_min", "date_max", "n_bad_or_missing_date",
    "doc_id_first", "doc_id_last",
    "recipe_file", "csv_file", "last_updated", "notes",
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


def _summarize(source_id, csv_path: Path, df: pd.DataFrame, recipe, yml: Optional[Path]) -> dict:
    date_min, date_max, n_bad = _coverage(df)
    doc_ids = sorted(str(x) for x in df.get("doc_id", pd.Series(dtype=str)).dropna() if str(x).strip())
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
        "date_min": date_min,
        "date_max": date_max,
        "n_bad_or_missing_date": n_bad,
        "doc_id_first": doc_first,
        "doc_id_last": doc_last,
        "recipe_file": yml.as_posix() if yml else "",
        "csv_file": csv_path.as_posix(),
        "last_updated": datetime.fromtimestamp(csv_path.stat().st_mtime).isoformat(timespec="seconds"),
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
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / out_name
    df_out.to_excel(out_path, index=False)
    log.info("index: wrote %d source(s) to %s", len(rows), out_path)
    return out_path


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
