# LeaderSpeech

Tools for scraping, transcribing, cleaning, and structuring speeches by political leaders — and,
in time, a published dataset of those speeches with wide geographic and chronological coverage.

National leaders' speeches live behind dozens of incompatible website designs: a presidential press
office in one country paginates with `?start=40`, another renders everything in JavaScript, a third
went offline three years ago and survives only on the Wayback Machine. Writing a fresh scraper for
each one does not scale. **`text_scraper` separates the engine from the site.** The engine — fetching,
pagination, extraction, date parsing, politeness, resumability — is written once. Each site is described
by a small **recipe** (a YAML file): where its listing pages are, how it paginates, and which CSS
selectors pull the title, text, date, and speaker. Adding a source is writing a recipe, not new code.

This is the first tool in a larger project; see [`README_goal.txt`](README_goal.txt) for the full scope
(a video/audio scraper with Whisper transcription, an LLM metadata-cleaning step, deduplication, and the
merged dataset). The scope of *this* repository is deliberately narrow: scraping, wrangling, and
structuring leader speeches.

## Install

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium                 # only needed for JavaScript ("js") sites
```

## Quickstart

```bash
# Scrape a single source from its recipe. Start small: cap pages and speeches.
python -m leaderspeech.text_scraper.run \
    --recipe recipes/arg_casarosada.yml \
    --max-pages 2 --limit 10
```

Output is written to `data/scraped/<Country>/<source_id>.csv`, one row per speech in the standardized
schema below. A per-country state file under `data/state/` records which URLs have been seen and the last
`doc_id` number used, so re-running the same recipe **continues where it left off** rather than starting
over or double-counting. Each run also drops a timestamped log and an errors file next to the CSV — see
[`docs/debugging.md`](docs/debugging.md) for the stop → fix → `--retry-failed` workflow.

## The recipe

A recipe is the entire answer to "how do we handle so many different sites." All per-site variation lives
here as data. The essentials:

```yaml
source_id: arg_casarosada        # short slug; links recipe <-> output files
country: Argentina
source_language: Spanish         # English goes in `text`; anything else in `text_originlanguage`
start_urls:
  - https://www.casarosada.gob.ar/informacion/discursos
renderer: static                 # "static" (httpx) or "js" (Playwright)

listing:                         # how to find speech links on a listing page
  link_selector: "a.panel"
  link_pattern: "/discursos/\\d+"

pagination:                      # query_param | path | click | url_list | none
  type: query_param
  param: start
  start: 0
  step: 40

# each field is an ORDERED fallback chain — the first selector that matches wins
title: { selectors: ["h1.titulo", "h1", "title"] }
text:  { selectors: ["div.body", "article"] }
date:  { selectors: ["span.fecha", ".date"] }
speaker: { selectors: ["span.orador"] }

