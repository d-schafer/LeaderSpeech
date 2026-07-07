"""Google Translate backend via `deep-translator` (the default).

Online, free, and light to install — runs in the `leaderspeech_scrape` venv. `deep-translator`
is imported lazily so the package stays importable without it. Source language may be a known
ISO code or 'auto' (Google auto-detects, which is reliable for these speeches)."""

from __future__ import annotations

from .base import Translator


class GoogleBackend(Translator):
    name = "google"

    def _translator_for(self, src: str):
        from deep_translator import GoogleTranslator  # lazy import
        return GoogleTranslator(source=src or "auto", target=self.target)

    def _translate_chunk(self, chunk: str, src_lang: str | None) -> str:
        src = (src_lang or "auto").lower()
        try:
            out = self._translator_for(src).translate(chunk)
        except Exception:
            # an unrecognized source code → fall back to auto-detect
            out = self._translator_for("auto").translate(chunk)
        return out or ""
