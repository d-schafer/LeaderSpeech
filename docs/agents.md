# Tasking coding agents with recipe issues

This is the explicit how-to for the workflow that `backlog.md` describes at a high level: turn the
un-recipe'd sources in `master_sources.xlsx` into GitHub issues, then have a coding agent (Claude, OpenAI
Codex, or GitHub Copilot) work each one and open a pull request you review.

The exact button names in each product change over time — when in doubt, follow the linked official docs.

## Step 1 — Open issues

**One source = one issue = one recipe.** Two ways:

**Browser:** repo → Issues → New issue → pick the "New source recipe" template, fill it in.

**Command line (`gh`):**
```bash
gh auth login                      # once
gh issue create --repo d-schafer/LeaderSpeech \
  --title "[recipe] Chile — Presidencia" \
  --label recipe \
  --body "Author a recipe for <url>. See docs/recipes.md."
```

**In batches from the source list (the scalable way):**
```bash
# preview, don't create:
python scripts/create_issues_from_master.py --limit 10 --dry-run
# create issues for the first 15 African sources still lacking a recipe:
python scripts/create_issues_from_master.py --region Africa --limit 15
```
This reads `data/sources/master_sources.xlsx`, takes the rows with `recipe_status: none`, and files one
issue each (filtered by `--region` / `--country`, capped by `--limit`). Work the backlog a batch at a time.
(The `recipe` label must already exist in the repo, or pass `--label ""`.)

## Step 2 — Assign the issue to an agent

You can mix and match — different issues to different agents.

### Claude (via the GitHub Action in this repo)
1. One-time setup: add a repository secret `ANTHROPIC_API_KEY`
   (Settings → Secrets and variables → Actions → New repository secret). The easiest way to wire this up is
   the Claude Code CLI command `/install-github-app`, which installs the app and adds the workflow + secret
   for you. The workflow is already at `.github/workflows/claude.yml`.
2. Comment on the issue: `@claude please write a recipe for this source — see docs/recipes.md`.
3. The Action runs Claude Code, which pushes a branch and opens a PR. Iterate by replying `@claude ...` on
   the PR. Uses Anthropic API credits.
   Docs: https://docs.anthropic.com/en/docs/claude-code/github-actions

### OpenAI Codex
- From the Codex interface (chatgpt.com → Codex): connect the GitHub repo, pick the issue or describe the
  task ("write recipes/<id>.yml per docs/recipes.md"), and let it open a PR.
- Or, if the Codex GitHub app is installed on the repo, mention `@codex` on the issue.
- Requires a ChatGPT plan with Codex access. Docs: https://platform.openai.com/docs/codex

### GitHub Copilot coding agent
1. Requires a Copilot plan with the coding agent enabled.
2. On the issue, set **Assignees → Copilot** (it appears when enabled), or start it from the Agents panel on
   github.com / in VS Code.
3. It opens a draft PR; review and steer with PR comments.
   Docs: https://docs.github.com/en/copilot/using-github-copilot/coding-agent

## Step 3 — Review and merge

Every agent produces a **pull request**, never a direct push to `main`. On each PR:
- CI validates the recipe against the schema (`.github/workflows/ci.yml`).
- You do the real check — a capped live run and a glance at the output (see `docs/recipes.md`).
- Merge when it looks right; otherwise comment and let the agent revise.

Treat agent output as a **draft**. The small live run is the gate, not the agent's confidence.

## Reviewing an agent's PR locally (pull & check the branch)

The agent's work lives on its own **branch** (e.g. `copilot/add-chile-presidencia-recipe`). To run the probe
against it you need that branch's files on your machine. The probe is read-only and writes nothing to git, so
checking out a branch and probing it is completely safe.

**With GitHub Desktop (no command line):**
1. Click **Fetch origin** (top bar) to pull down the latest, including the agent's branch.
2. Click the **Current Branch** dropdown → **Pull Requests** tab → click the agent's PR. Desktop checks out
   that branch (your working folder now shows the agent's files).
3. If the PR is behind `main` (e.g. it needs a new engine feature): **Branch** menu → **Update from main**.
   This merges `main` into the branch. (A good agent does this itself — check its commit list.)
4. **Repository** menu → **Open in Command Prompt** (or Terminal) → run the probe / a capped run on the recipe.
5. When you're done reviewing: if it's good, merge the PR in the browser ("Merge pull request"); then in
   Desktop switch **Current Branch → main** to get back to your normal state.

**With the command line** (equivalent):
```bash
git fetch origin
git checkout copilot/add-chile-presidencia-recipe   # the PR's branch name (shown on the PR page)
git merge origin/main                               # only if the branch is behind main
# ...run the probe / a capped run here...
git checkout main                                   # return to main when finished
```

**In the browser** you can *read* the changed files on the PR's "Files changed" tab, but to actually *run*
the probe you need the branch locally (Desktop or CLI above). Find the branch name near the top of the PR
page (e.g. "user wants to merge … from `copilot/...`").

## Which agent?

All three can do this. Practical guidance: Claude and Codex are stronger at the "inspect a live site, infer
selectors" part; Copilot is convenient if you already live in that ecosystem. For a big batch, assign a few
issues to each and compare. Cost differs by plan — check before mass-assigning.
