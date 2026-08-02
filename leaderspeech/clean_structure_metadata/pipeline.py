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
from typing import NamedTuple

import pandas as pd

from .. import datetext
from . import extract, gate, jalali, llm, store, tenure
from .config import CleanConfig

log = logging.getLogger("leaderspeech.clean_structure_metadata.pipeline")

# Defaults for resolve_date when no config is passed (tests and legacy callers). Built once:
# CleanConfig() reads nothing from disk, so this is just the default knob values.
_CONFIG_FOR_DATES = CleanConfig()

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


class DateResolution(NamedTuple):
    """Result of `resolve_date`: the chosen `date`, a `precision`/source label, the model's raw
    suggested date (`model_date`, for audit), a `disagreement` flag (the candidates conflicted and
    the row wants a human), the raw deterministic `parsed` value, the raw head-line regex parse
    (`regex`, recorded win or lose), and `is_fallback` (the date is ONLY the capture bound).
    Field order keeps `[0]`/`[1]` == (date, precision) for legacy positional use."""
    date: str
    precision: str | None
    model_date: str | None = None
    disagreement: bool = False
    parsed: str | None = None
    regex: str | None = None
    is_fallback: bool = False


def resolve_date(
    row: dict, meta: dict | None = None, *, flag_years: int = 5, config=None,
) -> DateResolution:
    """Best available date for a row. TWO TIERS OF TRUST.

    TIER 1 — the recipe's own date SELECTOR (`row["date"]`) is authoritative. It is the site's own
    machine-readable date field. The model still checks it and agreement is the expected case, but on
    disagreement the SELECTOR VALUE STAYS and the row is flagged for a human: a systematic mismatch
    means the RECIPE is broken (this is how `geo_president_wayback`'s DD.MM-vs-MM.DD misparse
    surfaces), and silently overwriting it would hide the bug instead of fixing it.

    TIER 2 — everything else is a proposal, and the MODEL OUTRANKS ALL OF IT. A head-line regex date
    and a Wayback capture date are both weak evidence:
      * the regex can only ever see the top of the document (see leaderspeech/datetext.py);
      * the capture date is when the Internet Archive CRAWLED the page — a hard upper bound, never
        the answer, and often years late.
    So: jalali(text) > model > regex > capture. When nothing beats the capture bound, `is_fallback`
    is set, which is the honest record that this row's date is only an upper bound.

    `meta` (the model reply) is consulted at enrich time; pass None pre-LLM. `flag_years` is the max
    tolerated year gap before a text-derived date is treated as suspect. Every candidate is returned
    for audit whether or not it won.
    """
    cfg = config if config is not None else _CONFIG_FOR_DATES
    text = row.get("text_originlanguage") or row.get("text") or ""
    jiso, jprec = jalali.parse_jalali(text)

    riso = None
    if getattr(cfg, "date_text_enabled", True):
        riso, _ = datetext.parse_text_head(
            text,
            lines=getattr(cfg, "date_text_lines", 4),
            max_line_chars=getattr(cfg, "date_text_max_line_chars", 60),
            min_year=getattr(cfg, "date_text_min_year", 1990),
            languages=datetext.lang_hint(row),
            use_dateparser=getattr(cfg, "date_text_dateparser", True),
        )

    selector = (row.get("date") or "").strip()
    wb = (row.get("wayback_capture") or "").strip()
    model_date = (meta.get("date") or "").strip() if meta is not None else ""
    model_says_no = (_norm(meta.get("date_matches_metadata")) == "no") if meta is not None else False

    # the deterministic TEXT candidate: a Jalali date (preferred -- exact calendar conversion)
    # else the head-line regex parse.
    if jiso:
        text_cand, text_prec = jiso, jprec
    elif riso:
        text_cand, text_prec = riso, "regex_text"
    else:
        text_cand, text_prec = "", None

    cap_y = _year_of(wb)
    sel_y, cand_y, model_y = _year_of(selector), _year_of(text_cand), _year_of(model_date)

    def _bounded(y: int | None) -> bool:
        """A candidate cannot be dated AFTER the capture: a page cannot be archived before the
        speech existed. With no capture column (~30 older wayback CSVs) there is nothing to check."""
        return y is not None and (cap_y is None or y <= cap_y)

    # A text-derived date has no context of its own, so it must clear the capture bound.
    #
    # The `flag_years` GAP check applies to a JALALI parse only, NOT to the head-line regex. A
    # Jalali date is found anywhere in the body, so one sitting decades from the capture is almost
    # certainly a stray institutional/founding date. The regex, by contrast, is structurally
    # constrained to a dateline at the top of the document -- and an archived page crawled years
    # after it was published is the NORMAL case, not a suspicious one: uzb_president_english_wayback
    # is 2016 speeches captured in 2024. Applying the gap check to it would reject every one of the
    # ~5,000 rows this exists to recover.
    text_credible = bool(text_cand) and _bounded(cand_y)
    if jiso and text_credible and cap_y is not None and cand_y is not None:
        text_credible = abs(cand_y - cap_y) <= flag_years

    # The model merely ECHOING the capture date is not an answer -- it is the model telling us it
    # could do no better. Promoting it would launder a crawl timestamp into a "model" date. It is
    # NOT a disagreement either, so the two conditions are kept apart.
    model_bounded = bool(model_date) and _bounded(model_y)
    model_ok = model_bounded and model_date != wb
    text_first = bool(getattr(cfg, "date_text_first", False))

    # --- what wants a human's attention ---------------------------------------------------------
    disagreement = False
    if model_says_no:                              # the model read the text and says the date is wrong
        disagreement = True
    if text_cand and not text_credible:            # impossible or implausibly far from the capture
        disagreement = True
    if model_date and not model_bounded:           # the model proposed a post-capture date
        disagreement = True
    if model_y is not None and sel_y is not None and abs(model_y - sel_y) > flag_years:
        disagreement = True                        # recipe bug or model error -- a human decides

    # --- choose, in order of trust --------------------------------------------------------------
    is_fallback = False
    if jiso and text_credible and not model_says_no:
        # Jalali keeps the top slot it has always had: it is an exact calendar conversion of an
        # explicit date, and it exists because Persian/Dari CMS dates were the untrustworthy ones.
        final, prec = jiso, jprec
    elif selector and not text_first:
        # TIER 1: the site's own field. Kept even when the model disagrees -- the row is flagged
        # instead, because a systematic mismatch is a RECIPE bug and overwriting would hide it.
        final, prec = selector, "scraped"
    elif model_ok:
        final, prec = model_date, "model"          # TIER 2: beats the regex AND the capture, always
    elif text_credible:
        final, prec = text_cand, text_prec
    elif selector:
        final, prec = selector, "scraped"          # date_text_first was set, but nothing beat it
    elif wb:
        final, prec = wb, "wayback_capture"        # an upper bound, never asserted as correct
        is_fallback = True
    else:
        final, prec = "", None

    return DateResolution(final, prec, model_date or None, disagreement,
                          text_cand or None, riso or None, is_fallback)


