"""Configuration for the metadata-cleaning tool.

Unlike the scraper, cleaning has no per-site variation, so there is ONE global
config (model, batch/checkpoint sizes, gate toggles, tenure path) rather than a
recipe per source. Defaults are sensible for a cheap, resumable production run;
override any field in `configs/clean_config.yml`. See docs/cleaning.md → "Configuration
reference" for what each gate setting does.

The two gate knobs that change WHAT IS KEPT:
  - keep_document_types: which document kinds count as "representing the leader" and are
    kept. Default keeps delivered speeches, interviews, AND official statements/communiqués
    (incl. third-person ones that convey the leader's position). Drop "official_statement"
    from the list to keep only things the leader said aloud.
  - require_leader_type: when True, set aside speakers the model marks as foreign visitors
    or non-leader ministers. Set False to keep every representative document regardless of
    the speaker's role.
Rejected rows are never deleted — they're retained with a `rejected_*` clean_status.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

# document_type values kept by default (those that represent the leader's words/position)
DEFAULT_KEEP_DOCUMENT_TYPES = ["speech", "interview", "official_statement"]


class CleanConfig(BaseModel):
    # --- model / API ---
    model: str = "gpt-4.1-mini"      # cheap structured-extraction model; override per run with --model
    temperature: float = 0.0
    max_tokens: int = 500
    max_words: int = 500             # truncate the speech text sent to the model

    # --- concurrency / checkpointing (mirrors the proven gpt_speakers_confirm.py knobs) ---
    batch_size: int = 25             # max concurrent requests
    rate_limit_delay: float = 0.1    # seconds to wait inside the semaphore before each request
    chunk_size: int = 100            # rows per asyncio.gather() == one checkpoint
    max_consecutive_failures: int = 50  # circuit breaker: stop if the API keeps failing

    # --- hard gate (every kept row must have a speaker and represent the leader) ---
    keep_document_types: list[str] = Field(default_factory=lambda: list(DEFAULT_KEEP_DOCUMENT_TYPES))
    require_leader_type: bool = True  # reject clearly-non-leader speakers (minister/foreign/other)

    # --- tenure crosscheck ---
    tenure_file: str = "data/sources/leader_tenure_final.csv"
    tenure_window: int = 1           # +/- years when listing plausible leaders

    # --- storage ---
    compression: str = "zstd"        # parquet codec; "snappy" is the conservative fallback

    # --- secrets ---
    openai_key_file: str = "openai_key.txt"  # used only if OPENAI_API_KEY is unset


DEFAULT_CONFIG_PATH = Path("configs/clean_config.yml")


def load_config(path: Optional[str | Path] = None) -> CleanConfig:
    """Load a config from YAML. With no path, use `configs/clean_config.yml` if it
    exists, else built-in defaults. A missing explicit path also falls back to defaults."""
    if path is None:
        path = DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None
    if path is None:
        return CleanConfig()
    p = Path(path)
    if not p.exists():
        return CleanConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return CleanConfig(**data)
