"""Global configuration for the audio transcription tool.

Like the cleaner/translator, transcription has no per-site variation, so there is ONE
global config (backend, model, device, pacing, retention) rather than per-source. A
recipe may override the transcription bits (`whisper.model`/`language`/`backend`) for a
single source. Override any field in `configs/audio_config.yml`. See docs/audio_transcription.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel

# Backends the tool knows about (the factory in transcribe/__init__.py maps these).
AVAILABLE_BACKENDS = ("faster-whisper", "openai-whisper", "openai-api")


class AudioConfig(BaseModel):
    # --- transcription backend / model ---
    backend: str = "faster-whisper"   # faster-whisper (default) | openai-whisper | openai-api
    model: str = "large-v3"           # whisper model name/size (e.g. large-v3, medium, small)
    device: str = "auto"              # auto | cuda | cpu  (local backends)
    compute_type: str = "auto"        # faster-whisper precision: auto|int8|int8_float16|float16|float32
    language: Optional[str] = None    # global default language hint (None => auto-detect per clip)

    # --- audio download / retention ---
    audio_format: str = "mp3"
    audio_quality: str = "192"
    delete_audio_after_transcribe: bool = False  # keep by default; --delete-audio flips it per run

    # --- pacing / checkpointing (mirrors the scraper's light-touch defaults) ---
    rate_limit_delay: float = 0.0     # courtesy pause (s) between videos
    pause_every: int = 0              # take a breather every N videos (0 = never)
    pause_seconds: float = 0.0
    max_consecutive_failures: int = 25  # circuit breaker: stop if downloads/transcribes keep failing
    save_every: int = 5               # checkpoint (flush rows + state) after this many transcriptions

    # --- OpenAI hosted-API backend (paid; only used when backend == openai-api) ---
    openai_key_file: str = "openai_key.txt"   # used only if OPENAI_API_KEY is unset
    openai_api_model: str = "whisper-1"       # or a newer hosted transcription model


DEFAULT_CONFIG_PATH = Path("configs/audio_config.yml")


def load_config(path: Optional[str | Path] = None) -> AudioConfig:
    """Load a config from YAML. With no path, use `configs/audio_config.yml` if it
    exists, else built-in defaults. A missing explicit path also falls back to defaults."""
    if path is None:
        path = DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None
    if path is None:
        return AudioConfig()
    p = Path(path)
    if not p.exists():
        return AudioConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return AudioConfig(**data)