def _inclusion_tier(document_type, is_first_person, is_substantive=None) -> str | None:
    """A single ordinal handle on the strict->broad inclusion spectrum, derived from
    document_type + is_first_person + is_substantive, so a dataset user filters by strictness
    without re-deriving the boolean logic every time:
      1_speech                 -- a delivered speech or interview (the leader speaking directly)
      2_first_person_statement -- an official statement in the leader's OWN words (first person)
      3_third_person_statement -- an official statement/communique ABOUT the leader's position
                                  (third person: "the president congratulated / signed ...")
      4_courtesy               -- kept but PURE courtesy/protocol (is_substantive == 'no'):
                                  greetings, congratulations, condolences, thank-yous, bare notices
    None for document_type 'other'/unknown (typically a rejected row). The keep gate is unchanged
    (still broad); this only LABELS each kept row. is_substantive == 'no' demotes ANY kept doc to
    tier 4 regardless of type; a missing/'unsure' substance flag is treated as substantive (NOT
    demoted -- we never drop on uncertainty). Thresholds: strict = tier 1; middle = tiers 1-2;
    substantive = tiers 1-3; broad = tiers 1-4 (everything the gate keeps)."""
    d = _norm(document_type)
    if d not in ("speech", "interview", "official_statement"):
        return None
    if _norm(is_substantive) == "no":
        return "4_courtesy"
    if d in ("speech", "interview"):
        return "1_speech"
    return "2_first_person_statement" if _norm(is_first_person) == "yes" else "3_third_person_statement"


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


