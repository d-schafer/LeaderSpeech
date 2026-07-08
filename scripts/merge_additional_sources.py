#!/usr/bin/env python3
"""Aggregate the per-source agent outbox into a single, master-aligned CSV view.

The agent "outbox" is a **folder** of one CSV per source
(``data/sources/additional_master_sources/<source_id>.csv``, each a header + one or
more rows). One file per source means parallel recipe PRs never touch the same file,
so they never merge-conflict. A **legacy** flat file
``data/sources/additional_master_sources.csv`` still holds the pre-folder rows (frozen).

This script concatenates the legacy file and every fragment, then emits a CSV whose
columns line up with ``master_sources.xlsx`` so the researcher can paste approved rows
straight in. Two conveniences make that paste clean:

* **De-duplication** — only the *latest* row per ``source_id`` is emitted (outbox files
  are append-only history; you only want the current status). Use ``--all-history`` to
  keep every row.
* **Column extraction** — older outbox rows carry ``country`` / ``source_url`` / ``region``
  / ``iso3n`` / ``source_name`` / ``source_type`` / ``content_format`` / ``leaders_covered``
  as ``key=value`` pairs inside ``notes`` (e.g. ``... | country=Mexico; source_url=…``).
  Those are parsed out into their own columns here, so you don't have to. New outbox
  files should just use the master columns directly (see the folder README).

The fragments (and the frozen legacy file) are the source of truth; this output is
derived — regenerate it whenever you want a single view.

Usage:
    python scripts/merge_additional_sources.py                 # print to stdout
    python scripts/merge_additional_sources.py -o pending.csv  # write to a file
    python scripts/merge_additional_sources.py --all-history   # keep every row
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

SOURCES_DIR = Path("data/sources")
OUTBOX_DIR = SOURCES_DIR / "additional_master_sources"
LEGACY_CSV = SOURCES_DIR / "additional_master_sources.csv"

# The columns we emit, aligned to master_sources.xlsx (minus workflow-only cols the
# researcher fills, e.g. full_scrape_done).
MASTER_COLS = [
    "source_id", "country", "region", "iso3n", "source_name", "source_url",
    "source_type", "renderer", "leaders_covered", "date_start", "date_end",
    "language", "content_format", "recipe_status", "last_checked", "notes",
]
# Fields we try to lift out of a `key=value` notes blob when a row lacks its own column.
NOTE_FIELDS = [
    "country", "source_url", "source_name", "region", "iso3n",
    "source_type", "content_format", "leaders_covered",
]


def _from_notes(notes: str, field: str) -> str:
    m = re.search(rf"{field}\s*=\s*([^;|]+)", notes or "")
    return m.group(1).strip() if m else ""


def _row_to_master(row: dict) -> dict:
    """Map one outbox row (any subset of columns) to the master column set, filling
    country/url/etc from the notes when they aren't already present as columns."""
    out = {c: (row.get(c) or "").strip() for c in MASTER_COLS}
    notes = row.get("notes") or ""
    for f in NOTE_FIELDS:
        if not out.get(f):
            out[f] = _from_notes(notes, f)
    out["source_id"] = (row.get("source_id") or "").strip()
    return out


def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if (r.get("source_id") or "").strip()]


def collect(outbox_dir: Path, legacy_csv: Path, dedup: bool) -> list[dict]:
    raw: list[dict] = []
    if legacy_csv.is_file():
        raw += _read(legacy_csv)
    if outbox_dir.is_dir():
        for path in sorted(outbox_dir.glob("*.csv")):
            raw += _read(path)
    mapped = [_row_to_master(r) for r in raw]
    if dedup:
        latest: dict[str, dict] = {}
        for r in mapped:  # later rows (by last_checked, then read order) win
            sid = r["source_id"]
            cur = latest.get(sid)
            if cur is None or (r.get("last_checked", "") >= cur.get("last_checked", "")):
                latest[sid] = r
        mapped = list(latest.values())
    mapped.sort(key=lambda r: r["source_id"])
    return mapped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(OUTBOX_DIR))
    ap.add_argument("--legacy", default=str(LEGACY_CSV))
    ap.add_argument("--all-history", action="store_true", help="keep every row, not just the latest per source_id")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    rows = collect(Path(args.dir), Path(args.legacy), dedup=not args.all_history)
    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        w = csv.DictWriter(out, fieldnames=MASTER_COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    finally:
        if args.out:
            out.close()
    if args.out:
        print(f"wrote {len(rows)} source(s) -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
