"""Crosscheck a speech's speaker against `leader_tenure_final.csv` (the authoritative
leader-tenure key: one row per leader-year, with `is_ceremonial`).

We match TOLERANTLY rather than by exact string: the GPT-extracted name is
accent-stripped, lowercased, and compared by surname containment against the leaders
known to be in office for the country/year. Authoritative canonical-name
standardization (the `key_fixNames.R` key) is applied later, in the R export step;
here we only need a good-enough flag (`exact` / `other_country` / `none`) plus the
matched leader's `is_ceremonial`.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

# tenure_match values
EXACT = "exact"            # speaker matches a leader in office for this country+year
OTHER_COUNTRY = "other_country"  # matches a leader of a DIFFERENT country (likely a visitor / wrong-country)
NONE = "none"             # no tenure match


def load_tenure(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"speaker": str, "country": str}, low_memory=False)
    df["_speaker_norm"] = df["speaker"].map(normalize)
    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce")
    if "is_ceremonial" not in df.columns:
        df["is_ceremonial"] = pd.NA
    return df


def normalize(name) -> str:
    """Accent-strip + lowercase + collapse whitespace; '' for missing."""
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = str(name)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def _year_of(date_str) -> int | None:
    if date_str is None or (isinstance(date_str, float) and pd.isna(date_str)):
        return None
    s = str(date_str).strip()
    if len(s) >= 4 and s[:4].isdigit():
        return int(s[:4])
    return None


def leaders_for(df: pd.DataFrame, country: str, year: int | None, window: int = 1) -> list[str]:
    """Unique leader names in office in `country` within `year` +/- `window`."""
    if not country:
        return []
    mask = df["country"] == country
    if year is not None and "year" in df.columns:
        mask &= df["year"].between(year - window, year + window)
    return df.loc[mask, "speaker"].dropna().unique().tolist()


def _surname_match(a_norm: str, b_norm: str) -> bool:
    """True if the names plausibly refer to the same person: equal, one contains the
    other, or they share a 'surname-like' token (length > 2)."""
    if not a_norm or not b_norm:
        return False
    if a_norm == b_norm or a_norm in b_norm or b_norm in a_norm:
        return True
    a_tokens = {t for t in a_norm.split() if len(t) > 2}
    b_tokens = {t for t in b_norm.split() if len(t) > 2}
    return bool(a_tokens & b_tokens)


def match_speaker(
    df: pd.DataFrame, speaker: str, country: str, year: int | None, window: int = 1
) -> tuple[str, object, str]:
    """Return (tenure_match, is_ceremonial, matched_name).

    - `exact`: speaker matches a leader in office for this country+year.
    - `other_country`: no country+year match, but the speaker matches a tenure leader
      of a different country (a likely foreign visitor or wrong-country attribution).
    - `none`: no match anywhere.
    `is_ceremonial` is the matched country+year leader's value (else pd.NA)."""
    sp = normalize(speaker)
    if not sp:
        return NONE, pd.NA, ""

    # 1) country + year
    if country:
        mask = df["country"] == country
        if year is not None and "year" in df.columns:
            mask &= df["year"].between(year - window, year + window)
        sub = df.loc[mask]
        for _, r in sub.iterrows():
            if _surname_match(sp, r["_speaker_norm"]):
                return EXACT, r.get("is_ceremonial", pd.NA), r["speaker"]

    # 2) any tenure leader of a DIFFERENT country (any year)
    other = df.loc[df["country"] != country] if country else df
    for _, r in other.iterrows():
        if _surname_match(sp, r["_speaker_norm"]):
            return OTHER_COUNTRY, pd.NA, r["speaker"]

    return NONE, pd.NA, ""


@lru_cache(maxsize=4)
def get_tenure(path: str) -> pd.DataFrame:
    """Cached loader so a multi-source run reads the tenure CSV once."""
    return load_tenure(path)
