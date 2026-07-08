"""Merge the per-source cleaned Parquets into ONE intermediate dataset, and keep a
human-readable index of what's been cleaned.

This produces `data/_build/LeaderSpeech_merged.parquet` (accepted rows only, deduped
by doc_id) — the INTERMEDIATE. The FINAL deliverable (with authoritative `fixNames`
name standardization, plus `.RData`/`.csv.gz`) is produced by `scripts/export_leaderspeech.R`,
which reads this file. Keeping the merge cheap and idempotent means it can be re-run
anytime without re-spending on the model.

    python -m leaderspeech.clean_structure_metadata.merge
"""

from __future__ import annotations

import argparse
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from . import gate, store

log = logging.getLogger("leaderspeech.clean_structure_metadata.merge")

# Curated metadata kept in the deliverable (alongside the 15 standardized scraper columns).
DELIVERABLE_META = [
    "document_type", "is_first_person",
    "speaker_type", "audience", "speech_type", "venue",
    "detected_language", "is_ceremonial", "tenure_match", "clean_confidence",
]
DELIVERABLE_COLUMNS = store.SCRAPED_COLUMNS + DELIVERABLE_META

INDEX_NAME = "cleaned_progress_log.xlsx"
DEFAULT_BUILD = "data/_build/LeaderSpeech_merged.parquet"


def _source_parquets(out_root: str) -> list[Path]:
    return sorted(p for p in Path(out_root).glob("*/*.parquet"))


def _write_atomic_parquet(df: pd.DataFrame, path: Path, compression: str = "zstd") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, engine="pyarrow", compression=compression, index=False)
    os.replace(tmp, path)


def build_dataset(
    out_root: str = "data/cleaned",
    build_path: str = DEFAULT_BUILD,
    compression: str = "zstd",
) -> Optional[Path]:
    """Concatenate accepted rows from every per-source Parquet, dedupe by doc_id, and
    write the intermediate merged Parquet. Returns the written path (or None if empty)."""
    frames = []
    for p in _source_parquets(out_root):
        try:
            df = pd.read_parquet(p)
        except Exception as e:
            log.warning("merge: skipping unreadable %s :: %s", p, e)
            continue
        if "clean_status" in df.columns:
            df = df[df["clean_status"] == gate.ACCEPTED]
        cols = [c for c in DELIVERABLE_COLUMNS if c in df.columns]
        frames.append(df[cols])

    if not frames:
        log.info("merge: no cleaned Parquets under %s — nothing to merge", out_root)
        return None

    merged = pd.concat(frames, ignore_index=True)
    before = len(merged)
    merged = merged.drop_duplicates(subset=["doc_id"], keep="first").reset_index(drop=True)
    out = Path(build_path)
    _write_atomic_parquet(merged, out, compression)
    log.info("merge: wrote %d speeches (%d dupes dropped) to %s", len(merged), before - len(merged), out)
    return out


def _nonempty(series: pd.Series) -> pd.Series:
    """Boolean mask of rows whose string value is non-empty (treats NaN/'' as empty)."""
    return series.fillna("").astype(str).str.strip() != ""


def build_clean_index(out_root: str = "data/cleaned", out_name: str = INDEX_NAME) -> Optional[Path]:
    """One row per cleaned source Parquet: counts, coverage, model, file path, plus DERIVED
    per-source stage flags (`is_translated`) computed straight from the data — so 'what's
    done' can never silently drift from a stale written flag."""
    rows = []
    for p in _source_parquets(out_root):
        try:
            df = pd.read_parquet(p)
        except Exception as e:
            log.warning("index: skipping unreadable %s :: %s", p, e)
            continue
        status = df.get("clean_status", pd.Series(dtype=str))
        dates = pd.to_datetime(df.get("date", pd.Series(dtype=str)), errors="coerce")
        plausible = dates[(dates.dt.year >= 1900) & (dates.dt.year <= datetime.now().year + 1)]
        doc_ids = sorted(str(x) for x in df.get("doc_id", pd.Series(dtype=str)).dropna())
        # translation stage (derived): a row "needs translation" iff it carries origin-language
        # text; it is "translated" once the English `text` column is filled.
        needs_tr = _nonempty(df.get("text_originlanguage", pd.Series(dtype=str)))
        translated = needs_tr & _nonempty(df.get("text", pd.Series(dtype=str)))
        n_nonenglish = int(needs_tr.sum())
        n_translated = int(translated.sum())
        rows.append({
            "source_id": p.stem,
            "country": p.parent.name,
            "n_total": len(df),
            "n_accepted": int((status == gate.ACCEPTED).sum()),
            "n_rejected": int(status.astype(str).str.startswith("rejected").sum()),
            "n_error": int(status.astype(str).str.startswith("error").sum()),
            "n_nonenglish": n_nonenglish,
            "n_translated": n_translated,
            "is_translated": bool(n_nonenglish == 0 or n_translated >= n_nonenglish),
            "date_min": plausible.min().date().isoformat() if not plausible.empty else "",
            "date_max": plausible.max().date().isoformat() if not plausible.empty else "",
            "doc_id_first": doc_ids[0] if doc_ids else "",
            "doc_id_last": doc_ids[-1] if doc_ids else "",
            "model": (df.get("clean_model", pd.Series(dtype=str)).dropna().iloc[0]
                      if "clean_model" in df.columns and df["clean_model"].notna().any() else ""),
            "parquet_file": p.as_posix(),
            "last_updated": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
        })
    if not rows:
        return None
    out_path = Path(out_root) / out_name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(["country", "source_id"]).to_excel(out_path, index=False)
    log.info("index: wrote %d source(s) to %s", len(rows), out_path)
    return out_path


def main():
    ap = argparse.ArgumentParser(description="Merge cleaned per-source Parquets into the intermediate dataset")
    ap.add_argument("--out-root", default="data/cleaned")
    ap.add_argument("--build-path", default=DEFAULT_BUILD)
    ap.add_argument("--compression", default="zstd")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    path = build_dataset(args.out_root, args.build_path, args.compression)
    build_clean_index(args.out_root)
    if path:
        print(f"wrote {path}")
        print("NEXT: run `Rscript scripts/export_leaderspeech.R` to apply fixNames and write "
              "the final LeaderSpeech.parquet / .RData / .csv.gz")
    else:
        print("no cleaned data found; nothing merged")


if __name__ == "__main__":
    main()
