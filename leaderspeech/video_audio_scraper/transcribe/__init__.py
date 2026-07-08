"""Transcriber backends + the `get_transcriber` factory.

Backends are imported lazily by name so selecting `faster-whisper` never imports
`torch` (which only `openai-whisper` needs), and the test suite (which uses a stub
transcriber) imports nothing heavy.
"""

from __future__ import annotations

from typing import Optional

from .base import Transcriber

__all__ = ["Transcriber", "get_transcriber", "AVAILABLE"]

AVAILABLE = ("faster-whisper", "openai-whisper", "openai-api")


def get_transcriber(name: str, config=None, *, model: Optional[str] = None,
                    language: Optional[str] = None) -> Transcriber:
    """Build the named backend. Raises a clear error for an unknown name or a missing
    optional dependency."""
    key = (name or "faster-whisper").strip().lower().replace("_", "-")
    if key in ("faster-whisper", "fasterwhisper"):
        from .backends.faster_whisper import FasterWhisperBackend
        return _construct(FasterWhisperBackend, config, model, language,
                          "faster-whisper", "faster-whisper", "audio")
    if key in ("openai-whisper", "whisper"):
        from .backends.openai_whisper import OpenAIWhisperBackend
        return _construct(OpenAIWhisperBackend, config, model, language,
                          "openai-whisper", "openai-whisper", "audio-openai-whisper")
    if key in ("openai-api", "openai", "api"):
        from .backends.openai_api import OpenAIAPIBackend
        return _construct(OpenAIAPIBackend, config, model, language,
                          "openai-api", "openai", "llm")
    raise ValueError(f"unknown transcriber {name!r}; choose one of {AVAILABLE}")


def _construct(cls, config, model, language, name, dep, extra):
    try:
        return cls(config, model=model, language=language)
    except ImportError as e:  # pragma: no cover - depends on env
        raise ImportError(
            f"the '{name}' backend needs {dep}; install it (e.g. `pip install .[{extra}]`)"
        ) from e