def _stored_date_row(df, i, cols, country) -> dict:
    """Rebuild `resolve_date`'s INPUT from an already-cleaned row.

    THE TRAP: `date` in a cleaned Parquet is the RESOLVED value, not the site's field. Feeding it
    back in would re-launder a capture date as a trusted `scraped` date. The site's own value lives
    in the audit copy `date_scraped`, so that is what we read -- falling back to `date` only when
    `date_precision` says the two are the same value anyway.
    """
    def cell(col):
        v = df.at[i, col] if col in cols else None
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)

    scraped = cell("date_scraped")
    if not scraped and cell("date_precision") == "scraped":
        scraped = cell("date")
    return {
        "date": scraped,
        "text": cell("text"),
        "text_originlanguage": cell("text_originlanguage"),
        "wayback_capture": cell("wayback_capture"),
        "detected_language": cell("detected_language"),
        "source_language": cell("source_language"),
        "country": cell("country") or country,
    }


def _stored_meta(df, i, cols) -> dict | None:
    """The model's stored reply, replayed with NO API call."""
    def cell(col):
        v = df.at[i, col] if col in cols else None
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)

    model_date = cell("date_model")
    matches = cell("date_matches_metadata")
    if not model_date and not matches:
        return None
    return {"date": model_date, "date_matches_metadata": matches}


def regate_source(
    source_id: str, *, out_root: str = "data/cleaned",
    config: CleanConfig | None = None, country: str | None = None,
    redate: bool = False,
) -> dict:
    """Re-apply the gate to an already-cleaned source using the STORED extraction fields
    (document_type / speaker / speaker_type) — no API calls. Lets you change
    `keep_document_types` / `require_leader_type` and re-classify for free, without
    re-spending or losing anything. Error rows are left untouched (retry those instead).

    With `redate=True`, also re-run `resolve_date` from stored columns first, so a changed
    date_text_* setting lands on already-cleaned data for free. The corrected date is computed
    BEFORE the tenure crosscheck below, so the crosscheck is re-keyed on the right year too.
    Idempotent: nothing it reads (date_scraped / date_model / text / wayback_capture) is ever
    written, so running it twice changes nothing.

    NOTE it cannot re-run the date PRE-PASS (that needs the API). Rows whose stored `date_model`
    is merely the capture date stay on `wayback_capture` with `date_is_fallback` set — a re-clean
    with the corrected prompt is what repairs those.
    """
    config = config or CleanConfig()
    _ensure_console()
    p, country = _locate_parquet(out_root, source_id, country)
    df = store.read_source(p)
    summary = {"source_id": source_id, "country": country, "regated": 0, "changed": 0,
               "redated": 0, "output": str(p)}
    if df.empty:
        return summary

    # Re-run the tenure crosscheck too (deterministic, no API) so a tightened match_speaker
    # (issue #68 Part 4) lands on already-cleaned data during a free --regate — e.g. a spurious
    # `other_country` becomes `none`, which is what lets the review flag fire. Skipped when the
    # key file is absent, so a missing key never wipes the stored crosscheck.
    tenure_df = None
    if config.tenure_file and Path(config.tenure_file).exists():
        try:
            tenure_df = tenure.get_tenure(str(config.tenure_file))
        except Exception as e:
            log.warning("regate: could not load tenure key %s: %s", config.tenure_file, e)

    cols = set(df.columns)

    def cell(idx, col):
        return df.at[idx, col] if col in cols else None

    changed = 0
    redated = 0
    for i in df.index:
        status_now = str(df.at[i, "clean_status"]) if "clean_status" in df.columns else ""
        if status_now.startswith("error"):
            continue

        # Recompute the date FIRST, so the tenure crosscheck below is re-keyed on the corrected
        # year -- a row wrongly dated to its capture year currently matches the wrong roster.
        if redate:
            dr = resolve_date(_stored_date_row(df, i, cols, country), _stored_meta(df, i, cols),
                              flag_years=config.date_flag_years, config=config)
            before = df.at[i, "date"] if "date" in cols else None
            if dr.date != ("" if before is None or pd.isna(before) else str(before)):
                redated += 1
            df.at[i, "date"] = dr.date
            df.at[i, "date_precision"] = dr.precision
            df.at[i, "date_parsed"] = dr.parsed
            df.at[i, "date_regex_recovered"] = dr.regex
            df.at[i, "date_disagreement_flag"] = dr.disagreement
            df.at[i, "date_is_fallback"] = dr.is_fallback

        meta = {
            "document_type": cell(i, "document_type"),
            "speaker": df.at[i, "speaker"],
            "speaker_type": cell(i, "speaker_type"),
            "is_first_person": cell(i, "is_first_person"),
            "is_substantive": cell(i, "is_substantive"),
        }
        # backfill the derived inclusion tier for free (it depends only on stored fields), so an
        # old Parquet gains the column on the next --regate without any API calls.
        df.at[i, "inclusion_tier"] = _inclusion_tier(
            meta["document_type"], meta["is_first_person"], meta["is_substantive"])

        if tenure_df is not None:
            tm, ceremonial, matched = tenure.match_speaker(
                tenure_df, df.at[i, "speaker"], cell(i, "country") or country,
                _year_of(cell(i, "date")), window=config.tenure_window,
            )
            df.at[i, "tenure_match"] = tm
            df.at[i, "tenure_matched_name"] = matched or None
            df.at[i, "is_ceremonial"] = None if pd.isna(ceremonial) else bool(ceremonial)
            tmatch = tm
        else:
            tmatch = df.at[i, "tenure_match"] if "tenure_match" in df.columns else ""

        new_status, new_reason = gate.decide(meta, config, tmatch)
        if new_status != status_now:
            df.at[i, "clean_status"] = new_status
            df.at[i, "gate_reason"] = new_reason
            changed += 1
        # backfill the review flag unconditionally (like inclusion_tier) so an old Parquet gains
        # the column on the first --regate even when the status itself doesn't change.
        df.at[i, "speaker_review"] = gate.needs_review(meta, new_status, tmatch)
    store.write_source_atomic(df, p, config.compression)
    try:
        from .merge import build_clean_index
        build_clean_index(out_root)
    except Exception:
        pass
    summary.update(regated=len(df), changed=changed, redated=redated)
    log.info("REGATE %s | rows=%d changed=%d%s -> %s", source_id, len(df), changed,
             f" redated={redated}" if redate else "", p)
    return summary


