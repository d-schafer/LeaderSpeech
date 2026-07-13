# Cleaning & structuring metadata (`clean_structure_metadata`)

The scraper gives you rows that are *structurally* clean but *semantically* messy: the speaker
column is often blank, some "speeches" are press releases or agendas, dates can be wrong, and
there's no audience/venue/type. This tool reads the scraper's per-source CSVs and, with **one cheap
GPT structured-extraction pass per speech** plus a deterministic crosscheck against the
leader-tenure key, produces enriched, gated rows.

The non-negotiable rule: **every kept row has a speaker and REPRESENTS THE LEADER** — a delivered
speech, an interview, or an official statement/communiqué issued in the leader's name that conveys
their position, values, or policy (including third-person ones like "The President… He reaffirms…").
Pure news reports, biographies, agendas, and logistical notices are not kept. Rows that fail are not
deleted — they're set aside in the same file with a `rejected_*` `clean_status`, so nothing is lost
and every decision is auditable.

> Scope of v1 (core MVP): extraction + tenure crosscheck + name standardization + the hard gate.
> Deferred: translation into the English `text`/`title` columns, and the leader-tenure *curation*
> loop (proposing new leaders into `leader_tenure_final.csv`).

## Install & setup

```bash
pip install -e ".[llm]"      # core deps + the openai client
```

- **OpenAI key:** set `OPENAI_API_KEY`, or put the key in `openai_key.txt` at the repo root
  (gitignored). The cleaner reads the env var first.
- **Leader-tenure key:** the cleaner crosschecks speakers against `leader_tenure_final.csv`
  (speaker / country / year / `is_ceremonial`). It lives in the parent research workspace; copy or
  symlink it to `data/sources/leader_tenure_final.csv`, or set an absolute `tenure_file` in
  `configs/clean_config.yml`. If it's missing the tool still runs, just without the crosscheck.
- **R export (final step):** needs the R `arrow` package (`install.packages("arrow")`).

## The loop: probe → run → merge → export

```bash
# 1) PROBE — eyeball quality on a random sample, no writes, cheap. Iterate the prompt here.
python -m leaderspeech.clean_structure_metadata.probe --all-countries --n 5
python -m leaderspeech.clean_structure_metadata.probe --source chl_presidencia --n 8

# 2) RUN — clean a source (or a whole country / everything). Resumable.
python -m leaderspeech.clean_structure_metadata.run --source chl_presidencia --limit 20   # trial
python -m leaderspeech.clean_structure_metadata.run --source chl_presidencia              # full
python -m leaderspeech.clean_structure_metadata.run --country Chile
python -m leaderspeech.clean_structure_metadata.run --all

# 2b) RUN on an ARBITRARY corpus — any CSV/Parquet, many countries/datasets in one table.
python -m leaderspeech.clean_structure_metadata.run --input data/LeaderSpeech.parquet       # -> data/LeaderSpeech.cleaned.parquet
python -m leaderspeech.clean_structure_metadata.run --input corpus.csv --output out.parquet  # explicit destination

# 3) MERGE — concatenate accepted rows from every source into the intermediate dataset.
python -m leaderspeech.clean_structure_metadata.merge

# 4) EXPORT — apply fixNames and write the final deliverable (Parquet + RData + csv.gz).
Rscript scripts/export_leaderspeech.R
```

Useful flags on `run`: `--model gpt-4.1` (override the model), `--limit N` (cap per source this
run), `--retry-failed` (re-attempt rows that errored), `--dry-run` (report counts, no API calls),
`--config path/to.yml`.

### Two input modes: per-source vs. `--input`

`--source/--country/--all` walk the scraper's `data/scraped/<Country>/<id>.csv` layout — one source =
one CSV = one country folder — and write the per-source ledger `data/cleaned/<Country>/<id>.parquet`.

`--input <table>` cleans **any single CSV or Parquet** instead (the merged deliverable, a raw export,
any corpus mixing countries / datasets / speakers). This works because the cleaning is **row-driven**:
each row's country, tenure crosscheck, and prompt come from its own `country` column, never a folder
name — so a combined corpus is handled correctly row by row. Specifics:

- **Output is non-destructive.** Default is a sibling `<input_stem>.cleaned.parquet` (the raw input is
  never overwritten); `--output PATH` redirects. Output format follows the path's extension.
- **Extra columns are preserved.** Any column beyond the standard 15 scraped fields (e.g. `ISI_id`,
  dataset-specific fields) is carried through cleaning unchanged and appended after the cleaned columns.
- **Resume keys on `doc_id`.** The output file *is* the ledger, exactly as in per-source mode: a re-run
  reads it back and skips rows already cleaned. This assumes `doc_id` is **unique within the corpus**
  (this project's `<ISO3>+N` ids are). A corpus that reuses `doc_id` across datasets could wrongly skip.
- `--input` ignores `--in-root/--out-root/--state-root`, does not refresh the cleaned-store index, and is
  incompatible with `--regate` (regate operates on the `data/cleaned/` tree). Parquet cells are coerced
  to strings (NA → `""`) to match the CSV path, so a numeric `ISO3N` may stringify (e.g. `"999.0"`).

## What the model returns (`SpeechMeta`)

One JSON object per speech, read from the speech's **original language** (translation is a later
stage — GPT reads non-English fine):

