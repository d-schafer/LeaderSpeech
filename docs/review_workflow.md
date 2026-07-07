# The review pipeline: cheap workhorse + frontier reviewer

A division of labor for scaling recipes responsibly: a **cheap agent** does the broad, repetitive
recipe-authoring; a **frontier reviewer** does fast, targeted verification; and **you (the researcher)**
hold the gates that matter. This document is both the human setup guide and the reviewer's instructions.

## Roles

| Who | Does | Never does |
|-----|------|------------|
| **You (researcher)** | Hold the three gates (below). | — |
| **Workhorse agent** (GPT-5.x mini / Sonnet, via Copilot/Codex/@claude) | Inspect a site, write `recipes/<id>.yml`, open a PR, iterate on review feedback. | Merge; decide it's "done". |
| **Frontier reviewer** (Claude, etc.) | On "ready for review", verify the PR and post a PASS / CHANGES verdict. When that verdict already contains a **probe-verified** recipe, may commit it straight to the PR branch instead of round-tripping the agent (see "When the review is the fix"). | Merge, run full scrapes, assign agents, push edits to `main`. |

## Your three gates (always manual, never automated)

1. **START** — you create an issue and assign it to an agent. Nothing scrapes until you do.
2. **FULL RUN** — you run the complete scrape on your machine. This is where the real data and storage
   happen, so it stays under your control.
3. **MERGE** — you merge the PR to `main` (browser) **and set that source's `recipe_status` to
   `validated` in `data/sources/master_sources.xlsx`** (you, or ask Claude — never the workhorse agent;
   see "Closing the loop" below). Publishing a recipe is your call.

Everything between those gates can run seamlessly.

## The loop (minimal copy-paste)

1. **[GATE: START]** You create an issue (browser, `gh`, or `scripts/create_issues_from_master.py`) and
   assign it to a workhorse agent in the GitHub UI.
2. The agent inspects the site, writes the recipe, opens a PR, marks it ready.
3. You tell the reviewer one line: **"review PR #N"**. That's the whole handoff — the reviewer reads
   everything from GitHub itself (no pasting agent output back and forth).
4. The reviewer (see "What the reviewer does" below) posts a comment on the PR: **PASS** or **CHANGES**
   with the exact fixes.
5. If **CHANGES**: normally the agent iterates (you re-comment `@agent`, or it picks up the review), back to
   step 3. **But if the reviewer's verdict already includes a complete, `--spread`-verified recipe** — i.e. it
   had to fully re-author the fix, not just point at it — the reviewer commits that recipe straight to the PR
   branch (no agent round-trip) and you jump to step 6. See "When the review is the fix".
6. If **PASS**: **[GATE: FULL RUN]** you run the full scrape locally and confirm it end-to-end (date
   coverage, failure rate). The data lands on your disk.
7. **[GATE: MERGE]** you merge the PR, then **bump that source's `recipe_status` to `validated` in
   `data/sources/master_sources.xlsx`** (see "Closing the loop" below).

## Closing the loop: update `recipe_status` (and who may touch `master_sources.xlsx`)

The recipe backlog is keyed off the `recipe_status` column: `scripts/create_issues_from_master.py` files an
issue for every row still at `none`. So the **final step of the agent↔reviewer back-and-forth** is to flip
the merged source's row to `validated` — otherwise the backlog "lags reality" and the generator re-proposes a
source that's already done.

- **Who updates it:** **you (researcher) or Claude** — and at the **MERGE** step (after PASS). For now keep it
  to the **status column only**. Claude doing this is an exception to "never edit `master_sources.xlsx`" that
  applies *only* to Claude in its authoring role, *only* to `recipe_status`, and never as a regenerate.
- **The workhorse agent never touches `master_sources.xlsx`.** It records its *proposed* status in the
  `data/sources/additional_master_sources.csv` **outbox** (see `agent_task_end_to_end.md`); that's all.

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
4. **Don't block the review loop on CI.** Verify the tests yourself with a local
   `python -m pytest -q` (in the `leaderspeech_scrape` venv), and treat green CI as a single
   pre-merge confirmation at the FULL RUN / MERGE gate — not a per-round gate. (Copilot-bot PR
   runs often sit in `action_required` awaiting manual approval, which would otherwise stall the loop.)
