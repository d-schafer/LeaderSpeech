"""Apply APPROVED tenure additions to leader_tenure_final.csv — the gated, careful step.

Consolidates `merge_verified_additions.R`. Reads the researcher-approved outbox, dedupes,
expands each leader's year span into leader-year rows (with country codes pulled from the
existing key), skips any that already exist, and either previews (`--dry-run`, the default)
or appends (`--apply`, which writes a timestamped `.bak` first and refuses to drop any
existing row). It also emits `fixNames` suggestions for the new names.

    python -m leaderspeech.leader_tenure.merge --dry-run     # preview (default)
    python -m leaderspeech.leader_tenure.merge --apply       # write the key (after approval)
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import load_config

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TENURE_COLUMNS = ["speaker", "ISO3N", "country", "year", "matchDF", "COWcode", "stateabb", "ccode", "is_ceremonial"]


def _int(v):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        return int(float(str(v).strip()[:4]))
    except (ValueError, TypeError):
        return None


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes", "y")


def load_approved(outbox_path: str, min_confidence: list[str]) -> pd.DataFrame:
    """Rows to apply: explicit `approved` = yes/no wins; a blank `approved` falls back to the
    GPT verdict (gpt_is_leader true AND confidence in `min_confidence`)."""
    df = pd.read_excel(outbox_path)
    approved = df.get("approved", pd.Series([""] * len(df))).astype(str).str.strip().str.lower()
    say_yes = approved.isin(["y", "yes", "true", "1", "approve", "approved"])
    say_no = approved.isin(["n", "no", "false", "0", "reject", "rejected"])
    gpt_ok = df.get("gpt_is_leader", pd.Series([None] * len(df))).map(_truthy)
    conf = df.get("gpt_confidence", pd.Series([""] * len(df))).astype(str).str.lower()
    gpt_ok &= conf.isin([c.lower() for c in min_confidence])
    keep = say_yes | (gpt_ok & ~say_no)
    return df[keep].copy()


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse duplicate (speaker, country) to one row: widest year span, first role/ceremonial."""
    rows = []
    for (sp, co), g in df.groupby(["speaker", "country"]):
        mins = [_int(x) for x in g.get("min_year", [])]
        maxs = [_int(x) for x in g.get("max_year", [])]
        mins = [m for m in mins if m is not None]
        maxs = [m for m in maxs if m is not None]
        rows.append({
            "speaker": sp, "country": co,
            "min_year": min(mins) if mins else None,
            "max_year": max(maxs) if maxs else None,
            "role": g.get("gpt_actual_role", g.get("role", pd.Series([""]))).dropna().astype(str).iloc[0]
                    if g.get("gpt_actual_role", g.get("role", pd.Series([""]))).notna().any() else "",
            "is_ceremonial": _truthy(g["is_ceremonial"].iloc[0]) if "is_ceremonial" in g.columns else False,
        })
    return pd.DataFrame(rows)


def _country_codes(tenure_df: pd.DataFrame) -> dict[str, dict]:
    cols = [c for c in ("ISO3N", "COWcode", "stateabb", "ccode") if c in tenure_df.columns]
    out = {}
    for c, g in tenure_df.groupby("country"):
        out[c] = {k: g[k].dropna().iloc[0] if g[k].notna().any() else None for k in cols}
    return out


def expand_to_leader_years(approved: pd.DataFrame, tenure_df: pd.DataFrame) -> tuple[pd.DataFrame, set]:
    """Each approved leader's [min_year, max_year] -> leader-year rows with country codes."""
    codes = _country_codes(tenure_df)
    rows, missing = [], set()
    for _, r in approved.iterrows():
        mn, mx = _int(r.get("min_year")), _int(r.get("max_year"))
        if mn is None and mx is None:
            continue
        mn = mn if mn is not None else mx
        mx = mx if mx is not None else mn
        if mx < mn:
            mn, mx = mx, mn
        cc = codes.get(r["country"], {})
        if not cc:
            missing.add(r["country"])
        cer = _truthy(r.get("is_ceremonial"))
        for y in range(mn, mx + 1):
            rows.append({"speaker": r["speaker"], "ISO3N": cc.get("ISO3N"), "country": r["country"],
                         "year": y, "matchDF": "speechOnly", "COWcode": cc.get("COWcode"),
                         "stateabb": cc.get("stateabb"), "ccode": cc.get("ccode"),
                         "is_ceremonial": bool(cer)})
    new = pd.DataFrame(rows, columns=TENURE_COLUMNS)
    if not new.empty and {"speaker", "country", "year"}.issubset(tenure_df.columns):
        existing = tenure_df[["speaker", "country", "year"]].drop_duplicates()
        existing["year"] = pd.to_numeric(existing["year"], errors="coerce")
        new = new.merge(existing, on=["speaker", "country", "year"], how="left", indicator=True)
        new = new[new["_merge"] == "left_only"].drop(columns="_merge").reset_index(drop=True)
    return new, missing


