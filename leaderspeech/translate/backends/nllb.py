"""NLLB backend: facebook/nllb-200, one multilingual model for all languages (offline).

Carries the ISO 639-1 -> NLLB BCP-47 map from the project's `translate_training.py`.
Needs `transformers` + `torch` (the `translate-hf` extra), imported lazily and only when
selected. Splits long text by a source-token budget (like the reference script) and forces
the English target language at generation. Requires a known source language."""

from __future__ import annotations

from .base import Translator, split_sentences

# ISO 639-1 -> NLLB BCP-47 (from translate_training.py)
ISO_TO_NLLB = {
    "af": "afr_Latn", "am": "amh_Ethi", "ar": "arb_Arab", "az": "azj_Latn",
    "be": "bel_Cyrl", "bg": "bul_Cyrl", "bs": "bos_Latn", "ca": "cat_Latn",
    "cs": "ces_Latn", "da": "dan_Latn", "de": "deu_Latn", "el": "ell_Grek",
    "en": "eng_Latn", "es": "spa_Latn", "et": "est_Latn", "fa": "pes_Arab",
    "fi": "fin_Latn", "fr": "fra_Latn", "ga": "gle_Latn", "he": "heb_Hebr",
    "hi": "hin_Deva", "hr": "hrv_Latn", "hu": "hun_Latn", "hy": "hye_Armn",
    "id": "ind_Latn", "is": "isl_Latn", "it": "ita_Latn", "ja": "jpn_Jpan",
    "ka": "kat_Geor", "kk": "kaz_Cyrl", "ko": "kor_Hang", "lt": "lit_Latn",
    "lv": "lvs_Latn", "mk": "mkd_Cyrl", "ms": "zsm_Latn", "nl": "nld_Latn",
    "no": "nob_Latn", "pl": "pol_Latn", "pt": "por_Latn", "ro": "ron_Latn",
    "ru": "rus_Cyrl", "sk": "slk_Latn", "sl": "slv_Latn", "sq": "als_Latn",
    "sr": "srp_Cyrl", "sv": "swe_Latn", "sw": "swh_Latn", "th": "tha_Thai",
    "tr": "tur_Latn", "uk": "ukr_Cyrl", "ur": "urd_Arab", "vi": "vie_Latn",
    "zh": "zho_Hans",
}
TARGET_BCP47 = {"en": "eng_Latn"}


class NLLBBackend(Translator):
    name = "nllb"

    def __init__(self, config=None):
        super().__init__(config)
        self._model_name = getattr(config, "nllb_model", "facebook/nllb-200-distilled-600M")
        self._device = _resolve_device(getattr(config, "device", "auto") if config else "auto")
        self._max_new = getattr(config, "nllb_max_tokens", 512) if config else 512
        self._chunk_tokens = getattr(config, "nllb_chunk_tokens", 400) if config else 400
        self._tok = None
        self._model = None

    def requires_source_language(self) -> bool:
        return True

    def _load(self):
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # lazy
        self._tok = AutoTokenizer.from_pretrained(self._model_name)
        dtype = torch.float16 if self._device == "cuda" else torch.float32
        self._model = AutoModelForSeq2SeqLM.from_pretrained(
            self._model_name, torch_dtype=dtype).to(self._device)
        self._model.eval()

    def _token_chunks(self, text: str) -> list[str]:
        """Greedy sentence packing under a source-token budget (per translate_training.py)."""
        test = self._tok(text, return_tensors="pt", truncation=False)
        if test.input_ids.shape[1] <= self._chunk_tokens * 2:
            return [text]
        chunks, current = [], []
        for sent in split_sentences(text) or [text]:
            current.append(sent)
            joined = " ".join(current)
            if self._tok(joined, return_tensors="pt", truncation=False).input_ids.shape[1] > self._chunk_tokens:
                chunks.append(joined)
                current = []
        if current:
            chunks.append(" ".join(current))
        return chunks

    def _translate_chunk(self, chunk: str, src_lang: str | None) -> str:
        if not src_lang:
            raise ValueError("NLLB requires a known source language (set detected_language "
                             "or source_language, or use --translator google)")
        src_code = ISO_TO_NLLB.get(src_lang.lower())
        if src_code is None:
            raise ValueError(f"no NLLB mapping for source language {src_lang!r}; add it to ISO_TO_NLLB")
        self._load()
        import torch
        self._tok.src_lang = src_code
        tgt_code = TARGET_BCP47.get(self.target, "eng_Latn")
        tgt_id = self._tok.convert_tokens_to_ids(tgt_code)
        out = []
        for piece in self._token_chunks(chunk):
            inputs = self._tok(piece, return_tensors="pt", truncation=True, max_length=1024).to(self._device)
            with torch.no_grad():
                gen = self._model.generate(**inputs, forced_bos_token_id=tgt_id,
                                           max_new_tokens=self._max_new)
            out.append(self._tok.decode(gen[0], skip_special_tokens=True))
        return " ".join(out).strip()


def _resolve_device(device: str) -> str:
    if device and device != "auto":
        return device
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"
