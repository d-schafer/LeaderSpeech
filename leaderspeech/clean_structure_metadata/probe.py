"""Diagnose the cleaner on a small RANDOM sample — without writing anything.

Runs the extraction pass on a few sampled speeches and prints the structured output
next to the scraped metadata, so you can eyeball quality and iterate the prompt cheaply
before a full run.

    python -m leaderspeech.clean_structure_metadata.probe --source chl_presidencia --n 5
    python -m leaderspeech.clean_structure_metadata.probe --all-countries --n 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pandas as pd

from . import extract, gate, tenure
from .config import load_config
from .llm import create_async_client, load_api_key
from .pipeline import _year_of, enrich, iter_sources, _locate_csv

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _select(csv_path: Path, n: int, seed: int, doc_ids: set | None) -> pd.DataFrame:
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    if df.empty:
        return df
    if doc_ids:
        return df[df["doc_id"].astype(str).isin(doc_ids)]
    return df.sample(n=min(n, len(df)), random_state=seed)


async def _extract_rows(client, config, items, tenure_df):
    sem = asyncio.Semaphore(config.batch_size)
    metas = await asyncio.gather(
        *(extract.extract_one(client, config, it["message"], sem) for it in items),
        return_exceptions=True,
    )
    return metas


def probe(args) -> dict:
    config = load_config(args.config)
    if args.model:
        config = config.model_copy(update={"model": args.model})

    if args.all_countries:
        sources = iter_sources(args.in_root)
    else:
        csv_path, country = _locate_csv(args.in_root, args.source, args.country)
        sources = [(args.source, country, csv_path)]

    tenure_df = tenure.get_tenure(str(config.tenure_file)) if Path(config.tenure_file).exists() else None
    doc_ids = {d.strip() for d in args.doc_id.split(",")} if getattr(args, "doc_id", None) else None

    items = []
    for source_id, country, csv_path in sources:
        sample = _select(csv_path, args.n, args.seed, doc_ids)
        for _, r in sample.iterrows():
            row = r.to_dict()
            year = _year_of(row.get("date"))
            leaders_info = ""
            if tenure_df is not None:
                leaders_info = ", ".join(tenure.leaders_for(tenure_df, row.get("country", ""), year, config.tenure_window))
            items.append({
                "source_id": source_id, "row": row,
                "message": extract.build_user_message(row, leaders_info, config.max_words),
            })

    client = create_async_client(load_api_key(config))
    try:
        metas = asyncio.run(_extract_rows(client, config, items, tenure_df))
    finally:
        try:
            asyncio.run(client.close())
        except Exception:
            pass

    report = []
    for it, meta in zip(items, metas):
        if isinstance(meta, Exception):
            report.append({"source": it["source_id"], "doc_id": it["row"].get("doc_id"),
                           "error": f"{type(meta).__name__}: {meta}"})
            continue
        cleaned = enrich(it["row"], meta, tenure_df, config)
        report.append({
            "source": it["source_id"],
            "doc_id": it["row"].get("doc_id"),
            "scraped_speaker": it["row"].get("speaker"),
            "scraped_date": it["row"].get("date"),
            "meta": meta,
            "tenure_match": cleaned.get("tenure_match"),
            "clean_status": cleaned.get("clean_status"),
            "gate_reason": cleaned.get("gate_reason"),
        })
    return {"model": config.model, "n_probed": len(report), "results": report}


def _print(rep: dict):
    print(f"\nCLEAN PROBE  model={rep['model']}  n={rep['n_probed']}\n")
    for r in rep["results"]:
        print(f"── {r['source']}  {r.get('doc_id')}")
        if "error" in r:
            print(f"   ✗ {r['error']}")
            continue
        m = r["meta"]
        status = r["clean_status"]
        mark = "✓ ACCEPT" if status == gate.ACCEPTED else f"✗ {status}"
        print(f"   {mark}  ({r['gate_reason']})" if r["gate_reason"] else f"   {mark}")
        print(f"   speaker:   scraped={r['scraped_speaker']!r}  ->  {m.get('speaker')!r} "
              f"(type={m.get('speaker_type')}, attributed_correct={m.get('speaker_attributed_correct')})")
        print(f"   document:  document_type={m.get('document_type')} first_person={m.get('is_first_person')} "
              f"speech_type={m.get('speech_type')} audience={m.get('audience')}")
        print(f"   date:      scraped={r['scraped_date']!r} -> {m.get('date')!r} "
              f"(matches={m.get('date_matches_metadata')})   lang={m.get('language')}  venue={m.get('venue')}")
        print(f"   tenure:    {r['tenure_match']}   confidence={m.get('confidence')}")
        if m.get("reasoning"):
            print(f"   reasoning: {m['reasoning']}")
        print()


def main():
    ap = argparse.ArgumentParser(description="Probe the metadata cleaner on a random sample")
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--source", help="a single source_id")
    sel.add_argument("--all-countries", action="store_true", help="sample from every scraped source")
    ap.add_argument("--country", default=None, help="disambiguate --source if needed")
    ap.add_argument("--n", type=int, default=5, help="rows to sample (per source)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--doc-id", default=None,
                    help="probe specific doc_id(s) (comma-separated) instead of a random sample")
    ap.add_argument("--in-root", default="data/scraped")
    ap.add_argument("--config", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rep = probe(args)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        _print(rep)


if __name__ == "__main__":
    main()
