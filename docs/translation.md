# Translation — filling the English `text` / `title` / `context`

The scraper stores a non-English speech with the original in `text_originlanguage`
(and `title_originlanguage`, `context_originlanguage`) and leaves the unsuffixed
`text` / `title` / `context` **empty** — the project schema convention is that the
unsuffixed columns hold the **English** version. This tool fills those English columns
**in place**, choosing a translation backend so you can test and compare.

It writes nothing new to disk besides the file it's translating: no `data/translated/`
tree, no separate dataframe versions. The original is always preserved in
`*_originlanguage`, and writes are atomic (`.tmp` → `os.replace`, prior file kept as
`.bak`), so an interrupted run never corrupts the file. **Resumability needs no ledger:**
a row is "done" once its English target is filled, so a re-run just skips it.

## The loop

```bash
# 1) compare backends on a sample (no writes) — pick one
python -m leaderspeech.translate.probe --source arg_casarosada --n 3 --translator google
python -m leaderspeech.translate.probe --source arg_casarosada --translator google,nllb

# 2) translate one cleaned source (in place), a country, or everything
python -m leaderspeech.translate.run --source arg_casarosada --limit 20
python -m leaderspeech.translate.run --country Argentina
python -m leaderspeech.translate.run --all

# 3) ...or any table at any stage (raw scraped CSV, the merged build, an external file)
python -m leaderspeech.translate.run --input data/scraped/Chile/chl_presidencia.csv
```

After a `--source/--country/--all` run, the derived index
`data/cleaned/cleaned_progress_log.xlsx` is refreshed: its `n_nonenglish`,
`n_translated`, and `is_translated` columns show translation progress per source. These
are computed from the data (origin text present vs English `text` filled), so they can
never drift from a stale flag.

There is **no pipeline rewiring**: `merge` keeps reading `data/cleaned/*/*.parquet`, which
by run time already have their English columns filled, and `scripts/export_leaderspeech.R`
is unchanged. The natural slot is between `clean` and `merge`, but the tool is
stage-agnostic via `--input`.

## Backends (choose with `--translator`)

| backend  | how | install | needs source lang? |
|----------|-----|---------|--------------------|
| `google` (default) | Google Translate via `deep-translator` (online, free) | `pip install .[translate-google]` — runs in the `leaderspeech_scrape` venv | no (auto-detects) |
| `opusmt` | Helsinki-NLP `opus-mt-<src>-en` MarianMT (offline) | `pip install .[translate-hf]` — needs the transformers/GPU env | yes |
| `nllb`   | `facebook/nllb-200` multilingual model (offline) | `pip install .[translate-hf]` | yes |

The local (`opusmt`/`nllb`) backends need a known source language. It is taken from
`detected_language` (the ISO code the cleaner records), then `source_language` (a name
like "Spanish", mapped to an ISO code). `google` falls back to auto-detect when the
language is unknown.

Long text is split at sentence/punctuation boundaries (online: by character budget;
local: by source-token budget) and rejoined, so over-long speeches translate cleanly.

## What gets written

For each row that needs work, the chosen `fields` (default `text`, `title`, `context`)
are filled from their `*_originlanguage` counterparts, and two provenance columns are set:
`text_translator` (backend name) and `translated_at` (timestamp). English rows
(`*_originlanguage` empty) are a no-op. On a cleaned Parquet, rejected rows are skipped by
default (`only_accepted: true`); pass `--all-rows` to translate them too.

## Configuration reference (`configs/translate_config.yml`)

| key | effect |
|-----|--------|
| `translator` | default backend (`google`); CLI `--translator` overrides |
| `target_language` | ISO code of the target columns (`en`) |
| `fields` | which columns to fill from `*_originlanguage` |
| `only_accepted` | on a cleaned Parquet, skip non-`accepted` rows (saves online calls) |
| `max_chunk_chars` | character budget per chunk for the online backend |
| `pause_every` / `pause_seconds` | light pacing for online backends |
| `checkpoint_every` | rows between atomic rewrites (crash-safe progress) |
| `nllb_model` | `facebook/nllb-200-distilled-600M` (default) or `...-3.3B` for top quality |
| `device` | `auto` / `cuda` / `cpu` for the local backends |

## Cost / etiquette

`google` is free but rate-limited — keep the default pacing on big runs. The local
backends cost only GPU/CPU time. Re-runs never redo finished rows, so a long translation
can be done incrementally.
