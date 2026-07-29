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
4. Describe the source **in the pull request**: country, URL, which leaders and years it covers, and
   the `recipe_status` you believe applies. The maintainer folds that into the source list.
   `data/sources/sources.csv` is **generated** from a local working file, so don't edit it directly.
5. Open a pull request with **only the recipe**. Do not commit scraped output (`data/scraped/` is
   gitignored).

When you describe a source, observations are the useful part: "returns HTTP 403 to the bot
user-agent; the Internet Archive holds 1,200 captures back to 2009" is exactly right.

CI validates every `recipes/*.yml` against the schema, so a malformed recipe fails fast.

## Working an issue with a coding agent

Issues are scoped to one source, so they suit an automated assistant if you use one — point it at
[`docs/recipes.md`](docs/recipes.md) and the issue. However the recipe gets written, a human reviews
and merges the PR, and agent output is a draft until a small live run looks right.

## Style

- Python: keep the engine generic. Site-specific behavior belongs in a recipe, not in `leaderspeech/`.
- Match the surrounding code — it favors small, documented functions over cleverness.
- Be a good citizen: never lower the default request delays, and cap test runs.
