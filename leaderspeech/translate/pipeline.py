"""Core translation logic: fill the English columns of a table in place.

`translate_table` is the unit of work — it walks the rows that still need translation
(origin-language text present, English target empty) and fills `text`/`title`/`context`
from `text_originlanguage`/etc. `translate_file` wraps it with atomic, checkpointed I/O
for one file. Resumability needs no separate ledger: a row is "done" once its English
target is filled, so a re-run simply skips it.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import store
from .config import TranslateConfig

log = logging.getLogger("leaderspeech.translate")

# Provenance columns this tool adds.
PROVENANCE_COLUMNS = ["text_translator", "translated_at"]

# source_language is stored as a NAME ("Spanish"); detected_language as an ISO code ("es").
LANG_NAME_TO_ISO = {
    "english": "en", "spanish": "es", "french": "fr", "portuguese": "pt",
    "german": "de", "italian": "it", "dutch": "nl", "russian": "ru",
    "ukrainian": "uk", "polish": "pl", "czech": "cs", "slovak": "sk",
    "romanian": "ro", "hungarian": "hu", "bulgarian": "bg", "croatian": "hr",
    "serbian": "sr", "slovenian": "sl", "greek": "el", "turkish": "tr",
    "arabic": "ar", "persian": "fa", "farsi": "fa", "hebrew": "he",
    "chinese": "zh", "japanese": "ja", "korean": "ko", "hindi": "hi",
    "urdu": "ur", "indonesian": "id", "malay": "ms", "vietnamese": "vi",
    "thai": "th", "swahili": "sw", "afrikaans": "af", "amharic": "am",
    "albanian": "sq", "armenian": "hy", "azerbaijani": "az", "belarusian": "be",
    "bosnian": "bs", "catalan": "ca", "danish": "da", "estonian": "et",
    "finnish": "fi", "georgian": "ka", "icelandic": "is", "irish": "ga",
    "kazakh": "kk", "latvian": "lv", "lithuanian": "lt", "macedonian": "mk",
    "norwegian": "no", "swedish": "sv",
}


def resolve_src_lang(row) -> str | None:
    """Best source-language ISO code for a row: `detected_language` (cleaner) wins, else
    `source_language` (a name like 'Spanish'). None if unknown — backends decide what to do."""
    dl = str(row.get("detected_language") or "").strip().lower()
    if dl and dl not in ("nan", "none") and dl.isalpha():
        return dl[:2]
    sl = str(row.get("source_language") or "").strip().lower()
    if sl in LANG_NAME_TO_ISO:
        return LANG_NAME_TO_ISO[sl]
    if len(sl) == 2 and sl.isalpha():  # already an ISO code
        return sl
    return None


def _needs(row, field: str, force: bool) -> bool:
    origin = str(row.get(f"{field}_originlanguage") or "").strip()
    target = str(row.get(field) or "").strip()
    return bool(origin) and (force or not target)


def translate_table(
    df: pd.DataFrame,
    translator,
    config: TranslateConfig,
    *,
    limit: int | None = None,
    force: bool = False,
    on_checkpoint=None,
) -> tuple[pd.DataFrame, int]:
    """Fill `config.fields` English columns in `df` using `translator`. Returns
    (df, n_rows_translated). Only rows whose English target is empty (unless `force`) and
    whose `*_originlanguage` is present are touched; `only_accepted` skips rejected rows
    when a `clean_status` column is present. `on_checkpoint(df)` is called periodically."""
    fields = list(config.fields)
    for c in PROVENANCE_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA

    needs_mask = df.apply(lambda r: any(_needs(r, f, force) for f in fields), axis=1)
    if config.only_accepted and "clean_status" in df.columns:
        needs_mask &= df["clean_status"].astype(str) == "accepted"
    idxs = list(df.index[needs_mask])
    if limit is not None:
        idxs = idxs[:limit]

    n_done = 0
    n_failed = 0
    total = len(idxs)
    for count, i in enumerate(idxs, 1):
        row = df.loc[i]
        src = resolve_src_lang(row)
        log.info("translating %d/%d (doc_id=%s)", count, total, row.get("doc_id"))
        changed = False
        for f in fields:
            if not _needs(row, f, force):
                continue
            origin = str(df.at[i, f"{f}_originlanguage"])
            try:
                out = translator.translate(origin, src)
            except Exception as e:
                # The backend's own message ("...api connection error...") hides the real cause.
                # Report the text length + chunk count and flag the common failure mode: a very long
                # text is split into many chunks, and the burst of requests trips the free Google
                # endpoint's rate limit. (Short texts = one request = fine.)
                n_chunks = len(origin) // max(1, config.max_chunk_chars) + 1
                etype = type(e).__name__
                looks_rate = "requesterror" in etype.lower() or any(
                    s in str(e).lower() for s in ("rate", "too many", "connection"))
                hint = (f"  [len={len(origin)} chars -> ~{n_chunks} chunk(s); long texts make many "
                        "requests and can trip the free endpoint's rate limit]") if (looks_rate and n_chunks > 1) else ""
                log.warning("translate failed after retries (doc_id=%s field=%s src=%s len=%d chunks~%d): %s: %s%s",
                            row.get("doc_id"), f, src, len(origin), n_chunks, etype, e, hint)
                out = ""
                n_failed += 1
            if out:
                df.at[i, f] = out
                changed = True
        if changed:
            df.at[i, "text_translator"] = translator.name
            df.at[i, "translated_at"] = datetime.now().isoformat(timespec="seconds")
            n_done += 1

        if config.pause_every and count % config.pause_every == 0:
            time.sleep(config.pause_seconds)
        if on_checkpoint and config.checkpoint_every and count % config.checkpoint_every == 0:
            on_checkpoint(df)
            log.info("checkpoint: %d/%d rows processed (%d translated)", count, len(idxs), n_done)

    if n_failed:
        log.warning("%d field(s) failed to translate (likely rate-limit) — they were left empty; "
                    "re-run to retry just those (already-filled rows are skipped).", n_failed)
    return df, n_done


def translate_file(
    path: str | Path,
    translator,
    config: TranslateConfig,
    *,
    output: str | Path | None = None,
    limit: int | None = None,
    force: bool = False,
) -> dict:
    """Translate one table file in place (or to `output`), with atomic checkpoint writes."""
    in_path = Path(path)
    out_path = Path(output) if output else in_path
    df = store.read_table(in_path)

    def checkpoint(d):
        store.write_table_atomic(d, out_path, config.compression)

    df, n = translate_table(df, translator, config, limit=limit, force=force, on_checkpoint=checkpoint)
    store.write_table_atomic(df, out_path, config.compression)
    log.info("DONE %s | translated=%d -> %s", in_path.name, n, out_path)
    return {"input": str(in_path), "output": str(out_path),
            "rows_translated": n, "translator": translator.name}
