# Recipe backlog & how to scale

The engine is done; coverage grows one recipe at a time. There are ~100 sources in
`data/sources/master_sources.xlsx` with `recipe_status: none`. This note explains how to work
through them efficiently — by hand, with subagents, or with coding agents on GitHub issues.

## The unit of work

One source → one recipe in `recipes/` → record its status by adding a per-source file
`additional_master_sources/<source_id>.csv` (the agent "outbox"; one file per source so PRs never conflict —
**never edit the legacy flat file or `master_sources.xlsx`** — see `agent_task_end_to_end.md`). That's it.
Each is small, independent, and reviewable, which is exactly why it parallelizes well.

## Deferred sources (don't re-attempt without the prerequisite)

Some sources were investigated and parked — tracked by GitHub issues labeled **`deferred`**. Don't burn
agent cycles re-attempting these as plain recipes; they need a prerequisite first:

- **Colombia — Presidencia discursos** (issue #7): ~~deferred~~ **UNBLOCKED** — recipe
  [`col_presidencia.yml`](../recipes/col_presidencia.yml) authored and probe-validated; pending a FULL RUN.
  The engine gained a JSON/search-API source type (`pagination.type: api`) and an RSS/Atom sibling
  (`type: feed`) plus browser-like default headers. *Colombia turned out not to be a GET search API* —
  it's a SharePoint CSWP that renders client-side via CSOM `ProcessQuery` (POST), and its WAF **blocks the
  honest bot User-Agent entirely** (0 links). The fix that unblocked it: the new per-recipe `user_agent:`
  override (browser UA) + `renderer: js` + the CSWP `click` pager. The `api`/`feed` types remain for the
  many other SharePoint sites that *do* expose a GET `_api/search/query`, and for feed-based sources.
- **Chile — Bachelet 2014–2018 Wayback** (issue #4): the Internet Archive holds no fetchable Bachelet-era
  `discurso.aspx` captures (they 404; only 2018+ Piñera is archived, already in the live recipe). *Needs:* a
  different archived source for that era (e.g. the slug-based `2010-2014.gob.cl` legacy site for Piñera I).

## Three ways to generate recipes

1. **By hand.** Follow [`recipes.md`](recipes.md): inspect the site, write the YAML, do a capped live run.
   Best for awkward sites (JS, no semantic containers, login walls).

2. **Local subagents (recommended for batches).** Point a cheaper model (e.g. Claude Sonnet) at a source
   URL with `docs/recipes.md` and ask it to (a) inspect the site and (b) return a draft recipe + a
   `master_sources` row. Then validate each draft yourself with a small live run:
   ```bash
   python -m leaderspeech.text_scraper.run --recipe recipes/<id>.yml --max-pages 1 --limit 5
   ```
   Inspection is the repetitive, token-heavy part — delegating it keeps the cost down. Validation (running
   the engine) is cheap and is the real check.

3. **Coding agents on GitHub issues.** File one issue per source with the "New source recipe" template,
   then hand it to an agent that opens a PR:
   See **[`agents.md`](agents.md)** for the explicit, step-by-step version (opening issues, assigning to
   Claude / Codex / Copilot, the review→merge flow). A human reviews and merges; CI validates every PR.

However the recipe is drafted, the small live run is the gate. Treat agent/subagent output as a draft.

## Do we need a recipe per site, or do "types" help?

Mostly one recipe per site — but it gets easier fast, for three reasons:

- **Sites cluster into structure families.** Many presidencies run the same CMS (the Latin-American
  `gob.*`/presidencia template, WordPress, Drupal, Plone). Once you have a recipe for one, the next is
  usually clone-and-tweak-the-selectors, not from scratch. `recipes/arg_casarosada.yml` is a good template
  for other Spanish query-param presidencies; `recipes/fra_elysee.yml` for server-rendered EU sites.
- **The generic fallback covers the long tail.** Where no recipe is tuned, `extract_generic` (trafilatura)
  still pulls a usable title/text/date — and the engine now uses it automatically when a recipe's selectors
  come up empty (so it also absorbs a site quietly redesigning out from under a recipe).
- **The recipe is just data.** A recipe is a few lines of YAML, so "a recipe per site" is cheap, and the
  fallback chains let one recipe tolerate several layouts.

So: not one recipe to rule them all, but recognizing the ~handful of structure types lets you cover the 88+
quickly by templating.

## Suggested order

1. **`president.ie`** — Drupal-style, no clean title/date containers; needs a careful recipe (good agent task).
2. **Latin America.** Casa Rosada, gob.mx, and Élysée are done; the same static/query-param pattern likely
   covers Chile, Colombia, Uruguay, Costa Rica with light edits. High value, low effort.
3. **Africa.** Work the African domains already in `master_sources.xlsx` (from the RA list), then expand.
   This is the thinnest continent in the data, so it's a priority.
4. **The rest of the 88.** Triage with `fallback_generic.extract_generic` first to gauge difficulty.

## Filing issues

Two paths, both intentionally **not** run automatically (review first; `gh` must be authenticated against
`d-schafer/LeaderSpeech`):

- **A hand-picked first batch:** `scripts/create_issues.sh` (a few specific sources).
- **Batches straight from the source list (the scalable path):** `scripts/create_issues_from_master.py`
  reads `master_sources.xlsx`, takes every row with `recipe_status: none`, and files one issue each —
  filterable and capped, so you work the ~100 sources a batch at a time:
  ```bash
  python scripts/create_issues_from_master.py --limit 10 --dry-run     # preview
  python scripts/create_issues_from_master.py --region Africa --limit 15
  ```
