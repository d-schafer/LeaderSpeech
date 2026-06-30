"""Per-source orchestration: read a scraped CSV, clean only the NEW speeches, and
keep the per-source Parquet up to date. Resumable and crash-safe — structure mirrors
`text_scraper/run.py`'s `scrape_recipe` (state, checkpointing, circuit breaker,
finally-flush, log handler, index refresh).

`clean_source(...)` handles ONE source; run.py loops it over a country / all sources.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import extract, gate, llm, store, tenure
from .config import CleanConfig

log = logging.getLogger("leaderspeech.clean_structure_metadata.pipeline")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


# --------------------------------------------------------------------------- logging
_FMT = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")


def _ensure_console():
    pkg = logging.getLogger("leaderspeech.clean_structure_metadata")
    pkg.setLevel(logging.INFO)
    if not any(type(h) is logging.StreamHandler for h in pkg.handlers):
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(_FMT)
        pkg.addHandler(sh)
    return pkg


def _add_log_file(out_dir: Path, source_id: str):
    pkg = _ensure_console()
    fmt = _FMT
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"{source_id}_{ts}.log"
    fh = logging.FileHandler(path, encoding="utf-8")
    fh.setFormatter(fmt)
    pkg.addHandler(fh)
    return path, fh


# ----------------------------------------------------------------------- source discovery
def iter_sources(in_root: str, country: str | None = None) -> list[tuple[str, str, Path]]:
    """List (source_id, country, csv_path) for every scraped CSV under in_root,
    optionally limited to one country. Skips the scraper's `_errors.csv` sidecars."""
    root = Path(in_root)
    pattern = f"{country}/*.csv" if country else "*/*.csv"
    out = []
    for csv_path in sorted(root.glob(pattern)):
        if csv_path.name.endswith("_errors.csv"):
            continue
        out.append((csv_path.stem, csv_path.parent.name, csv_path))
    return out


def _locate_csv(in_root: str, source_id: str, country: str | None) -> tuple[Path, str]:
    root = Path(in_root)
    if country:
        p = root / country / f"{source_id}.csv"
        if not p.exists():
            raise FileNotFoundError(f"no scraped CSV at {p}")
        return p, country
    matches = [p for p in root.glob(f"*/{source_id}.csv") if not p.name.endswith("_errors.csv")]
    if not matches:
        raise FileNotFoundError(f"no scraped CSV '{source_id}.csv' under {root}")
    if len(matches) > 1:
        raise ValueError(f"ambiguous source_id '{source_id}': {[str(m) for m in matches]}; pass --country")
    return matches[0], matches[0].parent.name


# ---------------------------------------------------------------------------- enrichment
def _norm(v) -> str:
    return (v or "").strip().lower() if isinstance(v, str) else ""


def _year_of(date_str) -> int | None:
    s = (date_str or "").strip()
    return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None


def _locate_parquet(out_root: str, source_id: str, country: str | None) -> tuple[Path, str]:
    root = Path(out_root)
    if country:
        p = root / country / f"{source_id}.parquet"
        if not p.exists():
            raise FileNotFoundError(f"no cleaned Parquet at {p}")
        return p, country
    matches = list(root.glob(f"*/{source_id}.parquet"))
    if not matches:
        raise FileNotFoundError(f"no cleaned Parquet '{source_id}.parquet' under {root}")
    if len(matches) > 1:
        raise ValueError(f"ambiguous source_id '{source_id}': {[str(m) for m in matches]}; pass --country")
    return matches[0], matches[0].parent.name


def regate_source(
    source_id: str, *, out_root: str = "data/cleaned",
    config: CleanConfig | None = None, country: str | None = None,
) -> dict:
    """Re-apply the gate to an already-cleaned source using the STORED extraction fields
    (document_type / speaker / speaker_type) — no API calls. Lets you change
    `keep_document_types` / `require_leader_type` and re-classify for free, without
    re-spending or losing anything. Error rows are left untouched (retry those instead)."""
    config = config or CleanConfig()
    _ensure_console()
    p, country = _locate_parquet(out_root, source_id, country)
    df = store.read_source(p)
    summary = {"source_id": source_id, "country": country, "regated": 0, "changed": 0, "output": str(p)}
    if df.empty:
        return summary
    changed = 0
    for i in df.index:
        status_now = str(df.at[i, "clean_status"]) if "clean_status" in df.columns else ""
        if status_now.startswith("error"):
            continue
        meta = {
            "document_type": df.at[i, "document_type"] if "document_type" in df.columns else None,
            "speaker": df.at[i, "speaker"],
            "speaker_type": df.at[i, "speaker_type"] if "speaker_type" in df.columns else None,
        }
        new_status, new_reason = gate.decide(meta, config)
        if new_status != status_now:
            df.at[i, "clean_status"] = new_status
            df.at[i, "gate_reason"] = new_reason
            changed += 1
    store.write_source_atomic(df, p, config.compression)
    try:
        from .merge import build_clean_index
        build_clean_index(out_root)
    except Exception:
        pass
    summary.update(regated=len(df), changed=changed)
    log.info("REGATE %s | rows=%d changed=%d -> %s", source_id, len(df), changed, p)
    return summary


