# End-to-end task: add and validate one source

This is the runbook for taking a single source from "nothing" to "validated recipe, full history scraped."
It is written to be followed autonomously by a coding agent (or a person). Each step has an explicit command
and an explicit check. Do not skip the checks.

## Goal

For one source: write a recipe, prove it with the probe, scrape its full available history, debug anything
that breaks, and open a PR. **One source = one recipe = one PR.**

## Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .[dev]
python -m playwright install chromium                  # only if the recipe needs renderer: js
pytest -q                                              # must be green before you start
```

## Steps

**1. Write the recipe.** Inspect the site per [`recipes.md`](recipes.md); create `recipes/<source_id>.yml`.

**2. Probe it (the fast loop — no full crawl).**
```bash
python -m leaderspeech.text_scraper.probe --recipe recipes/<source_id>.yml
```
Check: `LISTING ✓` with a non-zero link count, and `title` / `text` / `date` each show `✓` with a sensible
preview. If a field shows `✗ NO MATCH`, fix that selector and re-probe. If `text` is 0 chars but the probe
says generic would recover N chars, your `text` selector is wrong — fix it (don't rely on the fallback).
Iterate here until green. This is much cheaper than running.

**3. Capped trial run.**
```bash
python -m leaderspeech.text_scraper.run --recipe recipes/<source_id>.yml --max-pages 2 --limit 20
```
Check the printed summary: `failed_this_run` should be ~0, `via_generic_fallback` low, `aborted_early` false.
Open `data/scraped/<Country>/<source_id>.csv` and confirm `title`/`text`/`date` are populated and clean.

**4. Debug anything that broke.** Read `data/scraped/<Country>/<source_id>_errors.csv` and the
`<source_id>_<timestamp>.log`. Diagnose with the error→cause table in [`debugging.md`](debugging.md), fix the
recipe, then re-attempt just the failures:
```bash
python -m leaderspeech.text_scraper.run --recipe recipes/<source_id>.yml --retry-failed
```

**5. Full history.**
```bash
python -m leaderspeech.text_scraper.run --recipe recipes/<source_id>.yml
```
This runs until the site's listing is exhausted. Watch the summary and log:
- If `aborted_early` is true, the circuit breaker tripped (≥25 consecutive failures — likely blocked or the
  recipe/site broke). Diagnose, fix, and resume (`--retry-failed` for the recorded failures).
- If `via_generic_fallback` is high, the recipe's selectors are drifting across the site's history (older
  pages, different layout) — add the older selectors to the field's fallback chain and `--retry-failed`.
- A `HIGH FAILURE RATE` warning means something is systematically wrong — stop and fix, don't push through.
- **Check the date coverage**, not just the error counts. A run can finish with zero errors yet only cover
  a few recent weeks because the listing's pagination silently stopped (some sites ignore `?page=`). Compare
  the output's earliest date to what you expect (when the leader took office, or the site's oldest content).
  If it's far too shallow, the source almost certainly has a **sitemap** — switch to
  `pagination.type: sitemap` (see `recipes.md`). This is exactly how the France recipe went from ~100 recent
  items to its full ~4,700-article history.

**6. Record it.** Set this source's row in `data/sources/master_sources.xlsx` to `recipe_status: validated`
(fill `renderer`, `language`, `date_start`/`date_end`, `last_checked`).

**7. Open a PR.** Commit only the recipe and the `master_sources` change. **Never commit `data/scraped/`.**

## Definition of done

- [ ] `probe` shows a non-zero listing and `✓` for `title`, `text`, `date`
- [ ] capped run: `failed_this_run` ≈ 0, `via_generic_fallback` low
- [ ] full run finishes with `aborted_early: false` (or the abort is understood and resolved)
- [ ] **date coverage looks complete** — the earliest scraped date roughly matches the expected history
      (not just the last few weeks); if shallow, switch to a sitemap
- [ ] a few rows spot-checked: the speaker/date are plausible for that country (cross-check the
      `leader_tenure_final` key)
- [ ] `master_sources.xlsx` row set to `validated`
- [ ] PR opened, CI green, no scraped data committed

## If you get stuck

Everything you need to diagnose is on disk: the run **log**, the **errors CSV**, and the **state file**
(`data/state/<Country>.json`). Report what you tried, paste the relevant log/error lines, and which step's
check failed. Do not silently lower the bar (e.g. accept a 40% failure rate) — surface it.
