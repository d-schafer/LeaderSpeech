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


def _parquet_has_rows(path) -> bool:
    """True if a cleaned Parquet actually holds rows. Skips 0-row artifacts (e.g. from an
    interrupted run) so `--reclean`/`--regate --all` never pick them up and re-clean a whole
    source from scratch."""
    try:
        import pyarrow.parquet as pq
        return pq.ParquetFile(path).metadata.num_rows > 0
    except Exception:
        return True


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
    ap.add_argument("--reclean", action="store_true",
                    help="re-send EVERY already-cleaned row to the model (use after adding a new "
                         "extraction field such as is_substantive; costs API calls, unlike --regate). "
                         "Operates on the CLEANED store like --regate, so --all targets only "
                         "already-cleaned sources, not everything scraped.")
    ap.add_argument("--dry-run", action="store_true", help="report what would be cleaned; no API calls")
    ap.add_argument("--regate", action="store_true",
                    help="re-apply the gate to already-cleaned rows from stored fields; no API calls "
                         "(use after changing keep_document_types / require_leader_type)")
    args = ap.parse_args()

    config = load_config(args.config)
    if args.reclean and args.regate:
        ap.error("--reclean re-runs the model; --regate is no-API. Use one or the other.")

    # --input: clean one arbitrary table into a single output Parquet (non-destructive by default).
    if args.input:
        if args.regate:
            ap.error("--regate operates on the cleaned store (per-source Parquet), not an --input table")
        in_path = Path(args.input)
        out_path = Path(args.output) if args.output else in_path.with_name(in_path.stem + ".cleaned.parquet")
        summary = clean_file(
            in_path, out_path, config=config, model=args.model,
            label=in_path.stem, limit=args.limit, retry_failed=args.retry_failed,
            reclean=args.reclean, dry_run=args.dry_run, refresh_index=False,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if args.source:
        targets = [(args.source, args.country)]
    elif args.regate or args.reclean:
        # regate/reclean operate on ALREADY-CLEANED sources, so enumerate the cleaned store
        # (Parquet), NOT everything scraped -- otherwise `--all` would (re)clean never-cleaned
        # sources like the big full scrapes. Skip 0-row artifacts from any interrupted run.
        country = None if args.all else args.country
        pattern = f"{country}/*.parquet" if country else "*/*.parquet"
        targets = [(p.stem, p.parent.name) for p in sorted(Path(args.out_root).glob(pattern))
                   if _parquet_has_rows(p)]
    else:
        country = None if args.all else args.country
        targets = [(sid, c) for sid, c, _ in iter_sources(args.in_root, country)]

    if not targets:
        print(f"no sources found under {args.out_root if (args.regate or args.reclean) else args.in_root}")
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
                reclean=args.reclean, dry_run=args.dry_run,
            )
        summaries.append(result)

    print(json.dumps(summaries if len(summaries) > 1 else summaries[0],
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