def _base_row(row: dict) -> dict:
    """Carry the 15 scraped columns through + record audit copies."""
    out = {c: row.get(c, "") for c in store.SCRAPED_COLUMNS}
    out["speaker_scraped"] = row.get("speaker", "")
    out["date_scraped"] = row.get("date", "")
    for c in store.CLEAN_COLUMNS:
        out.setdefault(c, None)
    return out


def _error_row(row: dict, status: str, detail: str) -> dict:
    out = _base_row(row)
    out["clean_status"] = status
    out["gate_reason"] = detail[:300]
    out["clean_model"] = None
    out["cleaned_at"] = datetime.now().isoformat(timespec="seconds")
    return out


def enrich(row: dict, meta: dict, tenure_df, config: CleanConfig) -> dict:
    """Combine a scraped row with the extraction meta + tenure crosscheck + gate."""
    out = _base_row(row)

    # field corrections
    scraped_speaker = (row.get("speaker") or "").strip()
    meta_speaker = (meta.get("speaker") or "").strip()
    if not scraped_speaker and meta_speaker:
        out["speaker"] = meta_speaker
    elif _norm(meta.get("speaker_attributed_correct")) == "no" and meta_speaker:
        out["speaker"] = meta_speaker
    # else keep scraped speaker

    if not (row.get("position") or "").strip() and (meta.get("position") or "").strip():
        out["position"] = meta["position"].strip()

    scraped_date = (row.get("date") or "").strip()
    meta_date = (meta.get("date") or "").strip()
    if not scraped_date and meta_date:
        out["date"] = meta_date
    elif _norm(meta.get("date_matches_metadata")) == "no" and meta_date:
        out["date"] = meta_date

    # tenure crosscheck on the (possibly corrected) speaker + date
    if tenure_df is not None:
        tm, ceremonial, matched = tenure.match_speaker(
            tenure_df, out["speaker"], out.get("country", ""),
            _year_of(out["date"]), window=config.tenure_window,
        )
        out["tenure_match"] = tm
        out["tenure_matched_name"] = matched or None
        out["is_ceremonial"] = None if pd.isna(ceremonial) else bool(ceremonial)

    # extracted metadata
    out["document_type"] = meta.get("document_type")
    out["is_first_person"] = meta.get("is_first_person")
    out["speaker_type"] = meta.get("speaker_type")
    out["audience"] = meta.get("audience")
    out["speech_type"] = meta.get("speech_type")
    out["venue"] = meta.get("venue")
    out["detected_language"] = meta.get("language")
    out["speaker_attributed_correct"] = meta.get("speaker_attributed_correct")
    out["date_matches_metadata"] = meta.get("date_matches_metadata")
    out["clean_confidence"] = meta.get("confidence")
    out["clean_reasoning"] = meta.get("reasoning")
    out["clean_model"] = config.model
    out["cleaned_at"] = datetime.now().isoformat(timespec="seconds")

    status, reason = gate.decide(meta, config)
    out["clean_status"] = status
    out["gate_reason"] = reason
    return out


def _is_empty_meta(meta: dict) -> bool:
    return all(meta.get(k) is None for k in extract.META_FIELDS)


