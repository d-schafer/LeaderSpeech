# The review pipeline: cheap workhorse + frontier reviewer

A division of labor for scaling recipes responsibly: a **cheap agent** does the broad, repetitive
recipe-authoring; a **frontier reviewer** does fast, targeted verification; and **you (the researcher)**
hold the gates that matter. This document is both the human setup guide and the reviewer's instructions.

## Roles

| Who | Does | Never does |
|-----|------|------------|
| **You (researcher)** | Hold the three gates (below). | — |
| **Workhorse agent** (GPT-5.x mini / Sonnet, via Copilot/Codex/@claude) | Inspect a site, write `recipes/<id>.yml`, open a PR, iterate on review feedback. | Merge; decide it's "done". |
| **Frontier reviewer** (Claude, etc.) | On "ready for review", verify the PR and post a PASS / CHANGES verdict. | Merge, run full scrapes, assign agents, push recipe edits to main. |

## Your three gates (always manual, never automated)

1. **START** — you create an issue and assign it to an agent. Nothing scrapes until you do.
2. **FULL RUN** — you run the complete scrape on your machine. This is where the real data and storage
   happen, so it stays under your control.
3. **MERGE** — you merge the PR to `main` (browser). Publishing a recipe is your call.

Everything between those gates can run seamlessly.

## The loop (minimal copy-paste)

1. **[GATE: START]** You create an issue (browser, `gh`, or `scripts/create_issues_from_master.py`) and
   assign it to a workhorse agent in the GitHub UI.
2. The agent inspects the site, writes the recipe, opens a PR, marks it ready.
3. You tell the reviewer one line: **"review PR #N"**. That's the whole handoff — the reviewer reads
   everything from GitHub itself (no pasting agent output back and forth).
4. The reviewer (see "What the reviewer does" below) posts a comment on the PR: **PASS** or **CHANGES**
   with the exact fixes.
5. If **CHANGES**: the agent iterates (you re-comment `@agent`, or it picks up the review). Back to step 3.
6. If **PASS**: **[GATE: FULL RUN]** you run the full scrape locally and confirm it end-to-end (date
   coverage, failure rate). The data lands on your disk.
7. **[GATE: MERGE]** you merge the PR.

## What the reviewer does (the bar)

Read-only + spot-check + one comment. Concretely:

1. Read the recipe from the branch **without checking it out** (keeps your working tree alone):
   `git fetch origin <branch>` then `git show origin/<branch>:recipes/<id>.yml`.
2. **Across-time spot check** — the important one:
   `python -m leaderspeech.text_scraper.probe --recipe <tmp> --n 15 --spread`
   This samples 15 pages evenly across the **whole** history and shows each one's date. The bar:
   - `LISTING` link count > 0,
   - `title` / `text` / `date` show ✓ on samples spanning the **full date range** (not just recent ones —
     this is what catches a recipe that works for 2026 but breaks on 2018),
   - no "recipe got 0 chars but generic would recover N" warnings on the old samples.
3. **Date coverage** — does the earliest sampled date match the leader's tenure / the site's real history?
   A clean run that only spans recent weeks usually means pagination silently stopped (see the sitemap note
   in `recipes.md`).
4. **CI** — the schema check on the PR is green (`gh pr checks <N>`).
5. **Plausibility** — speaker/date look right for that country (a glance vs `leader_tenure_final`).
6. Post the verdict with `gh pr comment <N>`: **PASS** (ready for the human's full run + merge) or
   **CHANGES** with the specific selector/pagination/SSL fixes. Verdicts are concrete — never a vague
   "looks good".

## Hard rules for the reviewer

- **Never** `gh pr merge` — merging is the human's gate.
- **Never** run an uncapped/full scrape — only `--spread`, `--max-pages`, `--limit`. Full runs are the
  human's gate (data + storage).
- **Never** assign or initiate an agent.
- **Never** push recipe edits to `main` for a PR under review — post a review; the agent fixes on its branch.
- Always do the `--spread` across-time check before a PASS.

## Setup: make the reviewer seamless (permissions)

So you aren't clicking "approve" on every reviewer command, allowlist its bounded, read-only/review actions
in the repo's `.claude/settings.json`. Crucially, this list **omits** the three gates, so a merge or a full
run still stops for you.

```jsonc
// .claude/settings.json
{
  "permissions": {
    "allow": [
      "Bash(gh pr view:*)",
      "Bash(gh pr diff:*)",
      "Bash(gh pr checks:*)",
      "Bash(gh pr comment:*)",
      "Bash(gh pr review:*)",
      "Bash(git fetch:*)",
      "Bash(git show:*)",
      "Bash(git log:*)",
      "Bash(*text_scraper.probe*)"
    ]
    // NOT allowed (stay manual gates): gh pr merge, any '...text_scraper.run' full scrape,
    // assigning agents. Leave these off so they always prompt you.
  }
}
```

You can add this with the `/permissions` command in Claude Code, by editing `.claude/settings.json`, or by
asking a session to set it up. Keep `gh pr merge` and `text_scraper.run` **out** of the allow-list on
purpose — that's what preserves your FULL RUN and MERGE gates.

## Starting a fresh reviewer session

The **repo is the durable memory** — no chat history needed. A new reviewer session just reads, in order:
`README.md`, `docs/recipes.md`, `docs/debugging.md`, `docs/agent_task_end_to_end.md`, **this file**, and
glances at `recipes/` + `data/sources/master_sources.xlsx`. Then it can review any PR with:
*"review PR #N"*. Long chats get slow and expensive; rotate to a fresh session and let the repo carry the
context.