def fixnames_suggestions(approved: pd.DataFrame) -> list[str]:
    """Ready-to-edit fixNames lines + flag surname-only names that need a full-name mapping."""
    lines = ["# Suggested additions for scripts/key_fixNames.R (edit canonical spellings as needed):"]
    for _, r in approved.sort_values(["country", "speaker"]).iterrows():
        sp, co = str(r["speaker"]), str(r["country"])
        if len(sp.split()) == 1:
            lines.append(f'  # {co}: "{sp}" looks like a surname only — map to the full name:')
            lines.append(f'  dataframe$speaker[dataframe$country == "{co}" & dataframe$speaker == "{sp}"] <- "<FULL NAME>"')
        else:
            lines.append(f'  # {co}: confirm canonical form of "{sp}" (add variants if any)')
    return lines


def apply_additions(tenure_path: str, new_rows: pd.DataFrame) -> str:
    """Append `new_rows` to the tenure CSV after a timestamped backup. Refuses to drop rows."""
    tenure_df = pd.read_csv(tenure_path, low_memory=False)
    aligned = new_rows.reindex(columns=tenure_df.columns)
    merged = pd.concat([tenure_df, aligned], ignore_index=True)
    if len(merged) < len(tenure_df):
        raise RuntimeError("refusing to write: merge would drop existing tenure rows")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{tenure_path}.{ts}.bak"
    shutil.copy2(tenure_path, bak)
    merged.to_csv(tenure_path, index=False)
    return bak


def main():
    ap = argparse.ArgumentParser(description="Apply approved tenure additions to leader_tenure_final.csv")
    ap.add_argument("--proposed", default=None, help="outbox path (else config.outbox)")
    ap.add_argument("--tenure", default=None, help="tenure CSV (else config.tenure_file)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--apply", action="store_true", help="actually write (default is a dry-run preview)")
    args = ap.parse_args()

    config = load_config(args.config)
    outbox = args.proposed or config.outbox
    tenure_path = args.tenure or config.tenure_file
    if not Path(outbox).exists():
        print(f"no outbox at {outbox}; run `python -m leaderspeech.leader_tenure.run` first")
        return
    if not Path(tenure_path).exists():
        print(f"tenure key not found at {tenure_path}")
        return

    tenure_df = pd.read_csv(tenure_path, low_memory=False)
    approved = load_approved(outbox, config.min_confidence)
    deduped = dedupe(approved)
    new_rows, missing = expand_to_leader_years(deduped, tenure_df)

    print(f"\nTENURE MERGE  (outbox: {outbox})")
    print(f"  approved leaders:        {len(deduped)}")
    print(f"  new leader-year rows:    {len(new_rows)} (after skipping ones already in the key)")
    if missing:
        print(f"  WARNING missing country codes for: {', '.join(sorted(missing))}")
    if not deduped.empty:
        print("\n  Leaders to add:")
        for _, r in deduped.sort_values(["country", "speaker"]).iterrows():
            cer = "ceremonial" if _truthy(r.get("is_ceremonial")) else "executive"
            print(f"    {r['country']:<20} {r['speaker']:<28} {r['min_year']}-{r['max_year']}  ({cer})")
    print("\n" + "\n".join(fixnames_suggestions(deduped)))

    if not args.apply:
        print("\n--dry-run (default): nothing written. Re-run with --apply to update the key.")
        return
    if new_rows.empty:
        print("\nnothing new to add.")
        return
    bak = apply_additions(tenure_path, new_rows)
    print(f"\nAPPLIED: wrote {len(new_rows)} rows to {tenure_path} (backup: {bak})")
    print("Next: paste the fixNames suggestions above into scripts/key_fixNames.R.")


if __name__ == "__main__":
    main()
