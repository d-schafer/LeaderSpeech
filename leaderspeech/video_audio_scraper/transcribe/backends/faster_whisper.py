"""faster-whisper backend (default).

CTranslate2 reimplementation of Whisper: same models (incl. large-v3), markedly faster,
lower VRAM, and crucially does NOT pull `torch`. GPU or CPU (int8). The model is loaded
once per run and reused across every clip.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ..base import Transcriber

log = logging.getLogger("leaderspeech.video_audio_scraper.transcribe.faster_whisper")


def _resolve(config):
    device = (getattr(config, "device", None) or "auto") if config else "auto"
    compute = (getattr(config, "compute_type", None) or "auto") if config else "auto"
    if compute == "auto":
        compute = "default"   # let CTranslate2 pick per device (float16 on GPU, int8 on CPU)
    return device, compute


class FasterWhisperBackend(Transcriber):
    name = "faster-whisper"

    def __init__(self, config=None, *, model: Optional[str] = None, language: Optional[str] = None):
        super().__init__(config, model=model, language=language)
        from faster_whisper import WhisperModel  # ImportError -> factory gives an install hint

        device, compute = _resolve(config)
        model_name = self.model or "large-v3"
        log.info("loading faster-whisper model=%s device=%s compute=%s", model_name, device, compute)
        self._model = WhisperModel(model_name, device=device, compute_type=compute)
        self.model = model_name

    def transcribe(self, audio_path: str | Path, language: Optional[str] = None) -> dict:
        lang = language or self.language or None
        segments, info = self._model.transcribe(str(audio_path), language=lang)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return {"text": text, "language": getattr(info, "language", lang) or ""}
