"""OpusMT backend: Helsinki-NLP per-language-pair MarianMT models (offline).

One model per source language (`Helsinki-NLP/opus-mt-<src>-en`), cached after first load.
Needs `transformers`, `torch`, and `sentencepiece` (the `translate-hf` extra) — imported
lazily, and only when this backend is actually selected. Requires a known source language."""

from __future__ import annotations

from .base import Translator, split_sentences


class OpusMTBackend(Translator):
    name = "opusmt"

    def __init__(self, config=None):
        super().__init__(config)
        self._template = getattr(config, "opusmt_model_template", "Helsinki-NLP/opus-mt-{src}-en")
        self._device = _resolve_device(getattr(config, "device", "auto") if config else "auto")
        self._cache: dict = {}

    def requires_source_language(self) -> bool:
        return True

    def _model_for(self, src: str):
        if src in self._cache:
            return self._cache[src]
        from transformers import MarianMTModel, MarianTokenizer  # lazy
        name = self._template.format(src=src)
        tok = MarianTokenizer.from_pretrained(name)
        model = MarianMTModel.from_pretrained(name).to(self._device)
        model.eval()
        self._cache[src] = (tok, model)
        return self._cache[src]

    def _translate_chunk(self, chunk: str, src_lang: str | None) -> str:
        if not src_lang:
            raise ValueError("OpusMT requires a known source language (set detected_language "
                             "or source_language, or use --translator google)")
        import torch
        tok, model = self._model_for(src_lang.lower())
        out_sentences = []
        for sent in split_sentences(chunk) or [chunk]:
            inputs = tok(sent, return_tensors="pt", padding=True, truncation=True,
                         max_length=512).to(self._device)
            with torch.no_grad():
                generated = model.generate(**inputs, max_new_tokens=512)
            out_sentences.append(tok.decode(generated[0], skip_special_tokens=True))
        return " ".join(out_sentences).strip()


def _resolve_device(device: str) -> str:
    if device and device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"
