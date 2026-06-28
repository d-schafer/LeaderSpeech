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
leaderspeech/text_scraper/   the engine (recipe, fetch, paginate, extract, run, wayback, fallback_generic)
recipes/                     one YAML per source
data/sources/                master_sources.xlsx — the curated, citable source list (committed)
data/scraped/                per-country CSV output (gitignored; shared via Zenodo/Dataverse)
R/                           final combine of cleaned per-country corpora -> LeaderSpeech.RData
docs/recipes.md              how to author a recipe
tests/                       schema + extraction tests
```

The pipeline is Python through scraping and cleaning, with a single handoff to R at the end:
R combines the cleaned per-country corpora, standardizes names, validates speakers against the leader-tenure
key, and writes the compressed `data/LeaderSpeech.RData`.

## Roadmap

- [x] `text_scraper` — config-driven engine + first recipes
- [ ] `clean_structure_metadata` — translation, then metadata extraction (speaker, date, venue, audience)
- [ ] more sources — Latin America and Africa especially
- [ ] `video_audio_scraper` — yt-dlp + Whisper, same output schema

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