def _base_row(row: dict) -> dict:
    """Carry ALL input columns through (so a combined corpus keeps ISI_id / custom fields),
    guarantee the 15 scraped columns exist, record audit copies, and None-init the cleaner's
    columns. For a standard scraper CSV (exactly the 15 columns) this is unchanged behavior."""
    out = dict(row)
    for c in store.SCRAPED_COLUMNS:
        out.setdefault(c, "")
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

    # date: adjudicated by resolve_date (see its docstring for the two tiers of trust). Every
    # candidate is stored side by side, win or lose -- date_scraped (the site's own field),
    # date_regex_recovered (the head-line pattern match), date_model (the model's answer),
    # wayback_capture (the crawl bound) -- so a consumer can re-adjudicate without re-running
    # anything. date_precision says which won; date_is_fallback marks a date that is ONLY the crawl
    # bound; date_disagreement_flag marks a row where the candidates conflicted and a human should
    # look (above all: the recipe's own date selector contradicted by the model).
    _dr = resolve_date(row, meta, flag_years=config.date_flag_years, config=config)
    out["date"] = _dr.date
    out["date_precision"] = _dr.precision
    out["date_model"] = _dr.model_date
    out["date_parsed"] = _dr.parsed
    out["date_regex_recovered"] = _dr.regex
    out["date_disagreement_flag"] = _dr.disagreement
    out["date_is_fallback"] = _dr.is_fallback
    if meta.get("date_confidence") is not None:
        out["date_confidence"] = meta.get("date_confidence")

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
    out["is_substantive"] = meta.get("is_substantive")
    out["inclusion_tier"] = _inclusion_tier(
        meta.get("document_type"), meta.get("is_first_person"), meta.get("is_substantive"))
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

    status, reason = gate.decide(meta, config, out.get("tenure_match", ""))
    out["clean_status"] = status
    out["gate_reason"] = reason
    # Orthogonal review flag: a plausible national leader the tenure key doesn't yet know
    # about (issue #68). Never changes accept/reject — just surfaces a key gap for curation.
    out["speaker_review"] = gate.needs_review(meta, status, out.get("tenure_match", ""))
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
    reclean: bool = False,
    dry_run: bool = False,
    save_every_chunks: int = 1,
) -> dict:
    """Clean ONE scraped source: resolve its country folder + per-source output/state paths from
    the scraper's `data/scraped/<Country>/<id>.csv` convention, then delegate to `clean_file`.
    run.py loops this over a country / all sources."""
    csv_path, country = _locate_csv(in_root, source_id, country)
    out_path = Path(out_root) / country / f"{source_id}.parquet"
    state_path = Path(state_root) / country / f"{source_id}.json"
    return clean_file(
        csv_path, out_path, state_path=state_path,
        config=config, model=model, label=source_id, country_label=country,
        limit=limit, retry_failed=retry_failed, reclean=reclean, dry_run=dry_run,
        refresh_index=True, index_root=out_root, save_every_chunks=save_every_chunks,
    )


