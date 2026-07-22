# Debugging a scrape

The engine is built to fail *loudly and recoverably*: one bad page never aborts a run, every problem is
recorded with enough context to diagnose it, and you can fix a recipe and re-run without re-doing work or
losing your place. This is the stop → identify → fix → resume loop.

## What each run leaves behind

Per source, under `data/scraped/<Country>/`:

| Artifact | What it's for |
|----------|---------------|
| `<source_id>.csv` | the speeches that succeeded (the standardized schema) |
| `<source_id>_errors.csv` | **the to-fix list** — one row per failure: `timestamp, url, error` |
| `<source_id>_<timestamp>.log` | the **run log** — START, links harvested, per-error warnings, progress every 25, DONE summary |

And under `data/state/<Country>.json`:

| Field | Meaning |
|-------|---------|
| `seen_urls` | already scraped — never re-fetched (except by `--rescrape`, which re-does the whole source; see below) |
| `failed_urls` | errored or empty — skipped on a normal re-run, re-fetched with `--retry-failed` (or `--rescrape`) |
| `filtered_urls` | fetched, but the recipe's [`keep_if`](recipes.md) judged them not this source's content — a decided rejection, never re-fetched (not even by `--retry-failed`). Loosened the `keep_if`? Delete this list to re-open them. |
| `last_doc_num` | the per-country `doc_id` counter, so ids stay unique across runs |

### What each probe leaves behind

A `probe` (unlike a run) does **not** touch the source CSV/state — but it now keeps a dated
record of what it found, under `data/scraped/<Country>/sample/`:

| Artifact | What it's for |
|----------|---------------|
| `<source_id>_probe_<timestamp>.txt` | **every harvested link**, one per line — the full `--spread` list, or page 1 otherwise. A snapshot of the source's coverage at that moment (the run's `<id>_links.txt`, but for a probe, and never overwritten). |
| `<source_id>_probe_<timestamp>.json` | the **full report** — the listing summary plus each sampled page's per-field results (which selector matched, parsed date, kept?). Audit the extracted structure straight from the file. |

Written automatically on every CLI probe (the path is printed to stderr, so it never
corrupts `--json` stdout). These live under the gitignored data tree, so they accumulate
locally as a history and never clutter the repo. The sampled pages are chosen **evenly
across the harvested list, inclusive of both ends** (not randomly), so `--spread` always
includes the very newest and very oldest — re-probing the same recipe gives the same
sample, which is what makes it a reproducible review check.

The run also prints a summary when it finishes. Watch four numbers:
- **`via_generic_fallback`** — how many pages the recipe's selectors missed and the generic extractor
  rescued. A few is fine (old/archived layouts). A lot means the recipe's selectors are drifting — fix them.
- **`failed_pending_retry`** — how many URLs are waiting for a `--retry-failed` run.
- **`pagination_stopped_early`** — `true` means the harvest was cut short by a **pager problem**, not by
  reaching the end, so the coverage is incomplete *even though the run succeeded*. See below.
- **`filtered_out_this_run`** — pages a [`keep_if`](recipes.md) rejected. A high number is usually correct
  (that is the point of the filter); `filtered_out > 0` with `scraped_this_run == 0` means the `keep_if`
  is wrong, and the run says so.

## The loop

```bash
# 1) run (cap it while debugging)
python -m leaderspeech.text_scraper.run --recipe recipes/<id>.yml --max-pages 2 --limit 20

# 2) identify: read the summary, then the errors file and the log
cat data/scraped/<Country>/<id>_errors.csv
cat data/scraped/<Country>/<id>_*.log

# 3) fix the recipe (selectors? pagination? language?) — see docs/recipes.md

# 4) resume. A normal re-run continues where it stopped (skips done + known-failed).
python -m leaderspeech.text_scraper.run --recipe recipes/<id>.yml

#    After fixing the recipe, re-attempt the URLs that had failed:
python -m leaderspeech.text_scraper.run --recipe recipes/<id>.yml --retry-failed

#    If the bug produced rows that scraped "successfully" as JUNK (a WAF block page served
#    as 200, or a thin/wrong extraction) they are `seen`, so --retry-failed will NOT re-do
#    them. --rescrape re-fetches the WHOLE source from scratch and rewrites its CSV:
python -m leaderspeech.text_scraper.run --recipe recipes/<id>.yml --rescrape
```

### `--rescrape`: re-fetch one source from scratch

