# Agent outbox — one file per source

When a recipe PR proposes a source (or reports its status), it writes **its own file
here**, named after the `source_id`:

```
data/sources/additional_master_sources/<source_id>.csv
```

Each file is a normal CSV: the header row, then one or more rows for that source
(append newer status rows below older ones — it is fine for a file to carry a source's
history; the newest row wins when it is folded in).

## Use the `master_sources.xlsx` columns directly

So the file can be folded in **deterministically** (matched by column name, no parsing of
prose), use the master schema's columns — **not** a shorter header with metadata stuffed
into `notes`:

```csv
source_id,country,region,iso3n,source_name,source_url,source_type,renderer,leaders_covered,date_start,date_end,language,content_format,recipe_status,full_scrape_done,last_checked,notes
mex_amlo,Mexico,North America,484,gob.mx/presidencia,https://www.gob.mx/presidencia,official_gov,static,Andrés Manuel López Obrador,2018,2024,Spanish,fulltext,draft,,2026-07-08,"short probe notes — anything WITHOUT its own column (selectors tried, blockers, coverage caveats)."
```

- Fill in every column you can. `notes` is only for information that has **no** column of
  its own (probe findings, blockers, caveats) — don't put `country`/`source_url`/etc. there.
- Leave **`full_scrape_done`** blank — the researcher sets it after a full run.
- `country` is **required** (the append script skips a row without it, so a half-filled
  file can't inject a mostly-blank master row).

## Why one file per source

Distinct filenames can't collide, so parallel PRs **never** produce a merge conflict on
the outbox — no manual conflict resolution, no `merge=union` driver, regardless of how
many recipes are in flight. (The single shared `additional_master_sources.csv` it
replaced conflicted on every concurrent PR, because GitHub's web merge ignores the
`merge=union` attribute.)

## Rules

- **Add a new file `<source_id>.csv`; do not edit the legacy flat
  `data/sources/additional_master_sources.csv`** (frozen; kept only for the pre-folder
  rows) and **never edit `master_sources.xlsx` directly** (researcher-owned — it is
  updated only by the append script below, which the researcher runs).
- Use the master-schema header above. One `source_id` per file. Two sources for one
  country (e.g. a live recipe and a `*_wayback` recipe) are two files.

## Folding approved rows into `master_sources.xlsx` (researcher-run)

`data/sources/append_additional_sources.R` appends every **new** `source_id` here into
`master_sources.xlsx`, matching columns by name:

```bash
Rscript data/sources/append_additional_sources.R --dry-run   # report what WOULD be added
Rscript data/sources/append_additional_sources.R             # append + save
```

- **`source_id` is the key** — a source already in `master_sources.xlsx` is left untouched;
  only genuinely new ones are appended. Safe + idempotent (a second run adds nothing).
- Existing rows and the workbook's formatting are preserved (new rows are appended below
  the last row; the curated rows are never rewritten).
- Rows without a `country` are reported as *skipped (incomplete)* — finish them and re-run.
- To keep a source out of the backlog **permanently** (e.g. a third-party / non-primary source),
  add its `source_id` to the `exclude_ids` list at the top of the script — it is then reported as
  *excluded* and never appended, even if its outbox file is complete.
- Close `master_sources.xlsx` in Excel first, or the save fails on the file lock.

The script (and the archived earlier Python aggregator in `data/sources/_archive/`) are
**git-ignored** local tooling — they are not part of the published package.
