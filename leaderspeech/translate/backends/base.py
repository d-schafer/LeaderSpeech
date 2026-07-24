"""The pluggable translator interface + shared long-text chunking.

A `Translator` turns one string of source text into English. The base class owns the
boilerplate every backend needs — empty handling and splitting over-long text at
sentence/punctuation boundaries (ported from the project's R `splitTextIntoChunks`) —
so each backend only implements `_translate_chunk`.
"""

from __future__ import annotations

import re
import time


def split_into_chunks(text: str, max_chars: int) -> list[str]:
    """Split `text` into pieces no longer than `max_chars`, preferring to break at the
    last sentence end (then other punctuation, then whitespace) before the limit so a
    chunk never cuts mid-word. Mirrors the R `splitTextIntoChunks` heuristic."""
    text = text or ""
    chunks: list[str] = []
    while len(text) > max_chars:
        window = text[:max_chars]
        # last sentence end, then other punctuation, then any whitespace
        split_pos = max(window.rfind(". "), window.rfind(".\n"), window.rfind("。"))
        if split_pos == -1:
            for p in ("? ", "! ", "; ", ", ", "\n", " "):
                split_pos = window.rfind(p)
                if split_pos != -1:
                    break
        if split_pos == -1:
            split_pos = max_chars - 1  # no boundary found: hard split
        chunks.append(text[: split_pos + 1])
        text = text[split_pos + 1 :]
    if text:
        chunks.append(text)
    return chunks


class Translator:
    """Base translator. Subclasses set `name` and implement `_translate_chunk`."""

    name = "base"

    def __init__(self, config=None):
        self.config = config
        self.target = getattr(config, "target_language", "en") if config else "en"
        self.max_chunk_chars = getattr(config, "max_chunk_chars", 4500) if config else 4500

    def translate(self, text: str, src_lang: str | None = None) -> str:
        """Translate `text` to the target language, chunking if it's too long.
        Empty/whitespace input returns ''."""
        if text is None or not str(text).strip():
            return ""
        text = str(text)
        if len(text) <= self.max_chunk_chars:
            return self._chunk(text, src_lang)
        pieces = split_into_chunks(text, self.max_chunk_chars)
        out = [self._chunk(c, src_lang) for c in pieces if c.strip()]
        return " ".join(p for p in out if p).strip()

    def _chunk(self, chunk: str, src_lang: str | None) -> str:
        """One chunk, with pacing + retry/backoff so a transient online rate-limit self-heals
        instead of dropping the row. Paces before each call (config.call_delay) and, on failure,
        waits an exponentially growing backoff before retrying (config.retries / config.backoff)."""
        delay = getattr(self.config, "call_delay", 0.0) if self.config else 0.0
        retries = getattr(self.config, "retries", 0) if self.config else 0
        backoff = getattr(self.config, "backoff", 2.0) if self.config else 2.0
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            if delay:
                time.sleep(delay)
            try:
                return self._translate_chunk(chunk, src_lang)
            except Exception as e:      # noqa: BLE001 — retry any transient backend error
                last_err = e
                if attempt < retries:
                    time.sleep(backoff * (2 ** attempt))
        raise last_err

    def _translate_chunk(self, chunk: str, src_lang: str | None) -> str:
        raise NotImplementedError

    # Backends that need an explicit source language override this.
    def requires_source_language(self) -> bool:
        return False


def split_sentences(text: str) -> list[str]:
    """Sentence split used by the token-budget backends (OpusMT/NLLB)."""
    return [s for s in re.split(r"(?<=[.!?。！？])\s+", text or "") if s.strip()]
