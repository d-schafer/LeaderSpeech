"""PDF speech-page support.

Some high-value archives serve speeches as **PDFs**, not HTML (e.g. Brazil's
Biblioteca da Presidência — the only source for Lula I–II, 2003–2010). When a
harvested URL is a PDF, the engine downloads the bytes and extracts text with a PDF
library instead of BeautifulSoup, then maps the result into the same schema. All the
routing lives in ``run.py``; this module is just the primitives:

  * :func:`is_pdf_url`     — does a URL look like a PDF? (auto-detection)
  * :func:`looks_like_pdf` — do these bytes start with the ``%PDF`` magic?
  * :func:`pdf_bytes_to_text` — extract text from PDF bytes.

The PDF library is imported **lazily** (like the translator backends), so pdfminer.six
/ pypdf is only required when a PDF source is actually run — the rest of the engine
never pays for it. Install with ``pip install 'leaderspeech[pdf]'``.
"""

from __future__ import annotations

import io
import logging
import re
from urllib.parse import urlparse

log = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF-"

# A URL points at a PDF if a path segment ends in `.pdf` (optionally followed by more
# path, e.g. Plone's `<file>.pdf/@@download/file/<name>.pdf` or `<file>.pdf/view`), or
# if it uses a Plone-style `@@download` handler. Kept as a search (not full-match) so a
# `.pdf` anywhere in the path counts; the query string is ignored.
_PDF_URL_RE = re.compile(r"\.pdf($|[/?#])", re.IGNORECASE)


def is_pdf_url(url: str) -> bool:
    """Heuristic: does this URL point at a PDF? True for a `.pdf` path segment or a
    Plone `@@download` handler. Note some sources serve PDFs from URLs with *no* `.pdf`
    hint (the Plone object id lacks the extension) — force those with `content_type: pdf`."""
    if not url:
        return False
    if "@@download" in url.lower():
        return True
    path = urlparse(url).path
    return bool(_PDF_URL_RE.search(path))


def looks_like_pdf(data) -> bool:
    """True if `data` is bytes beginning with the ``%PDF`` magic (a real PDF), tolerating
    a little leading whitespace/BOM some producers emit before the header."""
    if not isinstance(data, (bytes, bytearray)):
        return False
    return PDF_MAGIC in bytes(data[:1024])


def _extract_pdfminer(data: bytes) -> str:
    """Text via pdfminer.six (better layout handling). Lets ImportError propagate so the
    caller can fall through to pypdf; swallows only parse errors."""
    from pdfminer.high_level import extract_text  # ImportError -> caller tries pypdf

    try:
        return extract_text(io.BytesIO(data)) or ""
    except Exception as e:  # a malformed/encrypted PDF shouldn't crash the run
        log.warning("pdfminer failed to parse a PDF: %s", e)
        return ""


def _extract_pypdf(data: bytes) -> str:
    """Text via pypdf (fallback). Same contract as :func:`_extract_pdfminer`."""
    from pypdf import PdfReader  # ImportError -> caller has no backend left

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as e:
        log.warning("pypdf failed to parse a PDF: %s", e)
        return ""


def _any_backend_available() -> bool:
    for mod in ("pdfminer.high_level", "pypdf"):
        try:
            __import__(mod)
            return True
        except Exception:
            continue
    return False


def pdf_bytes_to_text(data: bytes) -> str:
    """Extract text from PDF bytes, trying pdfminer.six then pypdf. Returns "" when the
    PDF has no extractable text (e.g. a scanned image), and raises a clear RuntimeError
    when no PDF library is installed at all."""
    for extractor in (_extract_pdfminer, _extract_pypdf):
        try:
            text = extractor(data)
        except ImportError:
            continue  # this backend isn't installed; try the next
        if text and text.strip():
            return text
    if not _any_backend_available():
        raise RuntimeError(
            "PDF support needs a PDF library — install with "
            "`pip install 'leaderspeech[pdf]'` (pdfminer.six)."
        )
    return ""  # a backend ran but the PDF yielded no text (e.g. image-only scan)