| field | values |
|-------|--------|
| `document_type` | speech / interview / official_statement / other |
| `is_first_person` | yes / no / unsure (recorded for analysis — not a gate) |
| `speaker` | clean full name, or null |
| `speaker_attributed_correct` | yes / no / unsure (vs the scraped speaker) |
| `speaker_type` | head_of_state / head_of_government / both / other_minister / foreign_visitor / other / unknown |
| `position` | short title (President, Prime Minister, King…) |
| `date` + `date_matches_metadata` | YYYY-MM-DD best estimate; yes / no / unsure |
| `language` | ISO 639-1 of the text |
| `audience` | one of 7 classes |
| `speech_type` | one of 10 classes |
| `venue` | short free text or null |
| `confidence`, `reasoning` | overall confidence; 1–2 sentence rationale |

After extraction, deterministic post-processing fills `tenure_match`
(`exact` / `other_country` / `none`), `is_ceremonial` (from the tenure key), and the `clean_status`
gate decision.

## The gate

`accepted` requires all three: the `document_type` is in `keep_document_types` (default `speech`,
`interview`, `official_statement`); the speaker is non-empty; and — when `require_leader_type` is on —
the speaker is not a `foreign_visitor` / minister / other. Reject statuses:
`rejected_not_representative` (a `document_type` of `other`, i.e. news/biography/agenda/logistics),
`rejected_no_speaker`, `rejected_foreign`, `rejected_non_leader`. Speakers whose type is `unknown` or
a head-of-state/government value pass — we don't drop a real leader just because the role was
uncertain. Both knobs live in `clean_config.yml` (see below).

## Configuration reference

Every field is in `configs/clean_config.yml`; override per run with `--config path.yml`, and the
model with `--model`. The two settings that change **what is kept**:

| setting | default | effect |
|---------|---------|--------|
| `keep_document_types` | `[speech, interview, official_statement]` | The `document_type`s that count as representing the leader and are kept. **Remove `official_statement`** to keep only things the leader said aloud (interviews + delivered speeches); anything not listed becomes `rejected_not_representative`. |
| `require_leader_type` | `true` | When `true`, speakers the model marks `foreign_visitor` / `other_minister` / `other` are set aside (`rejected_foreign` / `rejected_non_leader`). **Set `false`** to keep every representative document regardless of the speaker's role. |

Other settings: `model` (default `gpt-4.1-mini`), `temperature`, `max_tokens`, `max_words` (how much
text is sent), `batch_size` / `chunk_size` (concurrency + checkpoint granularity),
`max_consecutive_failures` (circuit breaker), `tenure_file` / `tenure_window`, `compression`
(`zstd` | `snappy`), `openai_key_file`.

**Changed the gate after a run?** Re-classify already-cleaned rows for **free** (no API calls) — the
gate reads the stored `document_type` / `speaker` / `speaker_type`:

```bash
python -m leaderspeech.clean_structure_metadata.run --source chl_presidencia --regate
python -m leaderspeech.clean_structure_metadata.run --all --regate
```

`--regate` rewrites `clean_status` in place from the stored fields (error rows untouched), so you can
tune `keep_document_types` / `require_leader_type` without re-spending or losing anything. (Plain
`--retry-failed` only re-attempts rows that *errored*, not rejected ones.)

## Storage, resumability, and safety

- **Per-source store:** `data/cleaned/<Country>/<id>.parquet` — one Parquet per source, accepted and
  rejected rows together (distinguished by `clean_status`). Parquet is compact, preserves UTF-8 text
  exactly (no CSV column-splitting), and loads from Python (`pd.read_parquet`) and R
  (`arrow::read_parquet`) alike.
- **The Parquet is the ledger.** A re-run reads it, diffs the scraped `doc_id`s against what's
  already cleaned, and sends only the *new* speeches to the model — so the model is never paid twice.
  Incremental scraper updates (new `doc_id`s) are picked up automatically.
- **Crash-safe / no overwrite:** the per-source file is rewritten **atomically** at each chunk
  checkpoint (`<id>.parquet.tmp` → `os.replace`, with the prior file kept as `<id>.parquet.bak`). The
  in-progress run holds all rows in memory and unions new rows by `doc_id`, so a re-run can only grow
  the file — it never clobbers prior cleaned data. A crash loses at most the current uncommitted
  chunk. **Assumes a single writer per source** — don't run two cleaners on one source at once.
- **State + logs:** `data/clean_state/<Country>/<id>.json` (counts, model, last run) and a timestamped
  `.log` next to the Parquet. `data/cleaned/cleaned_progress_log.xlsx` indexes every source.
- **Deliverable:** the Python merge writes the intermediate `data/_build/LeaderSpeech_merged.parquet`
  (accepted rows, deduped by `doc_id`); the R export applies `key_fixNames.R` and writes the final
  `data/LeaderSpeech.parquet` / `.RData` / `.csv.gz`, all name-consistent. All of these are derived
  and regenerable — re-run merge + export anytime; it costs nothing.

## Cleaned columns

The 15 standardized scraper columns (unchanged, for mergeability) plus: corrected-in-place
`speaker` / `position` / `date`; audit copies `speaker_scraped` / `date_scraped`; the extracted
`speaker_type`, `audience`, `speech_type`, `venue`, `detected_language`,
`speaker_attributed_correct`, `date_matches_metadata`; the crosscheck `tenure_match`,
`tenure_matched_name`, `is_ceremonial`; and `clean_status`, `gate_reason`, `clean_confidence`,
`clean_reasoning`, `clean_model`, `cleaned_at`. The final deliverable keeps the scraper schema plus a
curated metadata subset.

## Cost & tuning

Cost is roughly one `max_tokens`-bounded call per *new* speech, on the cheap default model
(`gpt-4.1-mini`). Knobs in `configs/clean_config.yml`: `model`, `max_words` (how much text is sent),
`batch_size` / `chunk_size` (concurrency and checkpoint granularity), and the gate toggles. Always
`--dry-run` first to see how many speeches a run would bill for, and `probe` to tune the prompt before
spending on a full source.
