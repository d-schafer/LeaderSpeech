"""openai-whisper backend (the reference implementation the prototypes used).

Local, free, but needs a (CUDA) `torch` install — heavier than faster-whisper. Kept as
an alternative for parity with the old scripts / for environments that already have torch.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ..base import Transcriber

log = logging.getLogger("leaderspeech.video_audio_scraper.transcribe.openai_whisper")


class OpenAIWhisperBackend(Transcriber):
    name = "openai-whisper"

    def __init__(self, config=None, *, model: Optional[str] = None, language: Optional[str] = None):
        super().__init__(config, model=model, language=language)
        import whisper  # ImportError -> factory gives an install hint

        device = (getattr(config, "device", None) or None) if config else None
        if device == "auto":
            device = None  # let whisper pick (cuda if available)
        model_name = self.model or "medium"
        log.info("loading openai-whisper model=%s device=%s", model_name, device or "auto")
        self._model = whisper.load_model(model_name, device=device)
        self.model = model_name

    def transcribe(self, audio_path: str | Path, language: Optional[str] = None) -> dict:
        lang = language or self.language or None
        result = self._model.transcribe(str(audio_path), language=lang)
        return {"text": (result.get("text") or "").strip(),
                "language": result.get("language", lang) or ""}
