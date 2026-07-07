# Curating the leader-tenure key

`leader_tenure_final.csv` (one row per leader-year, with `is_ceremonial`) is the
authoritative answer to "who was plausibly in power in this country on this date." The
cleaner cross-checks every speaker against it, but **never edits it**. This tool closes the
loop while keeping the key 100% accurate: it finds speakers the key doesn't know, verifies
the genuine national leaders among them, and **proposes** them to an outbox the researcher
approves by hand. Only a separate, gated `merge --apply` step writes the key.

## Why a propose-then-approve loop

The key is used to validate every speech, so a wrong row contaminates the dataset. So the
tool is split in two: `run` does all the searching and (paid) verification and writes a
review file; `merge` applies only what the researcher approved, after a backup, and never
deletes existing rows. Nothing the model decides reaches the key without a human in between.

## Step 1 — inventory & buckets (free)

```bash
python -m leaderspeech.leader_tenure.run --diagnostic
```

Reads the speeches (preferring the final `data/LeaderSpeech.parquet`, then the merged build,
then the cleaned per-source Parquets), aggregates them to one row per `(speaker, country)`,
and buckets each against the key using the cleaner's tolerant matcher:

- **matched** — a known leader of that country. For these it also records the tenure year
  range, so a **year-coverage gap** (speeches dated outside the recorded tenure) is flagged.
- **wrong_country** — matches a leader of a *different* country (likely a foreign visitor that
  slipped the gate, or a country mislabel). Reported for review, **not** proposed.
- **unmatched** — not in the key at all: the candidates for new additions.

All three buckets are written to `data/sources/leader_tenure_inventory.xlsx` (one sheet each).
`--diagnostic` stops here — no API calls.

## Step 2 — classify + verify the unmatched (paid)

```bash
python -m leaderspeech.leader_tenure.run --limit 50
python -m leaderspeech.leader_tenure.run --wikipedia --verify-model gpt-4.1
```

1. **Classify** each unmatched speaker as leader / non-leader. A position regex pre-filter
   (President, PM, King → include; minister, ambassador, governor, judge, non-reigning royal →
   exclude) handles the obvious cases for free; the ambiguous remainder goes to the cheap
   `classify_model` (default `gpt-4.1-mini`).
2. **Verify** each proposed leader with the strong `verify_model` (default **`gpt-4.1`** — the
   model validated for this step, for its world knowledge): did this person actually lead
   *this* country in *this* period, and is the office ceremonial or executive? With
   `--wikipedia`, each proposal is first grounded against the live Wikipedia summary API and
   that extract is given to the model.

The result is the **outbox** `data/sources/leader_tenure_proposed_additions.xlsx`, with an
`approved` column for you to fill (`yes`/`no`; blank falls back to the GPT verdict at merge),
the GPT verdict/role/confidence/reasoning, the ceremonial flag, and any Wikipedia extract.

Models are overridable: `--classify-model`, `--verify-model`, or `--model` (sets both).

## Step 3 — review, then merge (gated)

Open the outbox, set `approved` where you disagree with the model, then:

```bash
python -m leaderspeech.leader_tenure.merge --dry-run     # preview (default)
python -m leaderspeech.leader_tenure.merge --apply       # write the key
```

`merge` dedupes, expands each approved leader's `[min_year, max_year]` into leader-year rows
(carrying the country's `ISO3N`/`COWcode`/`stateabb`/`ccode` from the existing key), and skips
any `(speaker, country, year)` already present. `--dry-run` (the default) prints what would be
added and **`fixNames` suggestions** (including a flag for surname-only names that need a
full-name mapping). `--apply` writes `leader_tenure_final.csv` after a timestamped `.bak`, and
refuses to write if the result would drop any existing row.

After applying, paste the printed `fixNames` lines into `scripts/key_fixNames.R`, then re-run
the cleaner's tenure crosscheck (a fresh `clean` run, or re-export) so the new leaders are
recognized.

## Configuration reference (`configs/tenure_config.yml`)

| key | effect |
|-----|--------|
| `classify_model` | cheap pre-filter model (`gpt-4.1-mini`) |
| `verify_model` | strong verifier (`gpt-4.1`); CLI `--verify-model`/`--model` overrides |
| `dataset_candidates` / `cleaned_root` | where to read the speeches |
| `tenure_file` | the key to bucket against (and, for `merge`, to append to) |
| `outbox` / `inventory_out` | where proposals and the bucketed inventory are written |
| `use_wikipedia` | ground verification on live Wikipedia (or pass `--wikipedia`) |
| `min_confidence` | GPT confidences accepted at merge when `approved` is blank |

## Cost / safety

`run` (classify + verify) spends OpenAI money — a FULL-RUN gate; start with `--limit`.
`--diagnostic` and `merge --dry-run` are free. The tool only ever *appends* to the key, behind
a manual `--apply` and a backup; the outbox is the sole channel into `leader_tenure_final.csv`.
