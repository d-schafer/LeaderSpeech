"""OpenAI hosted-API backend (paid; no GPU needed).

Sends each audio file to the hosted transcription endpoint. A FULL-RUN cost gate, like
the cleaner: every clip is billed per-minute. Key resolution mirrors the cleaner
(`OPENAI_API_KEY` env, then `openai_key.txt`).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from ..base import Transcriber

log = logging.getLogger("leaderspeech.video_audio_scraper.transcribe.openai_api")


def _load_api_key(config) -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key and key.strip():
        return key.strip()
    name = getattr(config, "openai_key_file", "openai_key.txt") if config else "openai_key.txt"
    seen = []
    for base in (Path.cwd(), Path.cwd().parent, Path(__file__).resolve().parents[4]):
        cand = (base / name) if not Path(name).is_absolute() else Path(name)
        seen.append(str(cand))
        if cand.exists():
            return cand.read_text(encoding="utf-8").strip()
    raise RuntimeError(
        f"No OpenAI key found. Set OPENAI_API_KEY, or place '{name}' in one of: {seen}"
    )


class OpenAIAPIBackend(Transcriber):
    name = "openai-api"

    def __init__(self, config=None, *, model: Optional[str] = None, language: Optional[str] = None):
        super().__init__(config, model=model, language=language)
        from openai import OpenAI  # ImportError -> factory gives an install hint

        self._client = OpenAI(api_key=_load_api_key(config))
        self.model = model or (getattr(config, "openai_api_model", None) if config else None) or "whisper-1"

    def transcribe(self, audio_path: str | Path, language: Optional[str] = None) -> dict:
        lang = language or self.language or None
        with open(audio_path, "rb") as f:
            resp = self._client.audio.transcriptions.create(
                model=self.model, file=f, language=lang or None)
        return {"text": (getattr(resp, "text", "") or "").strip(), "language": lang or ""}