`--retry-failed` only re-does `failed` URLs. A row that came back HTTP 200 + non-empty text —
a Cloudflare block page ([#65](recipes.md#block-page-guard)), a thin/wrong extraction — is `seen`,
not `failed`, so it is never re-fetched. `--rescrape` fixes exactly that:

- Ignores `seen`/`failed` for this source (re-fetches **all** harvested links; only `keep_if`
  `filtered` rejections still stand) and **rewrites** `<id>.csv` instead of appending — the old CSV
  is renamed to `<id>.csv.bak` (recoverable), the errors file is cleared.
- Does **not** reset the country's `last_doc_num`: new rows continue the sequence, so the freed old
  ids just leave a harmless gap and nothing collides with the country's **other** sources (their
  CSVs / `seen` / `failed` are untouched — state is per-country, but `--rescrape` only ever clears
  this source's harvested URLs).
- A harvest that returns **0 links** (transient failure) leaves the CSV and state untouched — it
  never wipes good data.

Combine with `--sample N` / `--limit N` to re-do just a slice (e.g. a calibration sample):
`... --rescrape --sample 20`. Then **also clear the cleaned artifacts** for the source before
re-cleaning, so the metadata step doesn't skip the fresh rows as already-done: delete
`data/cleaned/<Country>/<id>.parquet` and its `data/clean_state/` entry (see [cleaning.md](cleaning.md)).

## Reading the errors

| Error in the CSV / log | Likely cause | Fix |
|------------------------|--------------|-----|
| `empty_text (no recipe match; generic also empty)` | `text` selectors don't match this page | inspect the page, update the `text` selector chain; if it's a JS page, set `renderer: js` |
| many `via_generic_fallback` | the site redesigned, or older pages use a different layout | add the new/old selectors to the field's fallback chain |
| `HTTPStatusError: ... 404/500` | dead or moved URL | usually fine to leave failed; for a whole dead source, use the Wayback fallback (`leaderspeech.text_scraper.wayback`) |
| `CERTIFICATE_VERIFY_FAILED` / SSL error | the site's TLS cert chain is broken/incomplete (common on old gov sites) | set `verify_ssl: false` in the recipe |
| `0 links harvested` | listing selector/pattern or pagination is wrong | re-check `listing` and `pagination` against the live page |
| `pagination stopped EARLY` / `next_selector MATCHED an element but clicking it FAILED` | a `click` pager the site has **hidden** with its own JS (Playwright refuses non-visible elements), so only page 1 was harvested | if the pager is a real `<a href>` in the HTML, switch to `pagination: next_link` — it walks the chain over plain HTTP and needs no click (this was Austria: 10 links instead of 1,298) |
| `served N link(s) but NONE were new` | the site ignores the page parameter and re-serves page 1 | open the built page URL in a browser and check the pager really advances; the param name/`start`/`step` are probably wrong |
| `keep_if FILTERED OUT ALL n fetched page(s)` | the `keep_if` selector doesn't exist on these pages (no match = no evidence = drop), or the pattern is wrong | probe the recipe and read the `KEEP_IF` line; check the selector against a page you expect to **keep** |
| `0 links` in **both** `static` and `js` / the page is empty chrome | the speech list loads from a JSON/search API (often SharePoint behind a WAF); the served HTML has no links | capture the JSON endpoint in DevTools → Network → Fetch/XHR and use `pagination.type: api` (see [recipes.md](recipes.md)); the engine now sends browser-like `Accept`/`Accept-Language` headers by default to clear such WAFs |

## Guarantees

- **Per-page isolation.** A failed fetch or extraction is caught, logged, and added to `failed_urls`; the run
  keeps going.
- **Fault-tolerant harvesting.** A broken listing page stops pagination for that start URL and logs it — it
  doesn't kill the crawl.
- **A truncated harvest says so.** Pagination that ends because a pager broke (rather than because the
  archive ran out) logs a warning and sets `pagination_stopped_early` in the summary. A run can otherwise
  finish with zero errors while covering a few recent weeks — that used to be indistinguishable from a
  genuinely short archive. (Tested in `tests/test_paginate.py`.)
- **Fatal errors are visible.** Anything unexpected is logged with a full traceback (`FATAL ...`) and partial
  results are flushed to disk before the error propagates.
- **No silent data loss.** Failures land in `failed_urls` (not `seen`), so a recipe fix + `--retry-failed`
  actually re-scrapes them. (Tested in `tests/test_run.py`.)
