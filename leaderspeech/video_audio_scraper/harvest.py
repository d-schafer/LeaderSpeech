"""Enumerate the video URLs behind a playlist/channel link (or read a saved list).

This is the cheap first step: `yt-dlp` flat-extracts the list (no media), we apply the
title / max-videos filters, print a summary, and save `<id>_links.txt`. It's also a
standalone CLI (`leaderspeech-transcribe-harvest`) so a user can eyeball what a source
yields before committing to download + transcription.

(Date / duration filters need per-video metadata that flat extraction doesn't carry, so
they're enforced later, at download time, via yt-dlp's daterange/match_filter — see
download.py. The flat count here is therefore an upper bound.)
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Optional

from ._cli import add_source_args, recipe_from_args
from .recipe import AudioRecipe

log = logging.getLogger("leaderspeech.video_audio_scraper.harvest")


def detect_kind(recipe) -> str:
    """Classify a source as playlist | channel | url_list (for the index's pagination_type).
    Uses the recipe's explicit `harvest.kind` if set, else infers from the first URL."""
    h = getattr(recipe, "harvest", None)
    if h is not None and getattr(h, "kind", None):
        return h.kind
    urls = getattr(recipe, "start_urls", None) or []
    if not urls:
        return "url_list"     # a links_file / explicit list
    u = urls[0].lower()
    if "list=" in u or "/playlist" in u:
        return "playlist"
    if "/channel/" in u or "/@" in u or "/c/" in u or "/user/" in u or u.rstrip("/").endswith("/videos"):
        return "channel"
    return "url_list"


def _entry_url(e: dict) -> Optional[str]:
    """Best-effort full watch URL from a flat-playlist entry."""
    if not e:
        return None
    url = e.get("webpage_url") or e.get("url")
    if url and "://" in url:
        return url
    vid = e.get("id")
    if vid:
        return f"https://www.youtube.com/watch?v={vid}"
    return url


def _flatten(entries) -> list[dict]:
    out: list[dict] = []
    for e in entries or []:
        if e is None:
            continue
        if e.get("entries"):            # a channel's tabs / nested playlists
            out.extend(_flatten(e["entries"]))
        else:
            out.append(e)
    return out


def harvest_entries(recipe: AudioRecipe) -> list[dict]:
    """Return [{url, title, id, duration, upload_date}] for the source. Prefers
    `start_urls` (flat yt-dlp extraction); falls back to `links_file`."""
    if recipe.start_urls:
        from yt_dlp import YoutubeDL

        opts: dict = {"quiet": True, "no_warnings": True,
                      "extract_flat": "in_playlist", "skip_download": True}
        if recipe.user_agent:
            opts["http_headers"] = {"User-Agent": recipe.user_agent}
        if recipe.cookies_from_browser:
            opts["cookiesfrombrowser"] = (recipe.cookies_from_browser,)

        raw: list[dict] = []
        with YoutubeDL(opts) as ydl:
            for url in recipe.start_urls:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    continue
                raw.extend(_flatten(info.get("entries")) if info.get("entries") else [info])
        entries = []
        for e in raw:
            u = _entry_url(e)
            if not u:
                continue
            entries.append({
                "url": u, "title": e.get("title") or "", "id": e.get("id") or "",
                "duration": e.get("duration"), "upload_date": e.get("upload_date") or "",
            })
    elif recipe.links_file:
        lines = Path(recipe.links_file).read_text(encoding="utf-8").splitlines()
        entries = [{"url": ln.strip(), "title": "", "id": "", "duration": None, "upload_date": ""}
                   for ln in lines if ln.strip() and not ln.startswith("#")]
    else:
        entries = []

    # filters available at flat stage: title regex, then cap
    h = recipe.harvest
    if h.match_title:
        pat = re.compile(h.match_title, re.IGNORECASE)
        entries = [e for e in entries if not e["title"] or pat.search(e["title"])]
    # de-dupe while preserving order
    seen, deduped = set(), []
    for e in entries:
        if e["url"] not in seen:
            seen.add(e["url"])
            deduped.append(e)
    entries = deduped
    if h.max_videos:
        entries = entries[: h.max_videos]
    return entries


def summarize(entries: list[dict]) -> str:
    n = len(entries)
    dates = sorted(e["upload_date"] for e in entries if e.get("upload_date"))
    span = ""
    if dates:
        def fmt(d):
            return f"{d[:4]}-{d[4:6]}" if len(d) >= 6 else d
        span = f" | dates {fmt(dates[0])} .. {fmt(dates[-1])}"
    samples = [e["title"] for e in entries if e.get("title")][:3]
    sample = (" | e.g. " + "; ".join(f"'{t[:60]}'" for t in samples)) if samples else ""
    return f"Found {n} video(s){span}{sample}"


def write_links(entries: list[dict], out_dir: Path, source_id: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{source_id}_links.txt"
    path.write_text("\n".join(e["url"] for e in entries) + ("\n" if entries else ""), encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(
        description="Harvest video URLs from a playlist/channel (no download/transcription)")
    add_source_args(ap)
    ap.add_argument("--out-root", default="data/scraped")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    recipe, _ = recipe_from_args(args)
    entries = harvest_entries(recipe)
    out_dir = Path(args.out_root) / recipe.country
    path = write_links(entries, out_dir, recipe.source_id)
    print(summarize(entries))
    print(f"saved {len(entries)} link(s) -> {path}")


if __name__ == "__main__":
    main()
