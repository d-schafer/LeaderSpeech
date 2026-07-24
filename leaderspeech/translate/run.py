"""CLI: translate the English `text`/`title`/`context` columns IN PLACE.

    # one cleaned source (auto-detects its country folder), or a country, or everything
    python -m leaderspeech.translate.run --source arg_casarosada --limit 20
    python -m leaderspeech.translate.run --country Argentina
    python -m leaderspeech.translate.run --all

    # any other table at any stage (raw scraped CSV, the merged build, ...)
    python -m leaderspeech.translate.run --input data/scraped/Chile/chl_presidencia.csv

Choose the backend with --translator (google [default] | opusmt | nllb). Resumable:
only rows whose English target is still empty are translated; --force re-translates.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import store  # noqa: F401  (kept for symmetry / explicit dependency)
from .backends import get_translator
from .config import load_config
from .pipeline import translate_file

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

log = logging.getLogger("leaderspeech.translate")


def _ensure_console():
    pkg = logging.getLogger("leaderspeech.translate")
    pkg.setLevel(logging.INFO)
    if not any(type(h) is logging.StreamHandler for h in pkg.handlers):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
        pkg.addHandler(sh)
    return pkg


def _cleaned_targets(out_root: str, source: str | None, country: str | None, do_all: bool) -> list[Path]:
    root = Path(out_root)
    if source:
        if country:
            p = root / country / f"{source}.parquet"
            if not p.exists():
                raise FileNotFoundError(f"no cleaned Parquet at {p}")
            return [p]
        matches = list(root.glob(f"*/{source}.parquet"))
        if not matches:
            raise FileNotFoundError(f"no cleaned Parquet '{source}.parquet' under {root}")
        if len(matches) > 1:
            raise ValueError(f"ambiguous source '{source}': {[str(m) for m in matches]}; pass --country")
        return matches
    pattern = f"{country}/*.parquet" if (country and not do_all) else "*/*.parquet"
    return sorted(root.glob(pattern))


def main():
    ap = argparse.ArgumentParser(description="LeaderSpeech translator (fills English text/title/context in place)")
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--source", help="a single cleaned source_id (e.g. arg_casarosada)")
    sel.add_argument("--country", help="translate every cleaned source under this country folder")
    sel.add_argument("--all", action="store_true", help="translate every cleaned source")
    sel.add_argument("--input", help="translate an arbitrary CSV/Parquet (raw scraped, merged build, ...)")
    ap.add_argument("--output", default=None, help="with --input: write here instead of in place")
    ap.add_argument("--out-root", default="data/cleaned", help="root for --source/--country/--all")
    ap.add_argument("--translator", default=None,
                    help="google | nllb | opusmt. If omitted in an interactive terminal, you'll be "
                         "prompted to pick one (with a GPU-based recommendation); scripts fall back "
                         "to the config default (google).")
    ap.add_argument("--config", default=None, help="path to translate_config.yml (else defaults)")
    ap.add_argument("--limit", type=int, default=None, help="cap rows translated per file this run")
    ap.add_argument("--force", action="store_true", help="re-translate even if the English column is filled")
    ap.add_argument("--all-rows", action="store_true", help="also translate non-accepted rows (overrides only_accepted)")
    args = ap.parse_args()

    _ensure_console()
    config = load_config(args.config)
    if args.translator:
        translator_name = args.translator
    elif sys.stdin.isatty():                       # interactive + no --translator: offer the picker
        from .select import choose_backend
        translator_name, config = choose_backend(config)
    else:
        translator_name = config.translator        # scripted / non-TTY: use the config default
    config = config.model_copy(update={"translator": translator_name})
    if args.all_rows:
        config = config.model_copy(update={"only_accepted": False})

    translator = get_translator(translator_name, config)

    if args.input:
        targets = [Path(args.input)]
        cleaned_mode = False
    else:
        targets = _cleaned_targets(args.out_root, args.source, args.country, args.all)
        cleaned_mode = True

    if not targets:
        print("no target files found")
        return

    summaries = []
    for path in targets:
        out = None if cleaned_mode else args.output
        summaries.append(translate_file(path, translator, config, output=out,
                                        limit=args.limit, force=args.force))

    if cleaned_mode:
        try:  # refresh the derived stage index so is_translated reflects this run
            from ..clean_structure_metadata.merge import build_clean_index
            build_clean_index(args.out_root)
        except Exception as e:
            log.warning("could not refresh clean index: %s", e)

    print(json.dumps(summaries if len(summaries) > 1 else summaries[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
