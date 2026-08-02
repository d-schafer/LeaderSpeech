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

# 3) MERGE — concatenate the kept rows (default: leader + minister/foreign speeches) into the dataset.
python -m leaderspeech.clean_structure_metadata.merge          # --keep accepted|speakers|all

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
| `is_substantive` | yes / no / unsure — does it express a position / policy / value on a public matter (**yes**) vs. pure courtesy / protocol / logistics such as a greeting, congratulation, or condolence (**no**)? Recorded, not a gate; feeds `inclusion_tier` (tier `4_courtesy`). |
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
(`exact` / `other_country` / `none`), `is_ceremonial` (from the tenure key), `inclusion_tier`
(see below), and the `clean_status` gate decision.

**`inclusion_tier`** is a convenience label (derived from `document_type` + `is_first_person` +
`is_substantive`) that places every kept row on the strict→broad inclusion spectrum, so a dataset
user can filter by strictness with a single column instead of re-deriving the boolean logic:

| `inclusion_tier` | meaning |
|------------------|---------|
| `1_speech` | a delivered speech or interview — the leader speaking directly |
| `2_first_person_statement` | a substantive official statement in the leader's own words (first person) |
| `3_third_person_statement` | a substantive official statement/communiqué *about* the leader's position (third person: "the president reaffirmed / announced …") |
| `4_courtesy` | kept but **pure courtesy/protocol** (`is_substantive == no`): greetings, congratulations, condolences, thank-yous, bare appointment/schedule notices |

