"""Import an already-collected speech table (an earlier project's scrape) as a source.

Some documents were scraped before this tool existed and the site has since deleted them, or
re-fetching them from the Internet Archive would cost hours for text already on disk. This
writes such a table into the corpus exactly as a scrape would have:

  * ``data/scraped/<Country>/<source_id>.csv`` in ``SCHEMA_COLUMNS`` — the original-language
    text in ``*_originlanguage`` for a non-English source, the English columns only where the
    spec maps a real translation of them;
  * ``doc_id`` taken from the country's shared counter in ``data/state/<Country>.json``;
  * every imported URL added to that state file's ``seen_urls``, so any recipe of the country —
    live or Archive — skips those documents (the run compares by page identity, so ``http``,
    ``:80``, ``www.`` and noise-parameter variants of an imported URL are skipped too);
  * ``<source_id>_links.txt`` (the index's denominator), ``<source_id>_import.json`` (where the
    rows came from; the index labels the source ``renderer=import``), and optionally
    ``<source_id>_import_extra.parquet`` — input columns that have no schema column, kept
    verbatim and keyed by ``doc_id`` (Parquet, so no pipeline stage mistakes it for a source).

A DRY RUN by default: it reports what it would write. ``--apply`` writes, after backing up the
state file. Re-running is safe: rows whose URL the state already holds, or the target CSV
already contains, are skipped.

Spec (YAML)::

    source_id: mex_presidencia_amlo_import
    country: Mexico                 # the recipe convention: the tenure key's spelling
    source_language: Spanish
    position: president             # optional
    dataset: LeaderSpeech           # optional
    input: data/imports/Mexico/amlo.csv     # .csv or .parquet; relative to the spec file
    date_languages: [es]            # optional — only for dates that are not ISO already
    columns:                        # schema field -> input column. `source` and `text` required
      source: list
      title: title
      text: text
      context: context
      date: date
    english:                        # optional (non-English sources): English columns in the
      title: title_en               # input that are TRANSLATIONS of the mapped originals
      context: context_en
    extra:                          # optional: kept in <source_id>_import_extra.parquet
      text_en_leader_only: text_en
    identity_noise_params: [idiom]  # optional: the same knobs as a recipe's wayback_noise_params
    identity_strip: ['(?<=/presidencia)/es(?=/)']   # / wayback_identity_strip, used to decide
                                    # that an input row is a document the corpus ALREADY holds
                                    # under another URL form (and to fold twins in the input)
    notes: free text recorded in the sidecar

Run:  python -m leaderspeech.text_scraper.import_legacy --spec <spec.yml> [--apply]
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pandas as pd
import yaml

from . import wayback
from .extract import parse_date
from .run import SCHEMA_COLUMNS, _append, alpha3_for, is_english, load_state, map_to_schema, save_state

log = logging.getLogger(__name__)

SCHEMA_FIELDS = ("source", "title", "text", "context", "date", "speaker")
ENGLISH_FIELDS = ("title", "text", "context")


class ImportSpecError(ValueError):
    pass


def load_spec(path: Path) -> dict:
    spec = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for key in ("source_id", "country", "source_language", "input", "columns"):
        if not spec.get(key):
            raise ImportSpecError(f"spec {path}: '{key}' is required")
    cols = spec["columns"]
    unknown = set(cols) - set(SCHEMA_FIELDS)
    if unknown:
        raise ImportSpecError(f"spec {path}: unknown schema field(s) in columns: {sorted(unknown)}")
    for need in ("source", "text"):
        if need not in cols:
            raise ImportSpecError(f"spec {path}: columns.{need} is required")
    eng = spec.get("english") or {}
    if set(eng) - set(ENGLISH_FIELDS):
        raise ImportSpecError(f"spec {path}: english may map only {ENGLISH_FIELDS}")
    if eng and is_english(spec["source_language"]):
        raise ImportSpecError(f"spec {path}: `english` is for non-English sources; map English "
                              "text through `columns` instead")
    if alpha3_for(spec["country"]) == "XXX":
        raise ImportSpecError(f"spec {path}: country {spec['country']!r} does not resolve in pycountry")
    inp = Path(spec["input"])
    spec["input"] = inp if inp.is_absolute() else (Path(path).parent / inp)
    return spec


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path).astype("string").fillna("")
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def _clean(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def _iso_date(raw: str, languages) -> str:
    raw = _clean(raw)
    if not raw:
        return ""
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-" and raw[:4].isdigit():
        return raw[:10]                      # already ISO (the common case for an R/pandas export)
    return parse_date(raw, languages) or ""


def plan_import(spec: dict, out_root: str = "data/scraped", state_root: str = "data/state") -> dict:
    """Read the input and decide what an import would write. Writes nothing."""
    df = read_table(Path(spec["input"]))
    cols, eng, extra = spec["columns"], spec.get("english") or {}, spec.get("extra") or {}
    missing = [c for c in [*cols.values(), *eng.values(), *extra.values()] if c not in df.columns]
    if missing:
        raise ImportSpecError(f"input {spec['input']} lacks column(s): {missing}")

    country = spec["country"]
    out_dir = Path(out_root) / country
    csv_path = out_dir / f"{spec['source_id']}.csv"
    state_path = Path(state_root) / f"{country}.json"
    state = load_state(state_path)
    held = set(state["seen_urls"]) | set(state["failed_urls"]) | set(state["filtered_urls"])
    if csv_path.exists():
        held |= set(pd.read_csv(csv_path, dtype=str, usecols=["source"])["source"].dropna())
    # Rows already in ANY source of the country, under any URL form: the state file is shared by
    # every recipe of the country, so this also catches an Archive recipe's earlier rows.
    noise = tuple(spec.get("identity_noise_params") or ())
    strips = [re.compile(p) for p in (spec.get("identity_strip") or ())]

    def _pid(u: str) -> str:
        for rx in strips:
            u = rx.sub("", u)
        return wayback.page_identity(u, noise)

    held_ids = {_pid(u) for u in held}

    recipe = SimpleNamespace(
        country=country, iso3n=None, position=spec.get("position") or "",
        source_language=spec["source_language"], dataset=spec.get("dataset") or "LeaderSpeech")
    try:
        import pycountry
        recipe.iso3n = int(pycountry.countries.lookup(country).numeric)
    except Exception:  # noqa: BLE001
        pass

    languages = spec.get("date_languages")
    alpha3 = alpha3_for(country)
    next_num = int(state["last_doc_num"])
    rows, extras, seen_ids = [], [], set()
    skipped = {"no_url": 0, "no_text": 0, "already_held": 0, "duplicate_in_input": 0}
    undated = 0
    for rec in df.to_dict("records"):
        url = _clean(rec[cols["source"]])
        if not url:
            skipped["no_url"] += 1
            continue
        if not _clean(rec[cols["text"]]):
            skipped["no_text"] += 1
            continue
        pid = _pid(url)
        if url in held or pid in held_ids:
            skipped["already_held"] += 1
            continue
        if pid in seen_ids:
            skipped["duplicate_in_input"] += 1
            continue
        seen_ids.add(pid)
        next_num += 1
        doc_id = f"{alpha3}{next_num:04d}"
        date = _iso_date(rec[cols["date"]], languages) if "date" in cols else ""
        undated += not date
        row = map_to_schema({
            "speaker": _clean(rec[cols["speaker"]]) if "speaker" in cols else "",
            "date": date, "source": url,
            "title": _clean(rec[cols["title"]]) if "title" in cols else "",
            "text": _clean(rec[cols["text"]]),
            "context": _clean(rec[cols["context"]]) if "context" in cols else "",
        }, recipe, doc_id)
        for field, col in eng.items():
            row[field] = _clean(rec[col])
        rows.append(row)
        if extra:
            extras.append({"doc_id": doc_id, **{k: _clean(rec[c]) for k, c in extra.items()}})

    dates = sorted(r["date"] for r in rows if r["date"])
    return {
        "spec": spec, "csv_path": csv_path, "state_path": state_path, "state": state,
        "rows": rows, "extras": extras, "input_rows": len(df), "skipped": skipped,
        "undated": undated, "date_min": dates[0] if dates else "", "date_max": dates[-1] if dates else "",
        "doc_first": rows[0]["doc_id"] if rows else "", "doc_last": rows[-1]["doc_id"] if rows else "",
    }


def apply_import(plan: dict) -> None:
    """Write what `plan_import` decided: CSV rows, link list, extras, sidecar, then the state."""
    rows, spec = plan["rows"], plan["spec"]
    if not rows:
        log.info("nothing to import")
        return
    csv_path, state_path, state = plan["csv_path"], plan["state_path"], plan["state"]
    out_dir = csv_path.parent
    sid = spec["source_id"]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    if state_path.exists():
        backup = state_path.with_name(f"{state_path.name}.bak-import-{stamp}")
        shutil.copy2(state_path, backup)
        log.info("state backed up -> %s", backup.name)

    _append(csv_path, rows, SCHEMA_COLUMNS)

    links_path = out_dir / f"{sid}_links.txt"
    old = links_path.read_text(encoding="utf-8").split() if links_path.exists() else []
    links = list(dict.fromkeys([*old, *(r["source"] for r in rows)]))
    links_path.write_text("\n".join(links) + "\n", encoding="utf-8")

    if plan["extras"]:
        extra_path = out_dir / f"{sid}_import_extra.parquet"
        new = pd.DataFrame(plan["extras"])
        if extra_path.exists():
            new = pd.concat([pd.read_parquet(extra_path), new], ignore_index=True)
        new.to_parquet(extra_path, index=False)

    # The state LAST: if anything above failed, the URLs are not marked seen and a re-run (which
    # also skips URLs already in the target CSV) completes the import without duplicating rows.
    state["seen_urls"] = sorted(set(state["seen_urls"]) | {r["source"] for r in rows})
    state["last_doc_num"] = int(plan["doc_last"][len(alpha3_for(spec["country"])):])
    save_state(state_path, state)

    sidecar = out_dir / f"{sid}_import.json"
    history = json.loads(sidecar.read_text(encoding="utf-8")).get("imports", []) if sidecar.exists() else []
    history.append({
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "input": str(spec["input"]),
        "rows": len(rows), "doc_ids": [plan["doc_first"], plan["doc_last"]],
        "date_span": [plan["date_min"], plan["date_max"]],
        "columns": spec["columns"], "english": spec.get("english") or {},
        "extra": spec.get("extra") or {}, "skipped": plan["skipped"],
    })
    sidecar.write_text(json.dumps({
        "source_id": sid, "country": spec["country"], "source_language": spec["source_language"],
        "notes": spec.get("notes") or "", "imports": history,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("imported %d row(s) %s..%s -> %s; %d URL(s) marked seen in %s",
             len(rows), plan["doc_first"], plan["doc_last"], csv_path, len(rows), state_path.name)


def report(plan: dict) -> str:
    spec, rows = plan["spec"], plan["rows"]
    lines = [
        f"source_id   {spec['source_id']}  ({spec['country']}, {spec['source_language']})",
        f"input       {spec['input']}  ({plan['input_rows']} rows)",
        f"to import   {len(rows)} rows  doc_id {plan['doc_first']}..{plan['doc_last']}  "
        f"dates {plan['date_min']}..{plan['date_max']}  undated {plan['undated']}",
        f"skipped     {plan['skipped']}",
        f"writes      {plan['csv_path']}  (+ _links.txt, _import.json"
        f"{', _import_extra.parquet' if plan['extras'] else ''}) and {len(rows)} URL(s) into "
        f"{plan['state_path']} (last_doc_num {plan['state']['last_doc_num']} -> "
        f"{plan['doc_last'][3:] if rows else plan['state']['last_doc_num']})",
    ]
    if rows:
        r = {k: str(v) for k, v in rows[0].items() if str(v)}
        lines.append("first row   " + json.dumps({k: (v[:80] + "…" if len(v) > 80 else v)
                                                  for k, v in r.items()}, ensure_ascii=False))
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Import an already-collected speech table as a source")
    ap.add_argument("--spec", required=True, help="import spec YAML (see the module docstring)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run, report only)")
    ap.add_argument("--out-root", default="data/scraped")
    ap.add_argument("--state-root", default="data/state")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    plan = plan_import(load_spec(Path(args.spec)), args.out_root, args.state_root)
    print(report(plan))
    if args.apply:
        apply_import(plan)
    else:
        print("\nDRY RUN — nothing written. Re-run with --apply to import.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