5. **Plausibility** — speaker/date look right for that country (a glance vs `leader_tenure_final`).
6. Post the verdict with `gh pr comment <N>`: **PASS** (ready for the human's full run + merge) or
   **CHANGES** with the specific selector/pagination/SSL fixes. Verdicts are concrete — never a vague
   "looks good".

**Reviewing engine/tool-code PRs (not just recipes).** When a PR changes the engine itself (a new
pagination type, a fetch/extract change), the recipe can't be probed against your installed `main`
package — `load_recipe` rejects the new fields/enums. Probe it faithfully in a throwaway **git worktree
at the branch tip**: `git worktree add --detach <tmp> origin/<branch>`, probe from inside `<tmp>`, then
`git worktree remove <tmp> --force`. This keeps your working tree untouched. Read the engine diff too —
the bar for shared-engine changes is **backward-compatibility** (existing recipes must take the unchanged
code path).

## When the review is the fix (reviewer applies a verified recipe directly)

The workhorse↔reviewer round-trip exists so the **cheap** agent does the broad first-pass authoring and the
**expensive** reviewer only spot-checks. That math inverts when the first pass never actually validated against
the live site and the reviewer ends up **fully diagnosing and re-writing** the recipe (e.g. a UA-blocking WAF
plus wrong title/text selectors). At that point the corrected recipe *already exists in the review* — bouncing
it back to the agent just to paste it in is pure latency, and a chance for the agent to mis-apply it.

**Default: copilot is for cold, net-new authoring.** When the reviewer's CHANGES verdict already contains a
**complete, probe-verified** recipe, skip the agent round-trip and let the reviewer commit that recipe
**directly to the PR's branch**.

**Mechanism: commit to the PR branch, never to `main`.** Use a throwaway worktree so the researcher's working
tree is untouched:
```
git fetch origin <branch>
git worktree add <tmp> -B <branch> origin/<branch>
# overwrite recipes/<id>.yml with the verified recipe
git -C <tmp> commit -am "Apply reviewer fixes: <one-line summary>"
git -C <tmp> push origin <branch>
git worktree remove <tmp> --force
```
The PR now carries the fixed recipe; the researcher still runs the FULL RUN and still clicks MERGE.

**Only when ALL of these hold:**
- The reviewer has the **actual corrected recipe**, not just a diagnosis — every selector / pagination / UA
  change is written out.
- A final **`--spread` pass on a random, even selection across the full history passes cleanly**:
  `title` / `text` / `date` show ✓ on samples spanning the **whole** date range (old *and* new pages), and
  `LISTING` link count > 0. This is the non-negotiable gate — never push a fix you haven't watched work
  end-to-end across the site's history.
- The agent is **not actively working the branch** right now (don't race its pushes). If you just pinged
  `@agent`, let it take its swing first; only step in if it stalls or fumbles the paste.

If you only have a partial diagnosis, hand it back to the agent as before (step 5, first path).

**Still the human's, unchanged:** START (new issues / agents), FULL RUN (the complete scrape), MERGE (to `main`
+ the `recipe_status` flip). Committing a verified fix to a PR *branch* is none of those — it's finishing the
review, not publishing. (This project's authoring-role `.claude/settings.json` already allows the
`git worktree`/`commit`/`push` needed here, while the `gh pr merge` and full-`run` deny-rules keep those gates
intact.)

## Hard rules for the reviewer

- **Never** `gh pr merge` — merging is the human's gate.
- **Never** run an uncapped/full scrape — only `--spread`, `--max-pages`, `--limit`. Full runs are the
  human's gate (data + storage).
- **Never** assign or initiate an agent.
- **Never** push recipe edits to `main` for a PR under review. Posting a review and letting the agent fix on
  its branch is the default — but when your verdict already contains a **`--spread`-verified** recipe you may
  commit it to the **PR branch** (not `main`); see "When the review is the fix". MERGE to `main` stays the
  human's gate.
- The **only** edit Claude may make to `master_sources.xlsx` is flipping a merged source's `recipe_status`
  to `validated` (status-only), and only at/after MERGE — never edit a recipe on `main`, never regenerate
  the file, never edit it for a PR still under review.
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
