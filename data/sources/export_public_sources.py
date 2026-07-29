"""Generate the PUBLIC source list from the researcher's private master list.

The repo publishes **which sources exist** — that is the useful, citable part of the
backlog — but not our working notes about them. `master_sources.xlsx` carries a free-text
`notes` column of operational commentary (what is blocked, why, what to try next) plus
internal progress state; none of that is a research deliverable, and some of it reads as
intent to work around access controls. So the xlsx stays local and this script emits a
notes-free view that IS committed.

    python data/sources/export_public_sources.py

Writes `data/sources/sources.csv`. It is a GENERATED artifact — never edit it by hand and
never treat it as a second list to keep in sync; regenerate it after editing the xlsx.
(Same convention as `data/scraped/scraped_progress_log.xlsx`, which the scraper rebuilds.)

CSV rather than xlsx on purpose: GitHub renders and diffs it, so a reader can see what
changed between commits.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
MASTER = HERE / "master_sources.xlsx"
PUBLIC = HERE / "sources.csv"

# Everything the public list should carry: the identity, provenance and coverage of a
# source. Anything not listed here is dropped, so a new private column added to the xlsx
# is excluded by DEFAULT rather than leaking the next time someone regenerates.
PUBLIC_COLUMNS = [
    "source_id",
    "country",
    "region",
    "iso3n",
    "source_name",
    "source_url",
    "source_type",
    "renderer",
    "leaders_covered",
    "date_start",
    "date_end",
    "language",
    "content_format",
    "recipe_status",
]

# Named explicitly so the intent is on the record rather than implied by omission:
#   notes            - free-text operational commentary (the reason this script exists)
#   full_scrape_done - internal progress state
#   last_checked     - internal progress state
DROPPED_COLUMNS = ["notes", "full_scrape_done", "last_checked"]


def main() -> int:
    if not MASTER.exists():
        print(f"!! {MASTER} not found. It is local-only by design (see .gitignore); this "
              f"script needs the researcher's copy.", file=sys.stderr)
        return 1

    df = pd.read_excel(MASTER)
    keep = [c for c in PUBLIC_COLUMNS if c in df.columns]
    missing = [c for c in PUBLIC_COLUMNS if c not in df.columns]
    unknown = [c for c in df.columns if c not in PUBLIC_COLUMNS and c not in DROPPED_COLUMNS]

    out = df[keep].copy()

    # Dropping the `notes` column is not enough on its own: notes get pasted into structured
    # columns by hand too. Two rows in the master list have a whole paragraph in
    # `content_format` ("pdf. The Biblioteca da Presidencia is ... the live origin resets
    # connections from this network"), which would republish exactly what this script exists
    # to withhold. So every published cell is also clipped to its first sentence.
    #
    # Only cells LONGER than this are touched, so ordinary values are never mangled — a
    # source_name of "U.S. White House" contains ". " but is far under the threshold.
    MAX_STRUCTURED_CHARS = 120
    clipped = []
    for c in keep:
        for i, v in out[c].items():
            if not isinstance(v, str) or len(v) <= MAX_STRUCTURED_CHARS:
                continue
            head = re.split(r"\.\s|\n", v, maxsplit=1)[0].strip()
            if len(head) > MAX_STRUCTURED_CHARS:          # no sentence break — hard cut
                head = head[:MAX_STRUCTURED_CHARS].rstrip()
            out.at[i, c] = head
            clipped.append((i, c, v, head))

    out.to_csv(PUBLIC, index=False, encoding="utf-8")

    print(f"wrote {PUBLIC}  ({len(out):,} sources, {len(keep)} columns)")
    print(f"  dropped: {[c for c in DROPPED_COLUMNS if c in df.columns]}")
    if missing:
        print(f"  NOTE expected columns absent from the xlsx: {missing}")
    if unknown:
        print(f"  !! NEW columns in the xlsx are NOT published (add to PUBLIC_COLUMNS if "
              f"they should be): {unknown}")
    if clipped:
        print(f"  clipped {len(clipped)} over-long cell(s) in structured columns to their "
              f"first sentence (a note pasted into the wrong field):")
        for i, c, before, after in clipped[:6]:
            print(f"       row {i} {c!r}: {before[:70]}...  ->  {after!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
