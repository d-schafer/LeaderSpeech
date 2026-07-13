"""CLI: clean + structure the metadata of scraped speeches.

    # one source (auto-detects its country folder)
    python -m leaderspeech.clean_structure_metadata.run --source chl_presidencia --limit 20

    # every source in a country, or everything scraped
    python -m leaderspeech.clean_structure_metadata.run --country Chile
    python -m leaderspeech.clean_structure_metadata.run --all

    # an ARBITRARY combined corpus (any CSV/Parquet, many countries/datasets in one table)
    python -m leaderspeech.clean_structure_metadata.run --input data/LeaderSpeech.parquet
    #   -> writes data/LeaderSpeech.cleaned.parquet (raw input untouched); --output overrides

Resumable: re-running only sends speeches not already cleaned to the model. Use
--retry-failed to re-attempt rows that errored, and --dry-run to preview counts with
no API calls.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config
from .pipeline import clean_file, clean_source, iter_sources, regate_source

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser(description="LeaderSpeech metadata cleaner")
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--source", help="a single source_id (e.g. chl_presidencia)")
    sel.add_argument("--country", help="clean every source under this country folder")
    sel.add_argument("--all", action="store_true", help="clean every scraped source")
    sel.add_argument("--input", help="clean an ARBITRARY CSV/Parquet corpus (many countries/datasets "
                                     "in one table); ignores the per-country folder convention")
    ap.add_argument("--output", default=None,
                    help="with --input: write here instead of <input_stem>.cleaned.parquet")
    ap.add_argument("--in-root", default="data/scraped")
    ap.add_argument("--out-root", default="data/cleaned")
    ap.add_argument("--state-root", default="data/clean_state")
    ap.add_argument("--config", default=None, help="path to clean_config.yml (else defaults)")
    ap.add_argument("--model", default=None, help="override the model for this run")
    ap.add_argument("--limit", type=int, default=None, help="cap speeches cleaned per source this run")
    ap.add_argument("--retry-failed", action="store_true", help="re-attempt rows that errored")
    ap.add_argument("--dry-run", action="store_true", help="report what would be cleaned; no API calls")
    ap.add_argument("--regate", action="store_true",
                    help="re-apply the gate to already-cleaned rows from stored fields; no API calls "
                         "(use after changing keep_document_types / require_leader_type)")
    args = ap.parse_args()

    config = load_config(args.config)

    # --input: clean one arbitrary table into a single output Parquet (non-destructive by default).
    if args.input:
        if args.regate:
            ap.error("--regate operates on the cleaned store (per-source Parquet), not an --input table")
        in_path = Path(args.input)
        out_path = Path(args.output) if args.output else in_path.with_name(in_path.stem + ".cleaned.parquet")
        summary = clean_file(
            in_path, out_path, config=config, model=args.model,
            label=in_path.stem, limit=args.limit, retry_failed=args.retry_failed,
            dry_run=args.dry_run, refresh_index=False,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.source:
        targets = [(args.source, args.country)]
    elif args.regate:
        # regate operates on the cleaned store (Parquet), so enumerate sources there
        country = None if args.all else args.country
        pattern = f"{country}/*.parquet" if country else "*/*.parquet"
        targets = [(p.stem, p.parent.name) for p in sorted(Path(args.out_root).glob(pattern))]
    else:
        country = None if args.all else args.country
        targets = [(sid, c) for sid, c, _ in iter_sources(args.in_root, country)]

    if not targets:
        print(f"no sources found under {args.out_root if args.regate else args.in_root}")
        return

    summaries = []
    for source_id, country in targets:
        if args.regate:
            result = regate_source(source_id, out_root=args.out_root, config=config, country=country)
        else:
            result = clean_source(
                source_id, in_root=args.in_root, out_root=args.out_root,
                state_root=args.state_root, config=config, model=args.model,
                country=country, limit=args.limit, retry_failed=args.retry_failed,
                dry_run=args.dry_run,
            )
        summaries.append(result)

    print(json.dumps(summaries if len(summaries) > 1 else summaries[0],
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
