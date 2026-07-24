"""Google 'translate_a/single' endpoint backend.

This is the lighter Google endpoint that the project's R `gtranslate` pipeline (and libraries like
py-googletrans) use — it tolerates chunk bursts and long documents far better than deep-translator's
consumer-web-page scrape (the `google` backend), which is why long speeches translated fine in R.

Trade-off: `translate_a/single` is an UNOFFICIAL endpoint with no stability guarantee — Google can
change or block it without notice — so treat it as best-effort. No extra dependency (uses httpx,
already required); the base class still handles chunking + retry/backoff around each call.
"""

from __future__ import annotations

import httpx

from .base import Translator

_URL = "https://translate.googleapis.com/translate_a/single"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class GoogleTransBackend(Translator):
    name = "googletrans"

    def _translate_chunk(self, chunk: str, src_lang: str | None) -> str:
        src = (src_lang or "auto").lower()
        params = {"client": "gtx", "sl": src, "tl": self.target, "dt": "t"}
        # POST the text in the body, not the query string: non-Latin chars URL-encode to ~9x their
        # length (each byte -> %XX), so a 4500-char Dari/Pashto chunk would overflow the URL limit
        # (400 Bad Request) as a GET.
        r = httpx.post(_URL, params=params, data={"q": chunk}, timeout=30.0,
                       headers={"User-Agent": _UA})
        r.raise_for_status()
        data = r.json()
        # data[0] is a list of [translated_segment, original_segment, ...]; join the translations.
        if not data or not isinstance(data, list) or not data[0]:
            return ""
        return "".join(seg[0] for seg in data[0] if seg and seg[0]) or ""
