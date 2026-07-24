"""Configuration for the translation tool.

Like the cleaner, there is ONE global config (no per-site variation). Defaults are
tuned for the Google/`deep-translator` backend running in the `leaderspeech_scrape`
venv; the OpusMT and NLLB backends add their own model knobs (used only when selected).
Override any field in `configs/translate_config.yml`. See docs/translation.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

# Which columns get translated: each `<field>` is filled from `<field>_originlanguage`.
DEFAULT_FIELDS = ["text", "title", "context"]


class TranslateConfig(BaseModel):
    # --- backend selection ---
    translator: str = "google"          # google | opusmt | nllb  (override with --translator)
    target_language: str = "en"         # ISO 639-1 of the English-target columns

    # --- what to translate ---
    fields: list[str] = Field(default_factory=lambda: list(DEFAULT_FIELDS))
    only_accepted: bool = True          # on a cleaned Parquet, skip rejected rows (saves online calls)

    # --- chunking / pacing (the online backend has a ~5000-char limit + rate limits) ---
    max_chunk_chars: int = 4500         # split longer text at sentence/punctuation boundaries
    pause_every: int = 50               # after this many translated rows, breathe
    pause_seconds: float = 1.0          # ...for this long (online backends only)
    call_delay: float = 0.5             # wait this long before EACH online API call (rate-limit guard;
                                        # set 0 for the local HF backends, which don't rate-limit)
    retries: int = 3                    # retry a failed chunk this many times (transient rate-limits)
    backoff: float = 2.0                # exponential backoff base seconds between chunk retries

    # --- checkpointing / storage ---
    checkpoint_every: int = 50          # rows between atomic rewrites of the file
    compression: str = "zstd"           # parquet codec

    # --- OpusMT backend (Helsinki-NLP per-language-pair MarianMT) ---
    opusmt_model_template: str = "Helsinki-NLP/opus-mt-{src}-en"

    # --- NLLB backend (facebook/nllb-200; one multilingual model) ---
    nllb_model: str = "facebook/nllb-200-distilled-600M"  # set to nllb-200-3.3B for top quality
    nllb_chunk_tokens: int = 400        # split text into chunks of <=this many source tokens (< 1024)
    nllb_max_tokens: int = 640          # generation cap per chunk (headroom over chunk_tokens so the
                                        # translation of a full chunk isn't truncated on the output side)

    # --- device for the local (HF) backends ---
    device: str = "auto"                # auto | cuda | cpu


DEFAULT_CONFIG_PATH = Path("configs/translate_config.yml")


def load_config(path: Optional[str | Path] = None) -> TranslateConfig:
    """Load a config from YAML. With no path, use `configs/translate_config.yml` if it
    exists, else built-in defaults. A missing explicit path also falls back to defaults."""
    if path is None:
        path = DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None
    if path is None:
        return TranslateConfig()
    p = Path(path)
    if not p.exists():
        return TranslateConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return TranslateConfig(**data)
