"""Generate GitHub issues — one per un-recipe'd source — from master_sources.xlsx.

This turns the recipe backlog into issues an agent (or you) can work through in
batches. NOT run automatically. Requires `gh` authenticated against the repo.

Examples:
    # preview the first 10 without creating anything
    python scripts/create_issues_from_master.py --limit 10 --dry-run

    # create issues for African sources still lacking a recipe, 15 at a time
    python scripts/create_issues_from_master.py --region Africa --limit 15

    # everything still at recipe_status=none (careful — could be ~100 issues)
    python scripts/create_issues_from_master.py
"""

import argparse
import subprocess
from pathlib import Path

import pandas as pd

REPO_DEFAULT = "d-schafer/LeaderSpeech"
MASTER = Path(__file__).resolve().parents[1] / "data" / "sources" / "master_sources.xlsx"


def body_for(row) -> str:
    return f"""Author a scraper recipe for this source. One source = one recipe in `recipes/`.

- **Country:** {row.country}
- **Source:** {row.source_url}
- **Type:** {row.source_type or 'unknown'}
- **Renderer (guess):** {row.renderer or 'unknown'}
- **Language:** {row.language or 'unknown'}
- **source_id:** `{row.source_id}`

Follow the end-to-end runbook in `docs/agent_task_end_to_end.md`:
1. Inspect + write `recipes/{row.source_id}.yml` (see `docs/recipes.md`).
2. Prove it: `python -m leaderspeech.text_scraper.probe --recipe recipes/{row.source_id}.yml`
   (listing > 0 links; title/text/date show as matched).
3. Capped run, then full history; debug via `docs/debugging.md` and `--retry-failed`.
4. Record the result in the `data/sources/additional_master_sources.csv` **outbox** (your proposed
   `recipe_status` for this `source_id`); open a PR. **Never edit `master_sources.xlsx`** — it's
   researcher-owned. The maintainer (or Claude) sets `recipe_status: validated` there when the PR merges.

Tip: an existing recipe may be a close template — check `recipes/` for a same-structure site first
(e.g. the Latin-American presidencies share a layout with `arg_casarosada.yml`).
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=REPO_DEFAULT)
    ap.add_argument("--region", help="filter by region substring (e.g. Africa)")
    ap.add_argument("--country", help="filter by country substring")
    ap.add_argument("--status", default="none", help="recipe_status to target")
    ap.add_argument("--limit", type=int, help="cap how many issues to create")
    ap.add_argument("--label", default="recipe", help="label to apply ('' for none)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    df = pd.read_excel(MASTER).fillna("")
    df = df[df["recipe_status"] == args.status]
    if args.region:
        df = df[df["region"].str.contains(args.region, case=False, na=False)]
    if args.country:
        df = df[df["country"].str.contains(args.country, case=False, na=False)]
    if args.limit:
        df = df.head(args.limit)

    print(f"{len(df)} issue(s) to create (status={args.status}).")
    for _, row in df.iterrows():
        title = f"[recipe] {row.country} — {row.source_name or row.source_id}"
        if args.dry_run:
            print("  DRY:", title)
            continue
        cmd = ["gh", "issue", "create", "--repo", args.repo,
               "--title", title, "--body", body_for(row)]
        if args.label:
            cmd += ["--label", args.label]
        subprocess.run(cmd, check=True)
        print("  created:", title)


if __name__ == "__main__":
    main()