`None` for `document_type` `other`/unknown (i.e. rejected rows). Thresholds: **strict** = tier 1;
**middle** = tiers 1–2; **substantive** = tiers 1–3; **broad** = tiers 1–4 (everything the default
gate keeps). `is_substantive == no` demotes any kept row to tier 4 regardless of type; a missing or
`unsure` substance flag is treated as substantive (never demoted — we don't drop on uncertainty).
This only *labels* rows — the keep gate is unchanged, so a stricter subset stays fully recoverable
downstream. `inclusion_tier` is backfilled for free on `--regate`, but **`is_substantive` itself is a
model judgment**, so tier `4_courtesy` only appears after a fresh clean (a re-clean of existing data),
not from `--regate` alone.

## Date resolution

The final `date` is not the model's estimate nor a raw parse — it is **adjudicated**. A date parsed
straight from the text has no context: an Afghan/Persian **Solar-Hijri (Jalali)** date in the body
(handled by `jalali.py` — zodiac + Iranian month names, Western/Persian digits) is often a *founding
year* ("established in ۱۳۱۳ SH" → 1934), an institutional date, or a stray document date rather than
the delivery date. So each parse is cross-checked against two independent signals before it is
trusted:

- the **Wayback capture date** (`wayback_capture`, stamped on every archived row) — a hard bound: a
  page cannot be archived *before* the speech on it existed; and
- the **model's own read** of the text (`date` + `date_matches_metadata`), fed the resolved
  candidate so its yes/no verdict judges the *real* date.

### The date is settled FIRST, in its own pass

The date must be established **before** the tenure key supplies leader candidates. Otherwise the key
is applied to a bad year and *propagates* error into speaker attribution instead of correcting it — a
2016 Uzbek speech captured in 2024 would be matched against the 2024 roster. So a row with **no
trusted date selector** gets a cheap **date-only call first** (`date_pass_enabled`, ~200 words of the
head, and deliberately **no leader roster** — the roster is chosen *from* its answer). The confirmed
date then picks the roster for the full extraction call. Rows that already carry a selector date skip
the pre-pass entirely, so the common path costs nothing extra.

The pre-pass returns `date`, `date_confidence` (`high`/`medium`/`low` — "read a dateline" vs
"guessed"), and a `date_basis` sentence naming the evidence (logged for review, not stored).

### What the model is shown — and why it used to be wrong

The capture date is **never** rendered as the document's date. It used to be: the resolved date was
written straight into `DATE:`, so for a dateless archived row the model was handed a crawl timestamp
presented as fact and agreed with it **83–99%** of the time. It is now labelled for what it is:

```
DATE: not available
CANDIDATE DATE FROM TEXT (crude pattern match on the first lines -- UNVERIFIED; confirm
  against the text or correct it): 2016-12-05
ARCHIVE CAPTURE DATE: 2024-05-27 -- the date the Internet Archive CRAWLED this page. The
  document was published on or BEFORE it, usually not more than a few years earlier.
  A BOUND, NOT the answer.
```

### Two tiers of trust

**Tier 1 — a recipe's own date selector is authoritative.** It is the site's machine-readable field.
The model still checks it and agreement is expected, but **on disagreement the selector value stays**
and the row is flagged: a systematic mismatch means the *recipe* is broken (this is how a
DD.MM-vs-MM.DD selector misparse surfaces), and silently overwriting would hide the bug. Override per
source with `--date-text-first` when a selector is known bad.

**Tier 2 — everything else is a proposal, and the model outranks all of it.** Order:

1. a **Jalali** date from the text (`day` / `year`) — an exact calendar conversion, kept top;
2. the **selector** date (`scraped`);
3. the **model** (`model`) — beats the regex *and* the capture date, always;
4. the **head-line regex** (`regex_text`);
5. the **capture date** (`wayback_capture`) — an upper bound, marked `date_is_fallback`.

Every candidate must clear the capture bound (nothing can post-date its own archival). The
`date_flag_years` gap check (default **5**) applies to a *Jalali* parse only — a Jalali date is found
anywhere in the body, so one decades from the capture is almost certainly a stray institutional date.
It deliberately does **not** apply to the head-line regex, which is structurally confined to a
dateline: an archived page crawled years after publication is the normal case, not a suspicious one.

**The echo is recorded honestly.** If the model returns exactly the capture date it is telling us it
could do no better, so the row stays `wayback_capture` with `date_is_fallback=True` rather than being
relabelled `model`.

### The head-line date parser (`leaderspeech/datetext.py`)

Recovers a date sitting in plain sight at the top of a generic-extracted body. It accepts a date only
when a whole **head line IS a date** (modulo punctuation, a weekday, or a `Published:` label) and is
short. That strictness is the point: a naive "first date in the first 400 chars" scan was measured
getting the **year wrong 45–64%** of the time, grabbing prose like *"20 January 1990 went down in the
history of modern Azerbaijan…"*. Under the strict rule it recovers **99.1%** of Uzbekistan's dateless
rows with **zero** post-capture violations corpus-wide. Ambiguous `05/12/2016` slashes are refused
outright (`source_language` is a language, not a locale, so DD/MM vs MM/DD cannot be settled). Knobs:
`date_text_enabled`, `date_text_lines`, `date_text_max_line_chars`, `date_text_min_year`,
`date_text_dateparser`, `date_text_first`.

### The audit columns

Every candidate is kept **side by side, win or lose**, so a consumer can re-adjudicate without
re-running anything: `date_scraped` (the site's field), `date_regex_recovered` (the head-line parse —
also written by the *scraper* on every row), `date_model`, `wayback_capture`. Plus `date_precision`
(which won: `day` / `year` / `scraped` / `model` / `regex_text` / `wayback_capture`), `date_parsed`,
`date_confidence`, **`date_is_fallback`** (the date is only the crawl bound — exclude these from
date-sensitive analysis), and **`date_disagreement_flag`** (the candidates conflicted; a human should
look — above all a selector contradicted by the model).

### Backfilling for free — `--redate`

`--redate` recomputes the date on already-cleaned rows from **stored columns with no API calls**, and
is idempotent. It runs *before* the tenure crosscheck, so that is re-keyed on the corrected year too.

It reads **`date_scraped`**, not `date`: `date` in a cleaned Parquet is the *resolved* value, so
feeding it back would re-launder a capture date as a trusted `scraped` date.

It **cannot** re-run the date pre-pass (that needs the API), so rows whose stored `date_model` is
merely the capture date stay `date_is_fallback` — repair those with a `--reclean` under the corrected
prompt.

## Duplicate rows

`python -m leaderspeech.clean_structure_metadata.duplicates --all` writes
`data/_build/duplicate_clusters.csv`, one row per cluster of rows sharing identical text. **It reports
only — nothing is ever deleted or filtered.**

Measured across the scraped corpus: duplicates are always **byte-identical text on different URLs
with different `doc_id`s** — the same URL is never scraped twice (0 cases). **Never dedupe on
`title`**: 93.4% of title-duplicates have genuinely different text (a generic site `<title>` bleeding
in, or a recurring headline like "tender announcement"). Causes reported:

| cause | meaning | what it implies |
|---|---|---|
| `url_variant` | same URL modulo query / scheme / `:80` / `www` | one document — safe to collapse |
| `mirror` | same path, different host (`arkiva.president.al`) | one document — safe to collapse |
| `id_variant` | same article id, different slug/section | one document — safe to collapse |
| `slug_variant` | CMS duplicate slug `-2` / `-4` | one document — safe to collapse |
| `junk_stub` | short placeholder ("under construction") | not a document — drop the cluster |
| `shared_text_suspect` | identical **long** text on unrelated URLs | **not duplication** — an extraction failure |

`shared_text_suspect` is the one that matters: the text does not belong to the URL (107 Belarus
article URLs all carrying the same press-release index; 51 Armenian 2008 URLs all carrying a 2018
page). Keeping one representative would attach the wrong speech to a real URL.

## The gate

`accepted` requires all three: the `document_type` is in `keep_document_types` (default `speech`,
`interview`, `official_statement`); the speaker is non-empty; and — when `require_leader_type` is on —
the speaker is not a `foreign_visitor` / minister / other. Reject statuses:
`rejected_not_representative` (a `document_type` of `other`, i.e. news/biography/agenda/logistics),
`rejected_no_speaker`, `rejected_foreign`, `rejected_non_leader`. Speakers whose type is `unknown` or
a head-of-state/government value pass — we don't drop a real leader just because the role was
uncertain. Both knobs live in `clean_config.yml` (see below).

**`speaker_review` — surfacing a leader the tenure key doesn't know (issue #68).** The tenure key is
curated iteratively, so a genuine leader can be missing (a new administration, a regime change, a
deputy) — which would otherwise make the model classify the real speaker as a non-leader and the gate
drop it, invisibly. To catch that, the extraction prompt no longer treats the injected leader list as
exhaustive ("KNOWN LEADERS IN OFFICE (may be incomplete)" — a genuine leader not on the list is still
classified as a leader), and every row gets an orthogonal boolean **`speaker_review`**: `True` when the
row plausibly represents a national leader (the model typed a head of state/government, or the document
is a first-person substantive statement) **but the tenure crosscheck found nothing** (`tenure_match ==
none`). It is *orthogonal* to accept/reject — an accepted row stays accepted, it just carries the flag —
so nothing is un-accepted or lost. It is derived from stored fields, so `--regate` backfills it for
free. The `leader_tenure` curation tool (`--diagnostic`) then lists these unmatched-but-plausible
speakers per country as tenure-key addition candidates (its per-source read now includes review-flagged
rows, not just `accepted`). The cleaned-index `cleaned_progress_log.xlsx` shows an `n_review` count per
source.

## Configuration reference

Every field is in `configs/clean_config.yml`; override per run with `--config path.yml`, and the
model with `--model`. The two settings that change **what is kept**:

| setting | default | effect |
|---------|---------|--------|
| `keep_document_types` | `[speech, interview, official_statement]` | The `document_type`s that count as representing the leader and are kept. **Remove `official_statement`** to keep only things the leader said aloud (interviews + delivered speeches); anything not listed becomes `rejected_not_representative`. |
| `require_leader_type` | `true` | When `true`, speakers the model marks `foreign_visitor` / `other_minister` / `other` are set aside (`rejected_foreign` / `rejected_non_leader`). **Set `false`** to keep every representative document regardless of the speaker's role. |

Other settings: `model` (default `gpt-4.1-mini`), `temperature`, `max_tokens`, `max_words` (how much
text is sent), `batch_size` / `chunk_size` (concurrency + checkpoint granularity),
`max_consecutive_failures` (circuit breaker), `tenure_file` / `tenure_window`, `date_flag_years`
(default `5` — max Jalali-parse-vs-capture year gap before a text date is flagged/adjudicated; lower =
stricter; override per run with `--date-flag-years N`; see **Date resolution** above), `compression`
(`zstd` | `snappy`), `openai_key_file`.

Date-specific knobs (all under **Date resolution** above):

| setting | default | effect |
|---|---|---|
| `date_pass_enabled` | `true` | Run the cheap **date-only pre-pass** on rows with no site date, so the date is settled before the tenure key names candidate leaders. Turn off to revert to a single call per row. |
| `date_pass_max_words` | `200` | How much of the head is sent to the pre-pass (the dateline lives there). |
| `date_text_enabled` | `true` | Use the head-line date parser to supply a candidate. |
| `date_text_lines` | `4` | Leading non-empty lines considered. |
| `date_text_max_line_chars` | `60` | A date *line* is short; longer means prose and is ignored. |
| `date_text_min_year` | `1990` | Hard floor. Not redundant with the capture check — ~30 wayback CSVs have no `wayback_capture` column, so that check no-ops for them. |
| `date_text_dateparser` | `true` | Tier 2: non-English month names ("12 Janar 2006") via `dateparser`. |
| `date_text_first` | `false` | Let the head-line date outrank the recipe's **own** date selector. Only for sources whose selector is known bad. `--date-text-first`. |

**Changed the gate after a run?** Re-classify already-cleaned rows for **free** (no API calls) — the
gate reads the stored `document_type` / `speaker` / `speaker_type`:

```bash
python -m leaderspeech.clean_structure_metadata.run --source chl_presidencia --regate
python -m leaderspeech.clean_structure_metadata.run --all --regate
```

`--regate` rewrites `clean_status` in place from the stored fields (error rows untouched), so you can
tune `keep_document_types` / `require_leader_type` without re-spending or losing anything. It also
re-runs the **tenure crosscheck** deterministically (from the stored `speaker`/`country`/`date`, no API
calls) and backfills `speaker_review` — so a curated tenure key or a tightened matcher lands on
already-cleaned data for free (e.g. after adding a missing leader, `--regate` alone re-accepts their
speeches; only a *model* mis-type needs a paid `--reclean`). If the key file is missing, the stored
crosscheck is left untouched. (Plain `--retry-failed` only re-attempts rows that *errored*.)

**Changed a `date_text_*` setting?** `--redate` does the same for dates — free, no API calls, and it
implies `--regate`:

```bash
python -m leaderspeech.clean_structure_metadata.run --all --redate
```

See **Backfilling for free — `--redate`** above for what it can and cannot repair.

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
  (deduped by `doc_id`). **`--keep` selects which rows go in** — default `speakers` = leader speeches
  PLUS minister/foreign-visitor speeches (`rejected_non_leader` / `rejected_foreign`), `accepted` =
  leader-only (the old behavior), `all` = everything except errors. Rejected rows are RETAINED
  per-source regardless. Every deliverable row carries `clean_status` / `speaker_type` /
  `is_ceremonial` / `is_substantive` / `inclusion_tier`, so a user can filter to any stricter subset
  (leader-only, substantive-only, executive-only). The R export applies `key_fixNames.R` and writes
  the final `data/LeaderSpeech.parquet` / `.RData` / `.csv.gz`, all name-consistent. All derived and
  regenerable — re-run merge + export anytime; it costs nothing.

## Cleaned columns

The 15 standardized scraper columns (unchanged, for mergeability) plus: corrected-in-place
`speaker` / `position` / `date`; audit copies `speaker_scraped` / `date_scraped`; the extracted
`speaker_type`, `audience`, `speech_type`, `venue`, `detected_language`,
`speaker_attributed_correct`, `date_matches_metadata`; the date-audit set `date_precision`,
`date_model`, `date_parsed`, `date_disagreement_flag` (see **Date resolution** above); the crosscheck
`tenure_match`, `tenure_matched_name`, `is_ceremonial`; and `clean_status`, `gate_reason`,
`clean_confidence`, `clean_reasoning`, `clean_model`, `cleaned_at`. The final deliverable keeps the
scraper schema plus a curated metadata subset.

## Cost & tuning

Cost is roughly one `max_tokens`-bounded call per *new* speech, on the cheap default model
(`gpt-4.1-mini`). Knobs in `configs/clean_config.yml`: `model`, `max_words` (how much text is sent),
`batch_size` / `chunk_size` (concurrency and checkpoint granularity), and the gate toggles. Always
`--dry-run` first to see how many speeches a run would bill for, and `probe` to tune the prompt before
spending on a full source.
