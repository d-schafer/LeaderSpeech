"""Configuration for the leader-tenure curation tool.

Two models by design: a cheap pre-filter classifier and a stronger verifier (the step that
needs real world knowledge — this is the model the researcher validated for it). Override any
field in `configs/tenure_config.yml`, or per run with --classify-model / --verify-model / --model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class TenureConfig(BaseModel):
    # --- models (classification is a cheap pre-filter; verification needs world knowledge) ---
    classify_model: str = "gpt-4.1-mini"
    verify_model: str = "gpt-4.1"
    temperature: float = 0.0
    max_tokens: int = 250

    # --- concurrency ---
    batch_size: int = 25
    rate_limit_delay: float = 0.1
    chunk_size: int = 100

    # --- inputs: where to read the speeches and the tenure key ---
    # Preference order for the speech dataset; falls back to cleaned per-source Parquets.
    dataset_candidates: list[str] = Field(default_factory=lambda: [
        "data/LeaderSpeech.parquet",                 # final (post-fixNames, cleanest names)
        "data/_build/LeaderSpeech_merged.parquet",   # merged intermediate
    ])
    cleaned_root: str = "data/cleaned"
    tenure_file: str = "data/sources/leader_tenure_final.csv"
    tenure_window: int = 1

    # --- outputs (NEVER the tenure key itself) ---
    outbox: str = "data/sources/leader_tenure_proposed_additions.xlsx"
    inventory_out: str = "data/sources/leader_tenure_inventory.xlsx"

    # --- verification / merge thresholds ---
    use_wikipedia: bool = False                      # opt-in live Wikipedia grounding
    min_confidence: list[str] = Field(default_factory=lambda: ["high", "medium"])

    # --- secrets ---
    openai_key_file: str = "openai_key.txt"


DEFAULT_CONFIG_PATH = Path("configs/tenure_config.yml")


def load_config(path: Optional[str | Path] = None) -> TenureConfig:
    """Load a config from YAML, falling back to built-in defaults if absent."""
    if path is None:
        path = DEFAULT_CONFIG_PATH if DEFAULT_CONFIG_PATH.exists() else None
    if path is None:
        return TenureConfig()
    p = Path(path)
    if not p.exists():
        return TenureConfig()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return TenureConfig(**data)
