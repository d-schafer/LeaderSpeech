#!/usr/bin/env python3
"""Aggregate the per-source agent outbox into a single CSV view.

The agent "outbox" is a **folder** of one CSV per source
(``data/sources/additional_master_sources/<source_id>.csv``, each a header + one or
more rows). One file per source means parallel recipe PRs never touch the same file,
so they never merge-conflict — that is the whole point of the folder convention.

A **legacy** flat file, ``data/sources/additional_master_sources.csv``, still holds the
pre-folder rows (frozen; do not append to it — add a per-source file instead). This
script concatenates the legacy file **and** every folder fragment into one CSV for
review — e.g. to fold approved rows into the researcher-owned ``master_sources.xlsx``
by hand. The fragments (and the frozen legacy file) are the source of truth; the
aggregated output is derived — regenerate it whenever you want a single view.

Usage:
    python scripts/merge_additional_sources.py                 # print to stdout
    python scripts/merge_additional_sources.py -o outbox.csv   # write to a file
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

SOURCES_DIR = Path("data/sources")
OUTBOX_DIR = SOURCES_DIR / "additional_master_sources"
LEGACY_CSV = SOURCES_DIR / "additional_master_sources.csv"
CANONICAL_HEADER = [
    "source_id", "recipe_status", "renderer", "language",
    "date_start", "date_end", "last_checked", "notes",
]


def _read(path: Path, header_ref: list[str] | None) -> tuple[list[str] | None, list[list[str]]]:
    with path.open(newline="", encoding="utf-8") as f:
        recs = list(csv.reader(f))
    if not recs:
        return header_ref, []
    file_header, *data = recs
    if header_ref is not None and file_header != header_ref:
        print(f"warning: {path} header differs from the canonical one; "
              f"keeping the first header seen", file=sys.stderr)
    rows = [r for r in data if r and r[0].strip()]  # skip blank lines
    return (header_ref or file_header), rows


def collect(outbox_dir: Path, legacy_csv: Path) -> tuple[list[str], list[list[str]]]:
    """Merge the legacy flat file and every folder fragment, sorted by source_id."""
    header: list[str] | None = None
    rows: list[list[str]] = []
    if legacy_csv.is_file():
        header, legacy_rows = _read(legacy_csv, header)
        rows.extend(legacy_rows)
    if outbox_dir.is_dir():
        for path in sorted(outbox_dir.glob("*.csv")):
            header, frag_rows = _read(path, header)
            rows.extend(frag_rows)
    rows.sort(key=lambda r: (r[0], r[6] if len(r) > 6 else ""))  # source_id, last_checked
    return header or CANONICAL_HEADER, rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", default=str(OUTBOX_DIR), help="outbox folder (default: %(default)s)")
    ap.add_argument("--legacy", default=str(LEGACY_CSV), help="legacy flat file (default: %(default)s)")
    ap.add_argument("-o", "--out", help="write here instead of stdout")
    args = ap.parse_args()

    header, rows = collect(Path(args.dir), Path(args.legacy))
    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        w = csv.writer(out, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    finally:
        if args.out:
            out.close()
    if args.out:
        print(f"wrote {len(rows)} row(s) -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
