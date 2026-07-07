# Contributing

Thanks for helping extend LeaderSpeech. The single most valuable contribution is a **new, validated
recipe** that adds a source — but bug fixes and engine improvements are welcome too.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium                 # only for "js" sites
pytest                                                # should pass before you start
```

## Adding a source (the common case)

1. Read [`docs/recipes.md`](docs/recipes.md) and inspect the site.
2. Add `recipes/<source_id>.yml`.
3. Validate and do a small live run:
   ```bash
   python -m leaderspeech.text_scraper.run --recipe recipes/<source_id>.yml --max-pages 1 --limit 5
   ```
4. Record the source in the `data/sources/additional_master_sources.csv` **outbox** (its `source_id` and the
   `recipe_status` you believe applies). **Do not edit `master_sources.xlsx`** — it is researcher-owned; the
   maintainer (or Claude) folds your row in and sets `recipe_status: validated` when the PR merges.
5. Open a pull request. Do **not** commit scraped output (`data/scraped/` is gitignored) — only the
   recipe and, if you added one, the `additional_master_sources.csv` outbox row.

CI validates every `recipes/*.yml` against the schema, so a malformed recipe fails fast.

## Working an issue with a coding agent

Issues are scoped to one source so they can be handed to an automated agent. **Step-by-step instructions
(opening issues, assigning to each agent, the review flow) are in [`docs/agents.md`](docs/agents.md);** the
backlog strategy is in [`docs/backlog.md`](docs/backlog.md). In brief:

- **GitHub Copilot coding agent** — assign the issue to Copilot in the GitHub UI; it opens a PR.
- **Claude** — mention `@claude` in an issue or PR comment; the workflow in
  `.github/workflows/claude.yml` runs it (needs an `ANTHROPIC_API_KEY` repository secret).
- **Codex / others** — point the agent at the issue and `docs/recipes.md`.

However the recipe gets written, a human reviews and merges the PR. Treat agent output as a draft until the
small live run looks right.

## Style

- Python: keep the engine generic. Site-specific behavior belongs in a recipe, not in `leaderspeech/`.
- Match the surrounding code — it favors small, documented functions over cleverness.
- Be a good citizen: never lower the default request delays, and cap test runs.
