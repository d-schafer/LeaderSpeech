"""Column-agnostic, atomic table I/O for the translator.

Unlike the cleaner's store (which knows the fixed cleaned schema), translation can run on
ANY table — a raw scraped CSV, a cleaned per-source Parquet, or the merged build — so this
reads/writes by file extension and preserves every column as-is. Writes are atomic
(`.tmp` + `os.replace`, prior file kept as `.bak`), matching the cleaner's crash-safety.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pandas as pd


def read_table(path: str | Path) -> pd.DataFrame:
    """Load a `.parquet` or `.csv` into a DataFrame (CSV read as all-strings, NA-safe)."""
    p = Path(path)
    if p.suffix.lower() == ".parquet":
        return pd.read_parquet(p)
    return pd.read_csv(p, dtype=str, keep_default_na=False)


def write_table_atomic(df: pd.DataFrame, path: str | Path, compression: str = "zstd") -> None:
    """Write `df` to `path` atomically, preserving column order. Format by extension."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    if p.suffix.lower() == ".parquet":
        df.to_parquet(tmp, engine="pyarrow", compression=compression, index=False)
    else:
        df.to_csv(tmp, index=False, encoding="utf-8")
    if p.exists():
        shutil.copy2(p, p.with_suffix(p.suffix + ".bak"))
    # Retry the atomic replace: on Windows a transient lock on the target — Dropbox mid-sync,
    # an antivirus scan, or an open viewer (Excel/RStudio) — briefly denies access. Waiting and
    # retrying is far better than crashing and losing a whole translation run.
    for attempt in range(5):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.5 * (attempt + 1))
