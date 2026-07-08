"""Compare translation backends on a small sample — without writing anything.

Samples a few rows, translates the origin-language text with one or several backends, and
prints the original next to each translation so you can eyeball quality and pick a backend.

    python -m leaderspeech.translate.probe --source arg_casarosada --n 3
    python -m leaderspeech.translate.probe --source arg_casarosada --translator google,nllb
    python -m leaderspeech.translate.probe --input data/scraped/Chile/chl_presidencia.csv --n 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import store
from .backends import get_translator
from .config import load_config
from .pipeline import resolve_src_lang

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _resolve_source(out_root: str, source: str, country: str | None) -> Path:
    root = Path(out_root)
    if country:
        return root / country / f"{source}.parquet"
    matches = list(root.glob(f"*/{source}.parquet"))
    if not matches:
        raise FileNotFoundError(f"no cleaned Parquet '{source}.parquet' under {root}")
    if len(matches) > 1:
        raise ValueError(f"ambiguous source '{source}'; pass --country")
    return matches[0]


def main():
    ap = argparse.ArgumentParser(description="Probe/compare translation backends on a sample (no writes)")
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--source", help="a cleaned source_id")
    sel.add_argument("--input", help="an arbitrary CSV/Parquet")
    ap.add_argument("--country", default=None)
    ap.add_argument("--out-root", default="data/cleaned")
    ap.add_argument("--translator", default="google", help="one or more (comma-separated): google,opusmt,nllb")
    ap.add_argument("--field", default="text", help="which field to compare (text|title|context)")
    ap.add_argument("--n", type=int, default=3, help="rows to sample")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-chars", type=int, default=600, help="truncate display (and what is sent) to this many chars")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    config = load_config(args.config)
    path = Path(args.input) if args.input else _resolve_source(args.out_root, args.source, args.country)
    df = store.read_table(path)

    origin_col = f"{args.field}_originlanguage"
    if origin_col not in df.columns:
        print(f"no column {origin_col} in {path}")
        return
    have_origin = df[df[origin_col].astype(str).str.strip() != ""]
    if have_origin.empty:
        print(f"no rows with non-empty {origin_col}")
        return
    sample = have_origin.sample(n=min(args.n, len(have_origin)), random_state=args.seed)

    names = [t.strip() for t in args.translator.split(",") if t.strip()]
    backends = {name: get_translator(name, config) for name in names}

    print(f"\nTRANSLATE PROBE  file={path.name}  field={args.field}  backends={names}\n")
    for _, row in sample.iterrows():
        src = resolve_src_lang(row)
        origin = str(row[origin_col])[: args.max_chars]
        print(f"── doc_id={row.get('doc_id')}  src={src}")
        print(f"   ORIGINAL : {origin!r}")
        for name, backend in backends.items():
            try:
                out = backend.translate(origin, src)
            except Exception as e:
                out = f"<error: {type(e).__name__}: {e}>"
            print(f"   {name:8}: {str(out)[: args.max_chars]!r}")
        print()


if __name__ == "__main__":
    main()