date_languages: ["es"]           # hints for multilingual date parsing
position: president              # fixed value when a source is single-office
```

The full field reference and a worked example are in [`docs/recipes.md`](docs/recipes.md).

## Output schema

Every recipe produces rows in one common schema (shared with the wider project's
`02-combine_and_standardize_data.R`):

`doc_id, country, ISO3N, speaker, position, context, title, text, date, source, source_language, dataset`
— plus `context_originlanguage`, `title_originlanguage`, `text_originlanguage`.

- **`doc_id`** — the per-speech unique key, critical for downstream NLP: an ISO-3 country code plus a
  zero-padded counter (`ARG0001`, `TUR0042`). The counter is per country and continues across runs and
  across sources, so ids never collide.
- **`source`** — the exact page each speech was scraped from, not the site's root.
- **English vs. original language** — unsuffixed `title`/`text`/`context` always hold English. For a
  non-English source the scraped text fills `*_originlanguage`, and the English columns are left for the
  translation step (project priority 2). `dataset` is `LeaderSpeech` for everything scraped here.

## Cleaning & structuring metadata

Scraped speeches are often messy: the speaker column is blank, the "speech" is sometimes a press
release, the date can be wrong. The second tool, **`clean_structure_metadata`**, reads the scraper's
CSVs and uses one cheap GPT structured-extraction pass per speech to confirm the speaker, classify the
`document_type` (delivered speech / interview / official statement / not-representative), and add
`speaker_type`, `position`, `audience`, `speech_type`, `venue`, `language`, and a corrected `date` —
cross-checked against the authoritative leader-tenure key. A hard gate enforces the project rule that
**every kept row has a speaker and represents the leader** — a speech, interview, or an official
statement that conveys the leader's position (even a third-person communiqué); pure news/logistics is
set aside (audited, not deleted).

```bash
pip install -e ".[llm]"          # adds the openai client
# preview on a random sample across every scraped country (no writes, cheap)
python -m leaderspeech.clean_structure_metadata.probe --all-countries --n 5
# clean one source (resumable; only NEW speeches hit the model)
python -m leaderspeech.clean_structure_metadata.run --source chl_presidencia --limit 20
# merge the per-source cleaned Parquets, then finalize names + deliverable formats in R
python -m leaderspeech.clean_structure_metadata.merge
Rscript scripts/export_leaderspeech.R
```

Cleaned data is stored as **Parquet** (`data/cleaned/<Country>/<id>.parquet`) — compact, UTF-8-exact, and
loadable from both Python and R. Re-running only cleans speeches not already done, so the model is never
paid twice. The full workflow, schema, and safety guarantees are in [`docs/cleaning.md`](docs/cleaning.md).

## Translation

The cleaner reads each speech in its original language; the **`translate`** tool fills the English
`text` / `title` / `context` columns from their `*_originlanguage` counterparts — **in place**, so there
are no extra dataframe versions and `merge` needs no rewiring. Pick a backend to test and compare:
**Google** (`deep-translator`, online, the default), **OpusMT** (Helsinki-NLP), or **NLLB** (offline).

```bash
pip install -e ".[translate-google]"     # Google backend; or ".[translate-hf]" for OpusMT/NLLB
# compare backends on a sample (no writes)
python -m leaderspeech.translate.probe --source arg_casarosada --translator google,nllb
# fill English columns in place (resumable; only untranslated rows are touched)
python -m leaderspeech.translate.run --source arg_casarosada --limit 20
# ...or any table at any stage (raw scraped CSV, the merged build)
python -m leaderspeech.translate.run --input data/scraped/Chile/chl_presidencia.csv
```

Progress is visible in the derived index (`data/cleaned/cleaned_progress_log.xlsx` → `is_translated`),
computed from the data rather than a stored flag. Details: [`docs/translation.md`](docs/translation.md).

## Curating the leader-tenure key

The cleaner cross-checks each speaker against `leader_tenure_final.csv` but never edits it. The
**`leader_tenure`** tool closes that loop: it inventories the speakers in the cleaned data, finds those
not matched to a known leader, classifies and GPT-verifies the genuine heads of state/government, and
**proposes** them to an outbox (`data/sources/leader_tenure_proposed_additions.xlsx`) for the researcher
to approve by hand. The key stays 100% accurate — only a separate, gated `merge --apply` step appends
approved rows (with a backup) and prints the `fixNames` lines to add.

```bash
python -m leaderspeech.leader_tenure.run --diagnostic         # free: just bucket matched/unmatched
python -m leaderspeech.leader_tenure.run --limit 50           # classify + verify a batch (GPT)
python -m leaderspeech.leader_tenure.merge --dry-run          # preview additions; --apply to write
```

Verification uses `gpt-4.1` by default (strong world knowledge), with an optional `--wikipedia` grounding
check. Details: [`docs/leader_tenure.md`](docs/leader_tenure.md).

## Video & audio transcription

Many leaders' words exist only as video — a YouTube channel, a ministry's media page. The
**`video_audio_scraper`** grabs the **audio only** (the video is never kept) with `yt-dlp` and transcribes
it with **Whisper**, landing the result in the *same* schema, per-country `doc_id`, state, and progress
index as the text scraper — so the cleaner/translator/merge treat audio-sourced speeches identically.

Unlike the text scraper it is **not recipe-first**: `yt-dlp` already handles each site's structure, so the
interface is just a playlist/channel link plus the country. No YAML to author.

```bash
pip install -e ".[audio]"        # yt-dlp + faster-whisper (default backend); needs ffmpeg on PATH
# 1. see what a source yields — harvest the links + a summary (no download/transcription)
python -m leaderspeech.video_audio_scraper.harvest --url "<playlist-url>" --country Italy
# 2. download audio + transcribe (prompts to confirm; --yes to skip). --save-recipe makes re-runs 1 command
python -m leaderspeech.video_audio_scraper.run --url "<playlist-url>" --country Italy \
    --speaker "Giuseppe Conte" --language Italian --limit 5 --delete-audio --save-recipe
