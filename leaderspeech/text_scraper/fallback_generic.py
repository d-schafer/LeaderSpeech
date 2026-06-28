"""Generic article extraction (best-effort, no recipe).

For URLs that don't yet have a hand-tuned recipe, trafilatura does a respectable
job of pulling the main body, title, date, and author out of arbitrary article
pages. Use it to triage a new source quickly, or as a last resort. A real recipe
will almost always beat it -- treat its output as a draft, not ground truth.
"""

from __future__ import annotations

from typing import Optional

import trafilatura

from .extract import clean_text


def extract_generic(html: str, url: Optional[str] = None) -> dict:
    text = trafilatura.extract(
        html, url=url, include_comments=False, favor_recall=True
    )
    title = date = author = None
    try:
        meta = trafilatura.extract_metadata(html)
        if meta is not None:
            title, date, author = meta.title, meta.date, meta.author
    except Exception:
        pass

    return {
        "title": clean_text(title),
        "text": clean_text(text),
        "date": date,        # ISO string when trafilatura finds one, else None
        "speaker": clean_text(author),
        "context": "",
        "source": url or "",
    }
