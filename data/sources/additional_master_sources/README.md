# Agent outbox — one file per source

When a recipe PR proposes a source (or reports its status), it writes **its own file
here**, named after the `source_id`:

```
data/sources/additional_master_sources/<source_id>.csv
```

Each file is a normal CSV: the header row, then one or more rows for that source
(append newer status rows below older ones — it is fine for a file to carry a source's
history).

```csv
source_id,recipe_status,renderer,language,date_start,date_end,last_checked,notes
mex_amlo,draft,static,Spanish,2018,2024,2026-07-08,"NEW master row needed | country=Mexico; source_url=…; region=North America; iso3n=484; … short probe notes"
```

## Why one file per source

Distinct filenames can't collide, so parallel PRs **never** produce a merge conflict on
the outbox — no manual conflict resolution, no `merge=union` driver, regardless of how
many recipes are in flight. (The single shared `additional_master_sources.csv` it
replaced conflicted on every concurrent PR, because GitHub's web merge ignores the
`merge=union` attribute.)

## Rules

- **Add a new file `<source_id>.csv`; do not edit the legacy flat
  `data/sources/additional_master_sources.csv`** (frozen; kept only for the pre-folder
  rows) and **never touch `master_sources.xlsx`** (researcher-owned).
- Use the exact 8-column header above.
- One `source_id` per file. Two sources for one country (e.g. a live recipe and a
  `*_wayback` recipe) are two files.

## Aggregating for review

To get a single combined view (e.g. before folding approved rows into
`master_sources.xlsx`):

```bash
python scripts/merge_additional_sources.py            # print to stdout
python scripts/merge_additional_sources.py -o all.csv # or write to a file
```

It concatenates the legacy flat file and every fragment here and emits **master-aligned
columns** so you can paste approved rows straight into `master_sources.xlsx`. Two things
it does for you:

- **de-duplicates** to the *latest* row per `source_id` (append-only files may carry a
  source's history; you only want its current status). `--all-history` keeps every row.
- **extracts** `country` / `source_url` / `region` / `iso3n` / `source_name` /
  `source_type` / `content_format` / `leaders_covered` from the `key=value` pairs in
  `notes` into their own columns.

So at minimum put those as `key=value` in `notes` (e.g. `... | country=Mexico;
source_url=https://…; region=North America; iso3n=484; source_type=official_gov;
content_format=fulltext`). Cleaner still: add them as real columns. Nothing in the
pipeline reads the outbox programmatically — regenerate the view whenever you want it.