# ------------------------------------------------------------------------------- driver
def clean_source(
    source_id: str,
    *,
    in_root: str = "data/scraped",
    out_root: str = "data/cleaned",
    state_root: str = "data/clean_state",
    config: CleanConfig | None = None,
    model: str | None = None,
    country: str | None = None,
    limit: int | None = None,
    retry_failed: bool = False,
    dry_run: bool = False,
    save_every_chunks: int = 1,
) -> dict:
    config = config or CleanConfig()
    if model:
        config = config.model_copy(update={"model": model})

    csv_path, country = _locate_csv(in_root, source_id, country)
    out_path = Path(out_root) / country / f"{source_id}.parquet"
    state_path = Path(state_root) / country / f"{source_id}.json"

    scraped = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    scraped["doc_id"] = scraped["doc_id"].astype(str)

    # tenure key (optional but expected)
    tenure_missing = not Path(config.tenure_file).exists()
    tenure_df = None if tenure_missing else tenure.get_tenure(str(config.tenure_file))

    existing = store.read_source(out_path)
    if not existing.empty:
        existing["doc_id"] = existing["doc_id"].astype(str)
    done, failed = store.done_and_failed(existing)
    skip = done if retry_failed else (done | failed)

    todo = scraped[~scraped["doc_id"].isin(skip)].copy()
    if limit:
        todo = todo.head(limit)
    todo_ids = set(todo["doc_id"])
    keep = existing[~existing["doc_id"].isin(todo_ids)] if not existing.empty else store.empty_frame()

    summary = {
        "source_id": source_id, "country": country, "model": config.model,
        "scraped_total": len(scraped), "to_clean": len(todo),
        "cleaned_this_run": 0, "accepted": 0, "rejected": 0, "errors": 0,
        "output": str(out_path), "log": "", "dry_run": dry_run,
    }

    # A no-op (dry-run, or nothing new to clean) must NOT create output dirs / log files.
    if dry_run or todo.empty:
        _ensure_console()
        if tenure_missing:
            log.warning("tenure file not found at %s -- crosscheck disabled", config.tenure_file)
        if dry_run:
            log.info("DRY RUN -- would clean %d of %d scraped speeches; no API calls made",
                     len(todo), len(scraped))
        else:
            log.info("nothing to clean -- all %d scraped speeches already processed", len(scraped))
        return summary

    # real run from here: attach a per-source timestamped file log
    log_path, log_handler = _add_log_file(out_path.parent, source_id)
    summary["log"] = str(log_path)
    log.info("START %s (%s) | model=%s limit=%s retry_failed=%s",
             source_id, country, config.model, limit, retry_failed)
    if tenure_missing:
        log.warning("tenure file not found at %s -- tenure crosscheck disabled", config.tenure_file)
    log.info("scraped=%d | already_done=%d known_failed=%d | to_clean=%d",
             len(scraped), len(done), len(failed), len(todo))

    # build items
    items = []
    for _, r in todo.iterrows():
        row = r.to_dict()
        year = _year_of(row.get("date"))
        leaders_info = ""
        if tenure_df is not None:
            leaders = tenure.leaders_for(tenure_df, row.get("country", ""), year, config.tenure_window)
            leaders_info = ", ".join(leaders)
        msg = extract.build_user_message(row, leaders_info, max_words=config.max_words)
        items.append({"row": row, "message": msg})

    api_key = llm.load_api_key(config)
    client = llm.create_async_client(api_key)

    new_rows: list[dict] = []
    counters = {"accepted": 0, "rejected": 0, "errors": 0, "chunks": 0, "consecutive_fail": 0}
    aborted = {"flag": False}

    async def worker(item, sem):
        return await extract.extract_one(client, config, item["message"], sem)

    def _save_state():
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "source_id": source_id, "country": country, "model": config.model,
            "scraped_total": len(scraped),
            "cleaned_total": len(keep) + len(new_rows),
            "this_run": dict(counters), "last_run": datetime.now().isoformat(timespec="seconds"),
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _flush():
        df_out = pd.concat(
            [keep, pd.DataFrame(new_rows, columns=store.CLEANED_COLUMNS)], ignore_index=True
        ) if new_rows else keep
        store.write_source_atomic(df_out, out_path, config.compression)
        _save_state()

    def on_chunk(chunk, results):
        chunk_fail = 0
        for item, res in zip(chunk, results):
            if isinstance(res, Exception):
                new_rows.append(_error_row(item["row"], "error_api", f"{type(res).__name__}: {res}"))
                counters["errors"] += 1
                chunk_fail += 1
            elif _is_empty_meta(res):
                new_rows.append(_error_row(item["row"], "error_parse", "empty/unparseable model reply"))
                counters["errors"] += 1
                chunk_fail += 1
            else:
                cleaned = enrich(item["row"], res, tenure_df, config)
                new_rows.append(cleaned)
                if cleaned["clean_status"] == gate.ACCEPTED:
                    counters["accepted"] += 1
                else:
                    counters["rejected"] += 1
        counters["consecutive_fail"] = counters["consecutive_fail"] + chunk_fail if chunk_fail == len(chunk) else 0
        counters["chunks"] += 1
        if counters["chunks"] % save_every_chunks == 0:
            _flush()
        log.info("progress %d/%d | accepted=%d rejected=%d errors=%d",
                 len(new_rows), len(todo), counters["accepted"], counters["rejected"], counters["errors"])
        if counters["consecutive_fail"] >= config.max_consecutive_failures:
            aborted["flag"] = True
            raise RuntimeError(f"aborting after {counters['consecutive_fail']} consecutive API failures")

    try:
        asyncio.run(llm.run_async_batches(
            items, worker, batch_size=config.batch_size,
            chunk_size=config.chunk_size, on_chunk=on_chunk,
        ))
    except RuntimeError as e:
        log.error("%s — partial results flushed", e)
    except Exception:
        log.exception("FATAL during cleaning — partial results flushed")
        raise
    finally:
        _flush()
        try:
            client_close = getattr(client, "close", None)
            if client_close:
                asyncio.run(client.close())
        except Exception:
            pass
        summary.update(
            cleaned_this_run=len(new_rows), accepted=counters["accepted"],
            rejected=counters["rejected"], errors=counters["errors"],
            aborted_early=aborted["flag"],
        )
        log.info("DONE %s | cleaned=%d accepted=%d rejected=%d errors=%d%s | out=%s",
                 source_id, len(new_rows), counters["accepted"], counters["rejected"],
                 counters["errors"], " | ABORTED" if aborted["flag"] else "", out_path)
        try:
            from .merge import build_clean_index
            build_clean_index(out_root)
        except Exception as e:
            log.warning("could not refresh clean index: %s", e)
        logging.getLogger("leaderspeech.clean_structure_metadata").removeHandler(log_handler)
        log_handler.close()

    return summary
