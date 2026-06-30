"""Build a speaker inventory from the cleaned speeches and bucket it against the tenure key.

Deterministic and free (no API). Aggregates speeches into unique (speaker, country) with a
year span and speech count, then uses the cleaner's tolerant tenure matcher to bucket each:
  - matched        -> the speaker is a known leader of that country (tenure_match == exact)
  - wrong_country  -> matches a leader of a DIFFERENT country (likely a foreign visitor)
  - unmatched      -> not in the key at all  (the candidates for new additions)
For matched speakers it also records the tenure year range, so a year-coverage gap (speeches
outside the recorded tenure) is visible.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd

from ..clean_structure_metadata import tenure
from .config import TenureConfig


def _year(value) -> int | None:
    s = str(value or "").strip()
    return int(s[:4]) if len(s) >= 4 and s[:4].isdigit() else None


def load_speeches(config: TenureConfig, input_path: str | None = None) -> tuple[pd.DataFrame, str]:
    """Load the speech table to inventory. Preference: explicit --input, then the final/merged
    datasets, then the cleaned per-source Parquets (accepted rows only). Returns (df, source)."""
    candidates = [input_path] if input_path else list(config.dataset_candidates)
    for c in candidates:
        if c and Path(c).exists():
            df = pd.read_parquet(c) if str(c).endswith(".parquet") else pd.read_csv(c, dtype=str, keep_default_na=False)
            return df, str(c)

    frames = []
    for sp in sorted(Path(config.cleaned_root).glob("*/*.parquet")):
        try:
            d = pd.read_parquet(sp)
        except Exception:
            continue
        if "clean_status" in d.columns:
            d = d[d["clean_status"] == "accepted"]
        frames.append(d)
    if not frames:
        raise FileNotFoundError(
            f"no dataset found ({config.dataset_candidates}) and no cleaned Parquets under {config.cleaned_root}")
    return pd.concat(frames, ignore_index=True), config.cleaned_root


def build_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate speeches into one row per (speaker, country): n_speeches, year span, modal position."""
    df = df.copy()
    df["speaker"] = df.get("speaker", "").fillna("").astype(str).str.strip()
    df["country"] = df.get("country", "").fillna("").astype(str).str.strip()
    df = df[(df["speaker"] != "") & (df["country"] != "")]
    df["__year"] = df.get("date", "").map(_year)
    has_pos = "position" in df.columns

    rows = []
    for (sp, co), g in df.groupby(["speaker", "country"]):
        years = [y for y in g["__year"].tolist() if y]
        positions = ([p for p in g["position"].fillna("").astype(str).str.strip() if p] if has_pos else [])
        modal = Counter(positions).most_common(1)[0][0] if positions else ""
        rows.append({
            "speaker": sp, "country": co, "n_speeches": int(len(g)),
            "min_year": min(years) if years else None,
            "max_year": max(years) if years else None,
            "position": modal,
        })
    return pd.DataFrame(rows).sort_values(["country", "speaker"]).reset_index(drop=True)


def bucket_inventory(inv: pd.DataFrame, tenure_df: pd.DataFrame, window: int = 1) -> pd.DataFrame:
    """Add tenure_match (exact|other_country|none), matched_name, is_ceremonial, and the matched
    leader's tenure year range. `window` is unused at the bucket level (we match country-wide,
    any year), kept for signature symmetry."""
    out = []
    for _, r in inv.iterrows():
        tm, ceremonial, matched = tenure.match_speaker(tenure_df, r["speaker"], r["country"], None)
        tmin = tmax = None
        years_in_tenure = None
        if tm == tenure.EXACT and matched and "year" in tenure_df.columns:
            sub = tenure_df[(tenure_df["country"] == r["country"]) & (tenure_df["speaker"] == matched)]
            yrs = pd.to_numeric(sub["year"], errors="coerce").dropna()
            if len(yrs):
                tmin, tmax = int(yrs.min()), int(yrs.max())
                if r["min_year"] and r["max_year"]:
                    years_in_tenure = bool(r["max_year"] >= tmin and r["min_year"] <= tmax)
        d = r.to_dict()
        d.update({
            "tenure_match": tm,
            "matched_name": matched or "",
            "is_ceremonial": None if pd.isna(ceremonial) else bool(ceremonial),
            "tenure_min_year": tmin,
            "tenure_max_year": tmax,
            "years_in_tenure": years_in_tenure,
        })
        out.append(d)
    return pd.DataFrame(out)


def split_buckets(bucketed: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Partition into matched / wrong_country / unmatched DataFrames."""
    return {
        "matched": bucketed[bucketed["tenure_match"] == tenure.EXACT].reset_index(drop=True),
        "wrong_country": bucketed[bucketed["tenure_match"] == tenure.OTHER_COUNTRY].reset_index(drop=True),
        "unmatched": bucketed[bucketed["tenure_match"] == tenure.NONE].reset_index(drop=True),
    }
