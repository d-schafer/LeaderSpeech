"""CLI: inventory speakers, classify + verify the unmatched, and PROPOSE additions to an outbox.

    # free: just bucket matched / wrong-country / unmatched (no API calls)
    python -m leaderspeech.leader_tenure.run --diagnostic

    # classify + GPT-verify unmatched speakers and write the proposal outbox
    python -m leaderspeech.leader_tenure.run --limit 50
    python -m leaderspeech.leader_tenure.run --wikipedia --verify-model gpt-4.1

This NEVER edits leader_tenure_final.csv. It writes:
  - data/sources/leader_tenure_inventory.xlsx          (all buckets, for inspection)
  - data/sources/leader_tenure_proposed_additions.xlsx (the outbox you approve by hand)
Approve rows there, then apply with `python -m leaderspeech.leader_tenure.merge`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from ..clean_structure_metadata import llm, tenure
from . import classify, inventory, verify
from .config import load_config

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# columns written to the proposal outbox (mirrors the example *_verified_additions_ceremonial.csv)
OUTBOX_COLUMNS = [
    "approved", "speaker", "country", "role", "min_year", "max_year", "n_speeches",
    "classification_method", "reasoning",
    "gpt_is_leader", "gpt_actual_role", "is_ceremonial", "gpt_confidence", "gpt_reasoning",
    "wikipedia_extract", "proposed_at",
]


def _write_inventory(buckets: dict, path: str):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        for name, frame in buckets.items():
            (frame if not frame.empty else pd.DataFrame(columns=["speaker", "country"])).to_excel(
                xw, sheet_name=name[:31], index=False)


def main():
    ap = argparse.ArgumentParser(description="Curate the leader-tenure key (propose additions to an outbox)")
    ap.add_argument("--input", default=None, help="explicit dataset path (else final/merged, else cleaned/*)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--diagnostic", action="store_true", help="only inventory + bucket; no API calls")
    ap.add_argument("--limit", type=int, default=None, help="cap unmatched speakers sent to the model")
    ap.add_argument("--classify-model", default=None)
    ap.add_argument("--verify-model", default=None)
    ap.add_argument("--model", default=None, help="set BOTH classify and verify models")
    ap.add_argument("--wikipedia", action="store_true", help="ground verification with live Wikipedia")
    ap.add_argument("--out", default=None, help="outbox path (else config.outbox)")
    args = ap.parse_args()

    config = load_config(args.config)
    updates = {}
    if args.classify_model:
        updates["classify_model"] = args.classify_model
    if args.verify_model:
        updates["verify_model"] = args.verify_model
    if args.model:
        updates["classify_model"] = updates["verify_model"] = args.model
    if args.wikipedia:
        updates["use_wikipedia"] = True
    if updates:
        config = config.model_copy(update=updates)

    if not Path(config.tenure_file).exists():
        print(f"tenure key not found at {config.tenure_file}")
        return
    tenure_df = tenure.get_tenure(str(config.tenure_file))

    speeches, src = inventory.load_speeches(config, args.input)
    inv = inventory.build_inventory(speeches)
    bucketed = inventory.bucket_inventory(inv, tenure_df, config.tenure_window)
    buckets = inventory.split_buckets(bucketed)

    _write_inventory(buckets, config.inventory_out)
    print(f"\nLEADER-TENURE INVENTORY  (source: {src})")
    print(f"  speakers (speaker x country): {len(bucketed)}")
    print(f"   matched:        {len(buckets['matched'])}")
    print(f"   wrong_country:  {len(buckets['wrong_country'])}  (likely foreign visitors / mislabels)")
    print(f"   unmatched:      {len(buckets['unmatched'])}  (candidates for new additions)")
    gaps = buckets["matched"][buckets["matched"]["years_in_tenure"] == False]  # noqa: E712
    if len(gaps):
        print(f"   year-coverage gaps among matched: {len(gaps)} (speeches outside recorded tenure)")
    print(f"  wrote {config.inventory_out}")

    if args.diagnostic:
        print("\n--diagnostic: stopping before any API call.")
        return

    unmatched = buckets["unmatched"]
    if args.limit is not None:
        unmatched = unmatched.head(args.limit)
    if unmatched.empty:
        print("\nno unmatched speakers to classify.")
        return

    client = llm.create_async_client(llm.load_api_key(config))
    try:
        classified = classify.classify_unmatched(unmatched, config, client=client)
        proposed = classified[classified["is_leader"] == True].copy()  # noqa: E712
        verified = verify.verify_proposals(proposed, config, client=client)
    finally:
        import asyncio
        try:
            asyncio.run(client.close())
        except Exception:
            pass

    verified["approved"] = ""             # researcher fills this in
    verified["proposed_at"] = datetime.now().isoformat(timespec="seconds")
    for c in OUTBOX_COLUMNS:
        if c not in verified.columns:
            verified[c] = ""
    out_path = args.out or config.outbox
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    verified[OUTBOX_COLUMNS].to_excel(out_path, index=False)

    n_conf = int(((verified["gpt_is_leader"] == True) &  # noqa: E712
                  (verified["gpt_confidence"].isin(config.min_confidence))).sum())
    print(f"\nclassified unmatched: {len(classified)} | proposed leaders: {len(proposed)} | "
          f"GPT-confirmed (>= {config.min_confidence}): {n_conf}")
    print(f"wrote outbox: {out_path}")
    print("REVIEW it, set `approved`, then run `python -m leaderspeech.leader_tenure.merge --dry-run`.")


if __name__ == "__main__":
    main()
