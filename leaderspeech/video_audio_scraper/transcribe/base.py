"""The pluggable transcriber interface.

A `Transcriber` turns one audio file into text (+ a detected language). The base class
owns the trivial shared bits; each backend implements `transcribe`. Mirrors the
translator backends' shape so the two tools feel the same.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


class Transcriber:
    """Base transcriber. Subclasses set `name` and implement `transcribe`."""

    name = "base"

    def __init__(self, config=None, *, model: Optional[str] = None, language: Optional[str] = None):
        self.config = config
        # per-recipe overrides win over the global config defaults
        self.model = model or (getattr(config, "model", None) if config else None)
        self.language = language or (getattr(config, "language", None) if config else None)

    def transcribe(self, audio_path: str | Path, language: Optional[str] = None) -> dict:
        """Return {"text": <str>, "language": <detected ISO code or "">}."""
        raise NotImplementedError

    def close(self) -> None:  # backends holding a model/client may override
        pass
