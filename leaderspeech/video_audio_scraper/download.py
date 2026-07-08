"""Audio download + metadata via yt-dlp (audio only — the video is never kept).

Consolidates the prototype `pulltube*.py`: `bestaudio/best` + an `FFmpegExtractAudio`
postprocessor to mp3, pulling the same rich metadata the old scripts collected. Date /
duration filters are pushed *into* yt-dlp (daterange / match_filter) so a filtered video
is skipped BEFORE its media is downloaded — no wasted bandwidth or disk.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("leaderspeech.video_audio_scraper.download")

# Metadata keys carried from yt-dlp into the media sidecar / schema mapping.
META_KEYS = (
    "id", "title", "upload_date", "description", "language", "duration",
    "view_count", "like_count", "channel", "uploader", "uploader_id", "webpage_url",
)


def _normalize_meta(info: dict) -> dict:
    tags = info.get("tags") or []
    return {
        "id": info.get("id") or "",
        "title": info.get("title") or "",
        "upload_date": info.get("upload_date") or "",   # YYYYMMDD
        "description": info.get("description") or "",
        "language": info.get("language") or "",
        "tags": ", ".join(t for t in tags if t) if isinstance(tags, list) else str(tags),
        "duration": info.get("duration") or "",
        "view_count": info.get("view_count") or "",
        "like_count": info.get("like_count") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "uploader": info.get("uploader") or "",
        "uploader_id": info.get("uploader_id") or "",
        "webpage_url": info.get("webpage_url") or "",
    }


def _base_opts(recipe=None, quiet: bool = True) -> dict:
    opts: dict = {"quiet": quiet, "no_warnings": quiet, "noplaylist": True}
    ua = getattr(recipe, "user_agent", None)
    if ua:
        opts["http_headers"] = {"User-Agent": ua}
    cfb = getattr(recipe, "cookies_from_browser", None)
    if cfb:
        opts["cookiesfrombrowser"] = (cfb,)
    return opts


def _filter_opts(recipe) -> dict:
    """daterange + duration match_filter so yt-dlp skips rejects before downloading media."""
    from yt_dlp.utils import DateRange, match_filter_func

    opts: dict = {}
    h = getattr(recipe, "harvest", None)
    if h is None:
        return opts
    if h.date_min or h.date_max:
        opts["daterange"] = DateRange(h.date_min or None, h.date_max or None)
    conds = []
    if h.min_duration:
        conds.append(f"duration >= {int(h.min_duration)}")
    if h.max_duration:
        conds.append(f"duration <= {int(h.max_duration)}")
    if conds:
        opts["match_filter"] = match_filter_func(" & ".join(conds))
    return opts


def probe_metadata(url: str, recipe=None, quiet: bool = True) -> Optional[dict]:
    """Extract a single video's metadata WITHOUT downloading media. Returns None if the
    video is filtered out (date/duration) or unavailable."""
    from yt_dlp import YoutubeDL

    opts = _base_opts(recipe, quiet)
    opts.update(_filter_opts(recipe) if recipe is not None else {})
    opts["skip_download"] = True
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        return None
    return _normalize_meta(info)


def _resolve_audio_path(ydl, info: dict, audio_format: str) -> str:
    """The path of the post-processed audio file."""
    reqs = info.get("requested_downloads") or []
    if reqs and reqs[0].get("filepath"):
        return reqs[0]["filepath"]
    # fallback: yt-dlp's filename before postprocessing, with the audio extension swapped in
    base = ydl.prepare_filename(info)
    return str(Path(base).with_suffix("." + audio_format))


def download_audio(url: str, out_dir: Path, recipe=None,
                   audio_format: str = "mp3", audio_quality: str = "192",
                   quiet: bool = True) -> Optional[dict]:
    """Download the best audio for `url` to `out_dir` as `audio_format`, returning the
    metadata dict + `audio_path`. Returns None if the video was filtered out (date/
    duration) or yt-dlp produced no info."""
    from yt_dlp import YoutubeDL

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    opts = _base_opts(recipe, quiet)
    opts.update(_filter_opts(recipe) if recipe is not None else {})
    opts.update({
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(upload_date)s_%(id)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_format,
            "preferredquality": str(audio_quality),
        }],
    })
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info is None:          # filtered out by daterange/match_filter
            return None
        audio_path = _resolve_audio_path(ydl, info, audio_format)

    meta = _normalize_meta(info)
    meta["audio_path"] = audio_path
    return meta
