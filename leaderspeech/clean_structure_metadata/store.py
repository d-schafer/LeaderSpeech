"""Parquet I/O for the per-source cleaned store, plus the resume diff.

The per-source Parquet is the canonical incremental store AND the ledger of what's
been cleaned. Writes are whole-file and ATOMIC (`.tmp` + `os.replace`, prior file kept
as `.bak`), so an interrupted run never corrupts the file and an incremental re-run can
only grow it — see the safety invariant in docs/cleaning.md.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pandas as pd


def _retry_win_lock(fn, *args, attempts: int = 6, delay: float = 0.4):
    """Run a filesystem op, retrying if Windows transiently rejects it with a lock
    (PermissionError — WinError 5 'access denied' / 32 'in use'). The usual cause under a
    Dropbox or OneDrive folder, or with antivirus, is the destination being held for a moment
    during sync/scan; a short backoff clears it. Re-raises with a hint if it never releases."""
    last = None
    for i in range(attempts):
        try:
            return fn(*args)
        except PermissionError as e:
            last = e
            time.sleep(delay * (i + 1))
    raise PermissionError(
        f"{last} — the file stayed locked after {attempts} retries. On Windows this is almost "
        f"always Dropbox/OneDrive or antivirus holding the file during sync/scan. Pause syncing on "
        f"data/cleaned (or move the data tree outside the synced folder) and re-run."
    ) from last

# The 15 standardized scraper columns (carried through unchanged for mergeability).
SCRAPED_COLUMNS = [
    "doc_id", "country", "ISO3N", "speaker", "position",
    "context", "context_originlanguage",
    "title", "title_originlanguage",
    "text", "text_originlanguage",
    "date", "source", "source_language", "dataset",
]

# Columns the cleaner adds.
CLEAN_COLUMNS = [
    "speaker_scraped", "date_scraped",           # audit copies of the originals
    "document_type", "is_first_person", "is_substantive", "inclusion_tier",
    "speaker_type", "audience", "speech_type", "venue",
    "detected_language",
    "speaker_attributed_correct", "date_matches_metadata",
    "tenure_match", "tenure_matched_name", "is_ceremonial",
    "clean_status", "gate_reason",
    "clean_confidence", "clean_reasoning", "clean_model", "cleaned_at",
]

CLEANED_COLUMNS = SCRAPED_COLUMNS + CLEAN_COLUMNS

# clean_status values that mean "tried but the API/parse failed" — re-done only with --retry-failed
ERROR_STATUSES = {"error_api", "error_parse"}


def empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=CLEANED_COLUMNS)


def read_source(path: str | Path) -> pd.DataFrame:
    """Load the per-source Parquet, or an empty frame if it doesn't exist yet."""
    p = Path(path)
    if not p.exists():
        return empty_frame()
    df = pd.read_parquet(p)
    for col in CLEANED_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA
    return df


def read_input(path: str | Path) -> pd.DataFrame:
    """Read an ARBITRARY input table (the column-agnostic input side, unlike `read_source`).

    Dispatches by extension: `.parquet` via pyarrow, anything else via `read_csv` (pandas
    auto-decompresses `.csv.gz`). Cells are normalized to strings with blanks for missing
    values, matching the per-source CSV path (`dtype=str, keep_default_na=False`) so the rest
    of the pipeline — which assumes string values (`.strip()`, `date[:4]`) — is unchanged.
    The fixed cleaned schema is NOT imposed here; extra columns are preserved."""
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        df = pd.read_parquet(p)
        # match the CSV branch: NA -> "" and every cell a str (parquet may carry
        # Timestamp / numeric ISO3N; downstream treats these fields as opaque strings)
        return df.astype(object).where(df.notna(), "").astype(str)
    return pd.read_csv(p, dtype=str, keep_default_na=False)


def write_source_atomic(df: pd.DataFrame, path: str | Path, compression: str = "zstd") -> None:
    """Write `df` to `path` atomically: serialize to `<path>.tmp`, keep the previous file
    as `<path>.bak`, then `os.replace` the temp over the target (an atomic swap, so the
    target is always a complete file)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # stable column order; keep any extra columns at the end
    ordered = [c for c in CLEANED_COLUMNS if c in df.columns]
    extra = [c for c in df.columns if c not in CLEANED_COLUMNS]
    out = df[ordered + extra]
    tmp = p.with_suffix(p.suffix + ".tmp")
    out.to_parquet(tmp, engine="pyarrow", compression=compression, index=False)
    if p.exists():
        _retry_win_lock(shutil.copy2, p, p.with_suffix(p.suffix + ".bak"))
    # atomic swap, retried through transient Dropbox/antivirus locks on Windows (WinError 5/32)
    _retry_win_lock(os.replace, tmp, p)


def done_and_failed(df: pd.DataFrame) -> tuple[set, set]:
    """From an existing cleaned frame, return (done_ids, failed_ids):
    done = processed successfully (accepted or rejected); failed = error rows."""
    if df.empty or "doc_id" not in df.columns:
        return set(), set()
    status = df.get("clean_status")
    ids = df["doc_id"].astype(str)
    if status is None:
        return set(ids), set()
    is_err = status.isin(ERROR_STATUSES)
    return set(ids[~is_err]), set(ids[is_err])
