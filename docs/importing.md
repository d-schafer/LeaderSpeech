# Importing a table collected elsewhere

`python -m leaderspeech.text_scraper.import_legacy --spec <spec.yml> [--apply]`

Some speeches were collected before this tool existed — by an earlier project's script, say —
and the site has since deleted them, or re-fetching them from the Internet Archive would take
hours for text that is already on disk. The importer writes such a table into the corpus **as
if it had been scraped**, so the cleaner, translator, merge and index treat it like any other
source:

| writes | what |
|---|---|
| `data/scraped/<Country>/<source_id>.csv` | the rows, in the standard schema. A non-English source's text goes to `*_originlanguage`; the English columns are filled only where the spec maps a real translation |
| `data/state/<Country>.json` | the `doc_id`s come from the country's shared counter, and every imported URL is added to `seen_urls` — so **every recipe of that country skips those documents** (backup taken first) |
| `<source_id>_links.txt` | the imported URLs (the index's denominator) |
| `<source_id>_import.json` | where the rows came from, when, and how; the index labels the source `renderer=import`, `pagination_type=legacy_import` |
| `<source_id>_import_extra.parquet` | optional: input columns with no schema column, kept verbatim, keyed by `doc_id`. Parquet, so no pipeline stage mistakes it for a source CSV |

It is a **dry run by default** — it prints the row count, `doc_id` range, date span and what it
would skip. `--apply` writes. Re-running is safe: rows the state file or the target CSV already
holds are skipped.

## The spec

```yaml
source_id: mex_presidencia_amlo_import
country: Mexico                    # the same spelling a recipe would use
source_language: Spanish
position: president                # optional
dataset: LeaderSpeech              # optional
input: amlo_2024_scrape.parquet    # .csv or .parquet; relative paths are relative to the spec
date_languages: [es]               # optional; only used for dates that are not already ISO
columns:                           # schema field -> input column; `source` and `text` required
  source: list                     #   (fields: source, title, text, context, date, speaker)
  title: title
  text: text
  context: context
  date: date
english:                           # optional, non-English sources: input columns that are
  title: title_en                  #   TRANSLATIONS of the mapped originals (title/text/context)
  context: context_en
extra:                             # optional: kept in <source_id>_import_extra.parquet
  text_en_leader_only: text_en
identity_noise_params: [idiom]     # optional: same meaning as a recipe's wayback_noise_params /
identity_strip: ['(?<=/presidencia)/es(?=/)']   # wayback_identity_strip — used to recognise a row
                                   #   the corpus already holds under ANOTHER URL form
notes: free text, shown in the index
```

Keep import specs and their input tables under `data/imports/` (gitignored — they point at
local files).

## Before you apply

- **Check for documents the corpus already holds.** The importer compares page identity (scheme,
  `www.`, port, trailing slash and the generic noise parameters normalized) against the country's
  state file and the target CSV. If the site served the same article under URL variants the
  generic normalization does not cover — a UI language toggle in the query, a language segment in
  the path — set `identity_noise_params` / `identity_strip` to what the country's Archive recipe
  uses. Measure the overlap first (by slug or article id); the dry run's `already_held` count
  should equal it.
- **Give the Archive recipe the same identity knobs.** The point of an import is that a later
  Archive run skips these documents; its `select_unscraped` only recognises them if its own
  `wayback_noise_params` / `wayback_identity_strip` fold the URL forms together.
- **Only map an English column that translates the mapped original.** A partial translation —
  say, only the leader's turns of a transcript — belongs in `extra`, not in `text`: the
  translate stage would treat `text` as done, and the corpus would pair a full original with a
  partial English.
- **Check the dates.** Re-parse the table's raw date string with the engine and compare.

## Example: Mexico 2018–2024

`mex_presidencia_amlo_import` holds 2,552 pages of the presidency's archive (2018-11-30 →
2024-01-18) collected from the live site in January 2024, before the archive listing was emptied.
82 more pages of that table were already in the corpus from `mex_presidencia_wayback`'s first
run and were skipped. After the import, that Archive recipe's next run fetches ~1,190 documents
instead of ~2,640.