def clean_file(
    in_path: str | Path,
    out_path: str | Path,
    *,
    state_path: str | Path | None = None,
    config: CleanConfig | None = None,
    model: str | None = None,
    label: str | None = None,
    country_label: str | None = None,
    limit: int | None = None,
    retry_failed: bool = False,
    reclean: bool = False,
    dry_run: bool = False,
    refresh_index: bool = False,
    index_root: str | Path | None = None,
    save_every_chunks: int = 1,
) -> dict:
    """Clean ONE input table into ONE output Parquet (which doubles as the resume ledger), with
    EXPLICIT paths. Country-agnostic: every row's country/tenure/prompt is read from its own
    `country` column, so the input may mix countries, datasets, and speakers (a combined corpus).
    `clean_source` wraps this with the per-source folder convention; the CLI's `--input` mode calls
    it directly. `label` names the source in logs/summary/state; `refresh_index` rebuilds the
    cleaned-store index rooted at `index_root` (only meaningful when writing into the
    `data/cleaned/<Country>/` tree)."""
    config = config or CleanConfig()
    if model:
        config = config.model_copy(update={"model": model})

    in_path = Path(in_path)
    out_path = Path(out_path)
    label = label or in_path.stem
    state_path = Path(state_path) if state_path else out_path.parent / f"{out_path.stem}.state.json"

    scraped = store.read_input(in_path)
    scraped["doc_id"] = scraped["doc_id"].astype(str)

    # tenure key (optional but expected)
    tenure_missing = not Path(config.tenure_file).exists()
    tenure_df = None if tenure_missing else tenure.get_tenure(str(config.tenure_file))

    existing = store.read_source(out_path)
    if not existing.empty:
        existing["doc_id"] = existing["doc_id"].astype(str)
    done, failed = store.done_and_failed(existing)
    # reclean re-sends EVERY row to the model (to populate a newly-added field like is_substantive);
    # otherwise skip already-done rows (and, unless retry_failed, previously-failed ones too).
    skip = set() if reclean else (done if retry_failed else (done | failed))

    todo = scraped[~scraped["doc_id"].isin(skip)].copy()
    if limit:
        todo = todo.head(limit)
    todo_ids = set(todo["doc_id"])
    keep = existing[~existing["doc_id"].isin(todo_ids)] if not existing.empty else store.empty_frame()

    summary = {
        "source_id": label, "country": country_label, "model": config.model,
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
    log_path, log_handler = _add_log_file(out_path.parent, label)
    summary["log"] = str(log_path)
    log.info("START %s (%s) | model=%s limit=%s retry_failed=%s",
             label, country_label, config.model, limit, retry_failed)
    if tenure_missing:
        log.warning("tenure file not found at %s -- tenure crosscheck disabled", config.tenure_file)
    log.info("scraped=%d | already_done=%d known_failed=%d | to_clean=%d",
             len(scraped), len(done), len(failed), len(todo))

    api_key = llm.load_api_key(config)
    client = llm.create_async_client(api_key)

    rows = [r.to_dict() for _, r in todo.iterrows()]
    for row in rows:
        # record the head-line candidate on the row so BOTH prompts can show it (labelled
        # UNVERIFIED) and so it is stored win or lose.
        row["date_regex_recovered"] = resolve_date(
            row, flag_years=config.date_flag_years, config=config).regex

    # ---------------------------------------------------------------- PASS 1: settle the date
    # The date must be established BEFORE the tenure key names candidate leaders. Otherwise the key
    # is applied to a bad year and PROPAGATES error into speaker attribution instead of correcting
    # it: a 2016 Uzbek speech captured in 2024 would be matched against the 2024 roster. Only rows
    # WITHOUT a trusted date selector need this -- the rest keep the single call they always had.
    date_meta: dict[int, dict] = {}
    need_date = [
        i for i, row in enumerate(rows)
        if getattr(config, "date_pass_enabled", True) and not (row.get("date") or "").strip()
    ]
    if need_date:
        log.info("date pre-pass: %d of %d rows have no site date -- resolving the date first "
                 "so the tenure key is keyed on the right year", len(need_date), len(rows))
        date_items = [
            {"idx": i,
             "message": extract.build_date_message(
                 rows[i], max_words=getattr(config, "date_pass_max_words", 200))}
            for i in need_date
        ]

        async def date_worker(item, sem):
            return await extract.extract_date_one(client, config, item["message"], sem)

        def on_date_chunk(chunk, results):
            for item, res in zip(chunk, results):
                if not isinstance(res, Exception) and isinstance(res, dict):
                    date_meta[item["idx"]] = res

        try:
            asyncio.run(llm.run_async_batches(
                date_items, date_worker, batch_size=config.batch_size,
                chunk_size=config.chunk_size, on_chunk=on_date_chunk,
            ))
        except Exception:
            # A failed pre-pass must never sink the run: those rows simply fall back to the
            # deterministic candidates, exactly as before this stage existed.
            log.exception("date pre-pass failed -- continuing without it")
        resolved = sum(1 for m in date_meta.values() if (m or {}).get("date"))
        log.info("date pre-pass: %d/%d dates resolved from the text", resolved, len(need_date))

    # ---------------------------------------------------------------- PASS 2: full extraction
    items = []
    for i, row in enumerate(rows):
        dmeta = date_meta.get(i) or {}
        # feed PASS 1's answer into resolve_date as the model's date, so the confirmed date -- not
        # the crawl timestamp -- picks the leader roster and is what the model sees as DATE.
        res_pre = resolve_date(row, {"date": dmeta.get("date")} if dmeta.get("date") else None,
                               flag_years=config.date_flag_years, config=config)
        leaders_info = ""
        if tenure_df is not None:
            leaders = tenure.leaders_for(tenure_df, row.get("country", ""),
                                         _year_of(res_pre.date), config.tenure_window)
            leaders_info = ", ".join(leaders)
        # message-only copy: the stored row is untouched, so date_scraped keeps the original
        msg_row = dict(row)
        if res_pre.date:
            msg_row["date"] = res_pre.date
        msg = extract.build_user_message(msg_row, leaders_info, max_words=config.max_words)
        items.append({"row": row, "message": msg, "date_meta": dmeta})

    new_rows: list[dict] = []
    counters = {"accepted": 0, "rejected": 0, "errors": 0, "chunks": 0, "consecutive_fail": 0}
    aborted = {"flag": False}

    async def worker(item, sem):
        return await extract.extract_one(client, config, item["message"], sem)

    def _save_state():
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "source_id": label, "country": country_label, "model": config.model,
            "scraped_total": len(scraped),
            "cleaned_total": len(keep) + len(new_rows),
            "this_run": dict(counters), "last_run": datetime.now().isoformat(timespec="seconds"),
        }
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _flush():
        # no columns= restriction: keep any extra input columns (e.g. ISI_id) on new rows;
        # write_source_atomic orders CLEANED_COLUMNS first and appends the extras.
        df_out = pd.concat(
            [keep, pd.DataFrame(new_rows)], ignore_index=True
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
                # PASS 1 is the dedicated date call, with the prompt that explains what an archive
                # capture is; its answer outranks the date PASS 2 mentions in passing.
                dmeta = item.get("date_meta") or {}
                if dmeta.get("date"):
                    res = dict(res)
                    res["date"] = dmeta["date"]
                    res["date_confidence"] = dmeta.get("date_confidence")
                    if dmeta.get("date_basis"):
                        log.debug("date basis %s: %s", item["row"].get("doc_id"), dmeta["date_basis"])
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
                 label, len(new_rows), counters["accepted"], counters["rejected"],
                 counters["errors"], " | ABORTED" if aborted["flag"] else "", out_path)
        if refresh_index and index_root is not None:
            try:
                from .merge import build_clean_index
                build_clean_index(str(index_root))
            except Exception as e:
                log.warning("could not refresh clean index: %s", e)
        logging.getLogger("leaderspeech.clean_structure_metadata").removeHandler(log_handler)
        log_handler.close()

    return summary
