"""Audio-source description — a *thin*, optional, machine-written record.

The text scraper needs a per-site recipe because every website's HTML is structured
differently (selectors, pagination must be described as data). `yt-dlp` already does
that structural work for video/audio: hand it a playlist/channel/video URL and it
extracts the media + metadata regardless of site. So there is essentially nothing to
author per source. An `AudioRecipe` therefore just records the handful of facts yt-dlp
can't supply — `country` (for the `doc_id` prefix + folder) and, optionally, the
`speaker`/`position`/`language` for a single-leader channel — plus the source URL(s).

Recipes are written by `run --save-recipe` (so a source can be re-run/updated with one
command), NOT hand-authored. `build_recipe()` constructs one from CLI flags; the same
object drives the harvest/run whether it came from flags or a saved YAML.

Its attribute surface intentionally matches `text_scraper.run.map_to_schema`'s needs
(`country`, `iso3n`, `position`, `source_language`, `dataset`) so that mapper is reused
verbatim.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, model_validator

try:  # auto-fill the numeric ISO code; optional at import time
    import pycountry
except Exception:  # pragma: no cover
    pycountry = None


class WhisperSpec(BaseModel):
    """Per-source transcription overrides (else the global `audio_config.yml` wins)."""

    model: Optional[str] = None      # e.g. "large-v3" / "medium" — overrides config.model
    language: Optional[str] = None   # ISO-639-1 hint (e.g. "it"); None => auto-detect
    backend: Optional[str] = None    # overrides config.backend (faster-whisper/openai-whisper/openai-api)


class HarvestSpec(BaseModel):
    """How to enumerate + filter videos from the source URL(s)."""

    kind: Optional[str] = None        # playlist | channel | url_list (auto-detected from the URL if None)
    max_videos: Optional[int] = None  # cap the number harvested
    match_title: Optional[str] = None # regex a video title must match to qualify
    date_min: Optional[str] = None    # YYYYMMDD — skip uploads before this (yt-dlp daterange)
    date_max: Optional[str] = None    # YYYYMMDD — skip uploads after this
    min_duration: Optional[int] = None  # seconds — skip shorter clips (yt-dlp match_filter)
    max_duration: Optional[int] = None  # seconds — skip longer items


class AudioRecipe(BaseModel):
    # identity / provenance
    source_id: str
    country: str
    iso3n: Optional[int] = None             # auto-filled from country if omitted
    source_language: str = "English"        # routes title/text/context to *_originlanguage when not English
    dataset: str = "LeaderSpeech"           # provenance tag (stays LeaderSpeech for audio too)
    source_type: str = "audio"              # discriminator; the index keys the audio marker off this/the sidecar

    # where to get the media
    start_urls: list[str] = Field(default_factory=list)  # channel / playlist / single-video URLs
    links_file: Optional[str] = None        # a pre-harvested URL list (one per line), like _links.txt
    harvest: HarvestSpec = Field(default_factory=HarvestSpec)

    # fixed values for single-leader channels (else left blank for the cleaner to fill)
    speaker_default: Optional[str] = None
    position: Optional[str] = None

    # transcription + download knobs
    whisper: WhisperSpec = Field(default_factory=WhisperSpec)
    audio_format: str = "mp3"
    audio_quality: str = "192"
    user_agent: Optional[str] = None        # some sites gate downloads on UA
    cookies_from_browser: Optional[str] = None  # e.g. "chrome" — for login-gated channels
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _checks(self):
        if not self.start_urls and not self.links_file:
            raise ValueError("recipe needs start_urls and/or links_file")
        if self.iso3n is None and pycountry is not None:
            try:
                self.iso3n = int(pycountry.countries.lookup(self.country).numeric)
            except Exception:
                pass
        return self


# --- construction helpers (shared by the harvest/run/probe CLIs) ---------------

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(s: str, maxlen: int = 40) -> str:
    s = _SLUG_RE.sub("-", (s or "").lower()).strip("-")
    return s[:maxlen].strip("-")


def _alpha3_lower(country: str) -> str:
    if pycountry is not None:
        try:
            return pycountry.countries.lookup(country).alpha_3.lower()
        except Exception:
            pass
    return _slugify(country)[:3] or "xxx"


def derive_source_id(url: Optional[str], country: str, explicit: Optional[str] = None) -> str:
    """A stable slug for a source: `<iso3>_<host-or-list-tail>`. Override with --id."""
    if explicit:
        return _slugify(explicit, 60)
    prefix = _alpha3_lower(country)
    if not url:
        return f"{prefix}_audio"
    p = urlparse(url)
    host = (p.netloc or "").replace("www.", "").split(".")[0]
    # prefer a playlist id / channel handle / last path segment as the distinguishing tail
    tail = ""
    if "list=" in (p.query or ""):
        tail = re.search(r"list=([^&]+)", p.query).group(1)
    elif p.path:
        tail = [seg for seg in p.path.split("/") if seg][-1] if [seg for seg in p.path.split("/") if seg] else ""
    slug = _slugify(f"{host}-{tail}".strip("-")) or host or "audio"
    return f"{prefix}_{slug}"


def build_recipe(
    *,
    country: str,
    urls: Optional[list[str]] = None,
    links_file: Optional[str] = None,
    source_id: Optional[str] = None,
    speaker: Optional[str] = None,
    position: Optional[str] = None,
    language: str = "English",
    dataset: str = "LeaderSpeech",
    backend: Optional[str] = None,
    model: Optional[str] = None,
    whisper_language: Optional[str] = None,
    harvest: Optional[HarvestSpec] = None,
    user_agent: Optional[str] = None,
    cookies_from_browser: Optional[str] = None,
    notes: Optional[str] = None,
) -> AudioRecipe:
    """Build an `AudioRecipe` from primitive CLI params (the no-YAML path)."""
    urls = [u for u in (urls or []) if u]
    sid = derive_source_id(urls[0] if urls else None, country, source_id)
    return AudioRecipe(
        source_id=sid,
        country=country,
        source_language=language,
        dataset=dataset,
        start_urls=urls,
        links_file=links_file,
        harvest=harvest or HarvestSpec(),
        speaker_default=speaker,
        position=position,
        whisper=WhisperSpec(model=model, language=whisper_language, backend=backend),
        user_agent=user_agent,
        cookies_from_browser=cookies_from_browser,
        notes=notes,
    )


def load_recipe(path: str | Path) -> AudioRecipe:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return AudioRecipe(**data)


def save_recipe(recipe: AudioRecipe, path: str | Path) -> Path:
    """Write a clean YAML capturing exactly what a re-run/update needs. Empty/default
    nested blocks are dropped so saved recipes stay readable."""
    data = recipe.model_dump(exclude_none=True)
    # drop empty nested dicts (harvest/whisper with no set fields)
    for key in ("harvest", "whisper"):
        if not data.get(key):
            data.pop(key, None)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Auto-generated by `video_audio_scraper.run --save-recipe`.\n"
        "# yt-dlp does the per-site work; this just records the source + a few fixed fields\n"
        "# so the source can be re-run/updated with one command. See recipes_audio/README.md.\n"
    )
    p.write_text(header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p
