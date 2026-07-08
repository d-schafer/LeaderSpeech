<!-- Closes #<issue> -->

## What this changes

-

## If this adds/edits a recipe

- [ ] `recipes/<source_id>.yml` validates (`pytest` passes / CI green)
- [ ] Did a small live run (`--max-pages 1 --limit 5`) and checked `title` / `text` / `date` are clean
- [ ] Spot-checked speaker + date against the leader-tenure key for plausibility
- [ ] Added the source's own outbox file `data/sources/additional_master_sources/<source_id>.csv` (one file per source — never edit the legacy flat `additional_master_sources.csv` nor `master_sources.xlsx`, which is researcher-owned; the maintainer sets `recipe_status: validated` on merge)
- [ ] No scraped output committed (`data/scraped/` stays out of git)

## Notes for the reviewer

-
