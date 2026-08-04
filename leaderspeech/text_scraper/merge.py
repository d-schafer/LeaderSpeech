"""Concatenate every scraped source CSV into one table, for inspection.

This is the merge step `index.py` was built to feed: it reads
`data/scraped/scraped_progress_log.xlsx` and concatenates every file its `csv_file`
column lists — text-scraper and video/audio-scraper sources alike, since both write the
same schema into the same tree.

    python -m leaderspeech.text_scraper.merge             # -> data/scraped/LeaderSpeech_scraped.parquet
    python -m leaderspeech.text_scraper.merge --csv      # also a .csv.gz
    python -m leaderspeech.text_scraper.merge --no-index # ignore the index, glob the tree

The output lands in the scrape root, beside `scraped_progress_log.xlsx` — the index says what
was scraped, this holds it, and the two stay together. (Contrast `data/_build/`, which is the
CLEANER's staging area: `clean_structure_metadata.merge` writes its intermediate there for
`scripts/export_leaderspeech.R` to pick up. Both trees are gitignored.)

WHAT THIS IS NOT: the deliverable. These are RAW scraped rows — no speaker confirmation,
no document-type gate, no date resolution, no translation. Non-English sources still have
their text only in `*_originlanguage`. The published dataset comes from
`clean_structure_metadata.merge` + `scripts/export_leaderspeech.R`, which run after the
cleaning pass. This is the "let me look at what I've got" view, and it is cheap to rebuild.

Nothing is deduplicated or dropped. The one thing it does assert is **doc_id uniqueness**,
loudly, because every downstream join depends on it.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

from .index import INDEX_NAME, docid_sort_key
from .run import SCHEMA_COLUMNS

log = logging.getLogger("leaderspeech.text_scraper.merge")

# Written into the scrape root next to the index, so `--out-root` moves both together and a
# merge of some other tree can't silently overwrite the main one.
MERGED_NAME = "LeaderSpeech_scraped.parquet"

# Sidecars and derived files that live in the same folders but are not speech rows.
_NOT_A_SOURCE = ("_errors.csv", "_media.csv")


def _source_csvs(out_root: Path, use_index: bool = True) -> list[Path]:
    """Every source CSV to merge, from the index if it exists, else by globbing.

    The index is the documented contract (its `csv_file` column), but it is a
    regenerable artifact that may be stale or absent — so a glob of the same tree is the
    fallback rather than an error. Both paths exclude the `sample/` snapshot folders and
    the `_errors`/`_media` sidecars."""
    index_path = out_root / INDEX_NAME
    if use_index and index_path.exists():
        try:
            idx = pd.read_excel(index_path)
        except Exception as e:  # noqa: BLE001 — a locked/corrupt workbook shouldn't block a merge
            log.warning("merge: could not read %s (%s) — falling back to a glob", index_path, e)
        else:
            if "csv_file" in idx.columns:
                paths, missing = [], []
                for rel in idx["csv_file"].dropna():
                    p = Path(str(rel))
                    if not p.exists():
                        # The index stores repo-relative posix paths ("data/scraped/X/y.csv"),
                        # so they only resolve as-is from the repo root. Re-root them on
                        # out_root's parents so a merge works from any cwd.
                        p = out_root.parent.parent / str(rel)
                    (paths if p.exists() else missing).append(p)
                if missing:
                    log.warning("merge: %d file(s) listed in the index are missing — "
                                "rebuild it with `python -m leaderspeech.text_scraper.index`",
                                len(missing))
                    for p in missing[:5]:
                        log.warning("  missing: %s", p)
                if paths:
                    # A STALE index under-collects in silence: it lists fewer sources than
                    # the tree holds, and the merge looks like it succeeded. Missing files
                    # announce themselves above; sources the index has never heard of do
                    # not, so compare against the tree explicitly.
                    on_disk = {p.resolve() for p in _glob_sources(out_root)}
                    unlisted = on_disk - {p.resolve() for p in paths}
                    if unlisted:
                        log.warning(
                            "merge: %d source CSV(s) on disk are NOT in the index — it is stale. "
                            "Rebuild it (`python -m leaderspeech.text_scraper.index`) or pass "
                            "--no-index, or these sources are silently left out:", len(unlisted))
                        for p in sorted(unlisted)[:10]:
                            log.warning("  unlisted: %s", p.name)
                    log.info("merge: %d source CSV(s) from %s", len(paths), index_path.name)
                    return sorted(paths)
            log.warning("merge: %s has no usable `csv_file` column — falling back to a glob",
                        index_path.name)

    paths = _glob_sources(out_root)
    log.info("merge: %d source CSV(s) found by globbing %s", len(paths), out_root)
    return paths


def _glob_sources(out_root: Path) -> list[Path]:
    """Every `<Country>/<id>.csv` under the scrape root, minus sidecars and snapshots."""
    return sorted(p for p in out_root.glob("*/*.csv")
                  if not p.name.endswith(_NOT_A_SOURCE) and p.parent.name != "sample")


def _ordered_columns(frames: list[pd.DataFrame]) -> list[str]:
    """Schema columns first, in their canonical order, then any extras alphabetically.

    Sources scraped at different times have different column sets — `date_regex_recovered`
    only exists on rows scraped after it was added — so the union is taken deliberately
    and the older rows get NA, rather than letting concat decide the order."""
    seen: set[str] = set()
    for f in frames:
        seen.update(f.columns)
    extras = sorted(seen - set(SCHEMA_COLUMNS) - {"source_id"})
    return ["source_id"] + [c for c in SCHEMA_COLUMNS if c in seen] + extras


def merge_scraped(
    out_root: str = "data/scraped",
    out_path: str | None = None,   # default: <out_root>/LeaderSpeech_scraped.parquet
    use_index: bool = True,
    write_csv: bool = False,
) -> pd.DataFrame:
    root = Path(out_root)
    out_path = out_path or str(root / MERGED_NAME)
    paths = _source_csvs(root, use_index=use_index)
    if not paths:
        log.warning("merge: no source CSVs under %s — nothing to merge", root)
        return pd.DataFrame()

    frames = []
    for p in paths:
        try:
            # Everything as str: doc_id must not become an int, and mixed date formats
            # must survive to the cleaner untouched.
            df = pd.read_csv(p, dtype=str, low_memory=False)
        except Exception as e:  # noqa: BLE001
            log.warning("merge: skipping unreadable %s :: %s", p, e)
            continue
        if df.empty:
            continue
        df.insert(0, "source_id", p.stem)  # provenance: which recipe produced the row
        frames.append(df)

    if not frames:
        log.warning("merge: every source CSV was empty or unreadable")
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True).reindex(columns=_ordered_columns(frames))
    if "doc_id" in merged.columns:
        # `.fillna("")` is load-bearing: an empty doc_id cell reads back as NaN, and a
        # float reaching `docid_sort_key`'s regex raises TypeError — so one malformed row
        # would abort the whole merge instead of being reported by `_report`.
        merged = merged.sort_values(
            "doc_id", key=lambda s: s.fillna("").astype(str).map(docid_sort_key),
            kind="stable", ignore_index=True,
        )

    _report(merged)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(out, index=False)
    log.info("merge: wrote %s (%d rows x %d cols)", out, len(merged), merged.shape[1])
    if write_csv:
        gz = out.with_suffix("").with_suffix(".csv.gz")
        merged.to_csv(gz, index=False, compression="gzip")
        log.info("merge: wrote %s", gz)
    return merged


def _report(df: pd.DataFrame) -> None:
    """Log what landed, and check the one invariant everything downstream depends on."""
    log.info("merge: %d rows | %d sources | %d countries",
             len(df), df["source_id"].nunique(),
             df["country"].nunique() if "country" in df.columns else 0)

    if "doc_id" not in df.columns:
        log.error("merge: NO doc_id COLUMN — downstream joins will not work")
        return

    blank = df["doc_id"].isna() | (df["doc_id"].fillna("").str.strip() == "")
    dup = df["doc_id"].duplicated(keep=False) & ~blank
    if blank.any():
        log.error("merge: %d row(s) have a BLANK doc_id", int(blank.sum()))
    if dup.any():
        # Loud on purpose: a reused doc_id silently corrupts every later join, and unlike
        # a missing row it does not announce itself.
        log.error("merge: DUPLICATE doc_id — %d row(s) share %d id(s). Affected sources: %s",
                  int(dup.sum()), int(df.loc[dup, "doc_id"].nunique()),
                  ", ".join(sorted(df.loc[dup, "source_id"].unique())[:10]))
    if not blank.any() and not dup.any():
        log.info("merge: doc_id OK — %d unique ids, no blanks", df["doc_id"].nunique())

    # Per-country counter width, so a country that has passed 9,999 is visible rather
    # than looking like a wrapped counter (see index.docid_sort_key).
    if "country" in df.columns:
        nums = pd.to_numeric(df["doc_id"].str.extract(r"(\d+)$")[0], errors="coerce")
        wide = df.loc[nums > 9999, "country"].value_counts()
        if not wide.empty:
            log.info("merge: countries past doc_id 9999 (5-digit ids, still unique): %s",
                     ", ".join(f"{c} ({n})" for c, n in wide.items()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Concatenate every scraped source CSV into one table.")
    ap.add_argument("--out-root", default="data/scraped", help="scrape root holding <Country>/<id>.csv")
    ap.add_argument("--out", default=None,
                    help=f"output Parquet path (default: <out-root>/{MERGED_NAME})")
    ap.add_argument("--csv", action="store_true", help="also write a gzipped CSV next to the Parquet")
    ap.add_argument("--no-index", action="store_true",
                    help="ignore scraped_progress_log.xlsx and glob the tree instead")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(name)s: %(message)s")
    df = merge_scraped(out_root=args.out_root, out_path=args.out,
                       use_index=not args.no_index, write_csv=args.csv)
    return 0 if len(df) else 1


if __name__ == "__main__":
    sys.exit(main())
