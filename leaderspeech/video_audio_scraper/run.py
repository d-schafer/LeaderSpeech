"""Orchestrator + CLI for audio transcription.

Harvest the video URLs behind a playlist/channel (or read a saved list), download the
audio for each, transcribe it with Whisper, map the result into the SAME standardized
LeaderSpeech schema as the text scraper, and append to the per-country CSV. A media
sidecar (`<id>_media.csv`) carries the rich yt-dlp provenance. The run is resumable via
the SHARED per-country state file, so `doc_id` stays unique and contiguous across text
*and* audio sources in a country.

Primary (no-recipe) usage:
    python -m leaderspeech.video_audio_scraper.run --url "<playlist>" --country Italy \
        --speaker "Giuseppe Conte" --language Italian --limit 2 --delete-audio --save-recipe

Reproducible re-run / update:
    python -m leaderspeech.video_audio_scraper.run --recipe recipes_audio/<id>.yml --update
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..text_scraper import index
from ..text_scraper.extract import parse_date
from ..text_scraper.run import (
    ERROR_COLUMNS, SCHEMA_COLUMNS, _add_log_file, _append, alpha3_for,
    load_state, map_to_schema, save_state,
)
from . import harvest as harvest_mod
from ._cli import add_source_args, recipe_from_args
from .config import AudioConfig, load_config
from .recipe import AudioRecipe, save_recipe
from .transcribe import get_transcriber

log = logging.getLogger("leaderspeech.video_audio_scraper.run")

# Rich provenance the standardized schema has no home for; keyed by doc_id.
# `kind` + `backend` are constant per source and are what index.py reads to set the
# audio marker (pagination_type=<kind>, renderer=audio:<backend>).
MEDIA_COLUMNS = [
    "doc_id", "media_url", "video_id", "upload_date", "duration",
    "channel", "uploader", "uploader_id", "view_count", "like_count", "tags",
    "language", "detected_language", "audio_path", "audio_status",
    "kind", "backend", "model", "transcribed_at",
]


def _iso_date(upload_date: str) -> str:
    """yt-dlp gives upload_date as YYYYMMDD; convert to ISO, falling back to dateparser."""
    if upload_date and len(upload_date) == 8 and upload_date.isdigit():
        try:
            return datetime.strptime(upload_date, "%Y%m%d").date().isoformat()
        except Exception:
            pass
    return parse_date(upload_date) or ""


def transcribe_source(
    recipe: AudioRecipe,
    config: AudioConfig,
    *,
    out_root: str = "data/scraped",
    state_root: str = "data/state",
    audio_root: str = "data/audio_video",
    limit: Optional[int] = None,
    retry_failed: bool = False,
    delete_audio: Optional[bool] = None,
    update: bool = False,
    assume_yes: bool = False,
    prompt_before_run: bool = False,
    dry_run: bool = False,
) -> dict:
    alpha3 = alpha3_for(recipe.country)
    out_dir = Path(out_root) / recipe.country
    out_path = out_dir / f"{recipe.source_id}.csv"
    media_path = out_dir / f"{recipe.source_id}_media.csv"
    err_path = out_dir / f"{recipe.source_id}_errors.csv"
    state_path = Path(state_root) / f"{recipe.country}.json"
    audio_dir = Path(audio_root) / recipe.country / recipe.source_id

    if delete_audio is None:
        delete_audio = config.delete_audio_after_transcribe

    log_path, log_handler = _add_log_file(out_dir, recipe.source_id)
    log.info("START %s (%s) | backend=%s model=%s | limit=%s retry_failed=%s delete_audio=%s update=%s",
             recipe.source_id, recipe.country,
             recipe.whisper.backend or config.backend, recipe.whisper.model or config.model,
             limit, retry_failed, delete_audio, update)

    state = load_state(state_path)
    seen = set(state["seen_urls"])
    failed = set(state["failed_urls"])

    def stamp() -> str:
        return datetime.now().isoformat(timespec="seconds")

    summary = {
        "source_id": recipe.source_id, "country": recipe.country,
        "links_found": 0, "transcribed_this_run": 0, "skipped_filtered": 0,
        "failed_this_run": 0, "failed_pending_retry": 0, "aborted_early": False,
        "last_doc_num": state["last_doc_num"], "output": str(out_path),
        "media": str(media_path), "log": str(log_path), "errors_file": str(err_path),
        "proceeded": False,
    }

    transcriber = None
    rows: list[dict] = []
    media_rows: list[dict] = []
    errors: list[dict] = []
    n_ok = n_failed = n_skipped = 0
    consecutive_fail = 0
    try:
        # 1) harvest the URL list (yt-dlp flat extraction or a saved list)
        entries = harvest_mod.harvest_entries(recipe)
        urls = [e["url"] for e in entries]
        summary["links_found"] = len(urls)
        harvest_mod.write_links(entries, out_dir, recipe.source_id)
        msg = harvest_mod.summarize(entries)
        log.info(msg)

        skip = seen if retry_failed else (seen | failed)
        todo = [u for u in urls if u not in skip]
        if limit:
            todo = todo[:limit]
        log.info("%d to process (%d already done, %d known-failed%s)",
                 len(todo), len(seen), len(failed),
                 "; retrying failures" if retry_failed else "")

        # 2) confirm before spending compute/disk (only on the interactive --url path)
        print(msg)
        if dry_run:
            print(f"[dry-run] would download + transcribe {len(todo)} video(s); no changes made.")
            return summary
        if not todo:
            print("nothing new to process.")
            return summary
        if prompt_before_run and not assume_yes:
            if not sys.stdin.isatty():
                print("non-interactive shell: re-run with --yes to proceed.")
                return summary
            ans = input(f"download + transcribe {len(todo)} video(s)? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                print("aborted.")
                return summary
        summary["proceeded"] = True

        # 3) load the transcriber ONCE (after the prompt, so a 'no' never loads a model)
        transcriber = get_transcriber(
            recipe.whisper.backend or config.backend, config,
            model=recipe.whisper.model or config.model,
            language=recipe.whisper.language or config.language,
        )
        backend_name = transcriber.name
        model_name = transcriber.model or (recipe.whisper.model or config.model)
        source_kind = harvest_mod.detect_kind(recipe)

        from .download import download_audio  # lazy: keep yt-dlp out of import time

        for i, url in enumerate(todo, 1):
            try:
                meta = download_audio(url, audio_dir, recipe,
                                      audio_format=recipe.audio_format,
                                      audio_quality=recipe.audio_quality)
                if meta is None:                      # filtered out (date/duration) before download
                    n_skipped += 1
                    seen.add(url)                     # decided; don't reprocess
                    consecutive_fail = 0
                    log.info("skipped (filtered): %s", url)
                    continue

                result = transcriber.transcribe(meta["audio_path"], language=recipe.whisper.language)
                text = (result.get("text") or "").strip()
                if not text:
                    errors.append({"timestamp": stamp(), "url": url, "error": "empty_transcript"})
                    failed.add(url)
                    n_failed += 1
                    consecutive_fail += 1
                    log.warning("empty transcript: %s", url)
                    continue

                state["last_doc_num"] += 1
                doc_id = f"{alpha3}{state['last_doc_num']:04d}"
                rec = {
                    "title": meta.get("title", ""),
                    "text": text,
                    "date": _iso_date(meta.get("upload_date", "")),
                    "context": meta.get("description", ""),
                    "speaker": recipe.speaker_default or "",
                    "source": meta.get("webpage_url") or url,
                }
                rows.append(map_to_schema(rec, recipe, doc_id))

                audio_path = meta.get("audio_path", "")
                audio_status = "kept"
                if delete_audio and audio_path:
                    try:
                        Path(audio_path).unlink(missing_ok=True)
                        audio_status = "deleted"
                        audio_path = ""
                    except Exception as e:
                        log.warning("could not delete %s :: %s", audio_path, e)
                media_rows.append({
                    "doc_id": doc_id, "media_url": meta.get("webpage_url") or url,
                    "video_id": meta.get("id", ""), "upload_date": meta.get("upload_date", ""),
                    "duration": meta.get("duration", ""), "channel": meta.get("channel", ""),
                    "uploader": meta.get("uploader", ""), "uploader_id": meta.get("uploader_id", ""),
                    "view_count": meta.get("view_count", ""), "like_count": meta.get("like_count", ""),
                    "tags": meta.get("tags", ""), "language": meta.get("language", ""),
                    "detected_language": result.get("language", ""),
                    "audio_path": audio_path, "audio_status": audio_status,
                    "kind": source_kind, "backend": backend_name, "model": model_name,
                    "transcribed_at": stamp(),
                })
                seen.add(url)
                failed.discard(url)
                n_ok += 1
                consecutive_fail = 0
                log.info("transcribed %s -> %s (%d chars)", url, doc_id, len(text))
            except Exception as e:
                detail = f"{type(e).__name__}: {e}"
                errors.append({"timestamp": stamp(), "url": url, "error": detail[:300]})
                failed.add(url)
                n_failed += 1
                consecutive_fail += 1
                log.warning("error: %s :: %s", url, detail[:160])

            if consecutive_fail >= config.max_consecutive_failures:
                summary["aborted_early"] = True
                log.error("ABORTING after %d consecutive failures — likely blocked or a broken "
                          "yt-dlp/ffmpeg/model setup. See the errors file, fix, then --retry-failed.",
                          consecutive_fail)
                break

            if i % config.save_every == 0:
                _append(out_path, rows, SCHEMA_COLUMNS)
                _append(media_path, media_rows, MEDIA_COLUMNS)
                _append(err_path, errors, ERROR_COLUMNS)
                rows, media_rows, errors = [], [], []
                state["seen_urls"], state["failed_urls"] = sorted(seen), sorted(failed)
                save_state(state_path, state)
                log.info("progress %d/%d | ok=%d skipped=%d failed=%d", i, len(todo), n_ok, n_skipped, n_failed)

            if config.rate_limit_delay:
                time.sleep(config.rate_limit_delay)
            if config.pause_every and i % config.pause_every == 0 and config.pause_seconds:
                time.sleep(config.pause_seconds)
    except Exception:
        log.exception("FATAL during harvest/transcribe — partial results flushed below")
        raise
    finally:
        if transcriber is not None:
            try:
                transcriber.close()
            except Exception:
                pass
        _append(out_path, rows, SCHEMA_COLUMNS)
        _append(media_path, media_rows, MEDIA_COLUMNS)
        _append(err_path, errors, ERROR_COLUMNS)
        state["seen_urls"], state["failed_urls"] = sorted(seen), sorted(failed)
        save_state(state_path, state)
        summary.update(transcribed_this_run=n_ok, skipped_filtered=n_skipped,
                       failed_this_run=n_failed, failed_pending_retry=len(failed),
                       last_doc_num=state["last_doc_num"])
        log.info("DONE %s | transcribed=%d skipped=%d failed=%d%s | last_doc_num=%d | out=%s",
                 recipe.source_id, n_ok, n_skipped, n_failed,
                 " | ABORTED EARLY" if summary["aborted_early"] else "",
                 state["last_doc_num"], out_path)
        try:
            index.build_index(out_root)
        except Exception as e:
            log.warning("could not update scrape index: %s", e)
        logging.getLogger("leaderspeech").removeHandler(log_handler)
        log_handler.close()

    return summary


def main():
    ap = argparse.ArgumentParser(description="LeaderSpeech audio scraper + transcriber (whisperscribe)")
    add_source_args(ap)
    ap.add_argument("--out-root", default="data/scraped")
    ap.add_argument("--state-root", default="data/state")
    ap.add_argument("--audio-root", default="data/audio_video")
    ap.add_argument("--config", default=None, help="path to an audio_config.yml (else defaults)")
    ap.add_argument("--recipes-dir", default="recipes_audio", help="where --save-recipe writes")
    ap.add_argument("--limit", type=int, default=None, help="cap videos processed this run")
    ap.add_argument("--retry-failed", action="store_true", help="re-attempt previously failed URLs")
    ap.add_argument("--update", action="store_true", help="re-harvest the playlist; process only new URLs")
    ap.add_argument("--yes", "-y", action="store_true", help="skip the confirm prompt on the --url path")
    ap.add_argument("--dry-run", action="store_true", help="harvest + summarize only; no download/transcribe")
    ap.add_argument("--save-recipe", action="store_true",
                    help="write recipes_audio/<id>.yml for reproducible re-runs/updates")
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--delete-audio", dest="delete_audio", action="store_true", default=None,
                     help="delete each mp3 after a successful transcription")
    grp.add_argument("--keep-audio", dest="delete_audio", action="store_false",
                     help="force-keep audio (override a config that deletes)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    recipe, from_url = recipe_from_args(args)
    config = load_config(args.config)

    if args.save_recipe and not args.recipe:
        path = save_recipe(recipe, Path(args.recipes_dir) / f"{recipe.source_id}.yml")
        log.info("saved recipe -> %s", path)

    result = transcribe_source(
        recipe, config,
        out_root=args.out_root, state_root=args.state_root, audio_root=args.audio_root,
        limit=args.limit, retry_failed=args.retry_failed, delete_audio=args.delete_audio,
        update=args.update, assume_yes=args.yes, prompt_before_run=from_url, dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
