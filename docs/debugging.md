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
| `seen_urls` | already scraped — never re-fetched |
| `failed_urls` | errored or empty — skipped on a normal re-run, re-fetched only with `--retry-failed` |
| `last_doc_num` | the per-country `doc_id` counter, so ids stay unique across runs |

The run also prints a summary when it finishes. Watch two numbers:
- **`via_generic_fallback`** — how many pages the recipe's selectors missed and the generic extractor
  rescued. A few is fine (old/archived layouts). A lot means the recipe's selectors are drifting — fix them.
- **`failed_pending_retry`** — how many URLs are waiting for a `--retry-failed` run.

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
```

## Reading the errors

| Error in the CSV / log | Likely cause | Fix |
|------------------------|--------------|-----|
| `empty_text (no recipe match; generic also empty)` | `text` selectors don't match this page | inspect the page, update the `text` selector chain; if it's a JS page, set `renderer: js` |
| many `via_generic_fallback` | the site redesigned, or older pages use a different layout | add the new/old selectors to the field's fallback chain |
| `HTTPStatusError: ... 404/500` | dead or moved URL | usually fine to leave failed; for a whole dead source, use the Wayback fallback (`leaderspeech.text_scraper.wayback`) |
| `CERTIFICATE_VERIFY_FAILED` / SSL error | the site's TLS cert chain is broken/incomplete (common on old gov sites) | set `verify_ssl: false` in the recipe |
| `0 links harvested` | listing selector/pattern or pagination is wrong | re-check `listing` and `pagination` against the live page |

## Guarantees

- **Per-page isolation.** A failed fetch or extraction is caught, logged, and added to `failed_urls`; the run
  keeps going.
- **Fault-tolerant harvesting.** A broken listing page stops pagination for that start URL and logs it — it
  doesn't kill the crawl.
- **Fatal errors are visible.** Anything unexpected is logged with a full traceback (`FATAL ...`) and partial
  results are flushed to disk before the error propagates.
- **No silent data loss.** Failures land in `failed_urls` (not `seen`), so a recipe fix + `--retry-failed`
  actually re-scrapes them. (Tested in `tests/test_run.py`.)
