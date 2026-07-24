"""Translator backends + the `get_translator` factory.

Backends are imported lazily by name so selecting `google` never imports `transformers`,
and the test suite (which uses a stub translator) imports nothing heavy.
"""

from __future__ import annotations

from .base import Translator, split_into_chunks, split_sentences

__all__ = ["Translator", "get_translator", "split_into_chunks", "split_sentences", "AVAILABLE"]

AVAILABLE = ("google", "googletrans", "opusmt", "nllb")


def get_translator(name: str, config=None) -> Translator:
    """Build the named backend. Raises a clear error for an unknown name or a missing
    optional dependency."""
    key = (name or "google").strip().lower()
    if key == "google":
        from .google import GoogleBackend
        return _construct(GoogleBackend, config, "google", "deep-translator", "translate-google")
    if key == "googletrans":
        from .googletrans import GoogleTransBackend
        return _construct(GoogleTransBackend, config, "googletrans", "httpx", "")
    if key == "opusmt":
        from .opusmt import OpusMTBackend
        return _construct(OpusMTBackend, config, "opusmt", "transformers/torch/sentencepiece", "translate-hf")
    if key == "nllb":
        from .nllb import NLLBBackend
        return _construct(NLLBBackend, config, "nllb", "transformers/torch", "translate-hf")
    raise ValueError(f"unknown translator {name!r}; choose one of {AVAILABLE}")


def _construct(cls, config, name, dep, extra):
    try:
        return cls(config)
    except ImportError as e:  # pragma: no cover - depends on env
        raise ImportError(
            f"the '{name}' backend needs {dep}; install it (e.g. `pip install .[{extra}]`)"
        ) from e