# re-run later to pick up only new uploads
python -m leaderspeech.video_audio_scraper.run --recipe recipes_audio/<id>.yml --update
```

Transcripts go to `data/scraped/<Country>/<id>.csv` (standard schema), with rich provenance in a
`<id>_media.csv` sidecar (source URL, channel, duration, backend/model, audio status). Audio files land in
`data/audio_video/<Country>/` and are **kept by default** (copy them to an external drive if you like) or
removed per run with `--delete-audio`. The transcriber is pluggable — **faster-whisper** (default, fast,
no `torch`), **openai-whisper**, or the paid **OpenAI hosted API**. Details:
[`docs/audio_transcription.md`](docs/audio_transcription.md) and
[`recipes_audio/README.md`](recipes_audio/README.md).

## Being a good citizen

This is an academic, public-interest project: it collects speeches that leaders themselves published on
public websites, in the service of transparency and accountability. So the stance is **considerate within
reason**, not slavish. The engine identifies itself in the User-Agent and retries with exponential backoff
rather than hammering a struggling server, but by default it does **not** insert a delay before every
request — these are small requests — it just takes a short breather every 50 (`pause_every` / `pause_seconds`,
tunable per recipe). `robots.txt` is **not** enforced by default; pass `--respect-robots` to honor it, or
raise the pacing knobs for a touchy host. The Internet Archive is more fragile than a government CDN, so
`wayback.py` keeps its own gentle delays — leave those alone.

## Repository layout

```
leaderspeech/text_scraper/             the scraper engine (recipe, fetch, paginate, extract, run, wayback)
leaderspeech/clean_structure_metadata/ the cleaner (config, extract, tenure, gate, store, pipeline, merge)
leaderspeech/translate/                the translator (backends, store, pipeline, run, probe)
leaderspeech/leader_tenure/            the tenure-key curation loop (inventory, classify, verify, run, merge)
leaderspeech/video_audio_scraper/      audio scraper + Whisper transcription (recipe, harvest, download, transcribe, run)
recipes/                     one YAML per text source
recipes_audio/               optional, auto-generated per audio source (see its README)
configs/clean_config.yml     global config for the cleaner (model, gate, tenure path)
configs/translate_config.yml global config for the translator (backend, fields, pacing)
configs/tenure_config.yml    global config for tenure curation (models, paths)
configs/audio_config.yml     global config for transcription (backend, model, retention, pacing)
data/sources/                master_sources.xlsx — curated source list, researcher-owned (committed; agents never edit it)
                             additional_master_sources.xlsx — agents' proposed rows; researcher folds these in by hand
                             leader_tenure_proposed_additions.xlsx — the tenure tool's outbox; researcher approves by hand
data/scraped/                per-country CSV output (gitignored; shared via Zenodo/Dataverse)
data/cleaned/                per-country cleaned Parquet (gitignored)
scripts/key_fixNames.R       authoritative speaker-name standardization key (synced from the research workspace)
scripts/export_leaderspeech.R  final merge -> fixNames -> LeaderSpeech.parquet/.RData/.csv.gz
docs/recipes.md              how to author a recipe
docs/cleaning.md             how the metadata cleaner works
docs/translation.md          how the translator works
docs/leader_tenure.md        how the tenure-key curation loop works
docs/audio_transcription.md  how the video/audio scraper + transcriber works
tests/                       schema + extraction tests
```

The pipeline is Python through scraping and cleaning, with a single handoff to R at the end:
the Python merge step concatenates the cleaned per-country Parquets into an intermediate file, then
`scripts/export_leaderspeech.R` standardizes leader names with the `key_fixNames.R` key and writes the
final `data/LeaderSpeech.parquet` / `.RData` / `.csv.gz`.

## Roadmap

- [x] `text_scraper` — config-driven engine + first recipes
- [x] `clean_structure_metadata` — GPT metadata extraction (speaker, date, venue, audience) + tenure crosscheck + name standardization
- [x] `translate` — fill English `text`/`title`/`context` in place (Google / OpusMT / NLLB backends)
- [x] `leader_tenure` — curation loop that proposes additions to the tenure key for hand approval
- [x] `video_audio_scraper` — yt-dlp + Whisper transcription, same output schema (faster-whisper / openai-whisper / OpenAI API)
- [ ] more sources — Latin America and Africa especially

## Contributing

The most useful contribution is a new, validated recipe. See [`CONTRIBUTING.md`](CONTRIBUTING.md). Issues
are scoped so they can be picked up one source at a time — including by coding agents (Claude, Codex,
Copilot) that open a pull request for you to review. The backlog of ~100 sources and how to work it is in
[`docs/backlog.md`](docs/backlog.md); the step-by-step for tasking agents is in
[`docs/agents.md`](docs/agents.md); and the cheap-agent → frontier-reviewer pipeline (with the gates the
researcher keeps) is in [`docs/review_workflow.md`](docs/review_workflow.md).

## License & citation

MIT (see [`LICENSE`](LICENSE)). The dataset itself will be released separately (Zenodo or Harvard
Dataverse) with its own citation; external corpora merged into it are credited there. A `CITATION.cff`
will accompany the first public release.
