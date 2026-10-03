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
import os
import re
from typing import Optional
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


# --- truncated PDFs ---------------------------------------------------------------------------
# The Internet Archive holds many large PDFs only as a PREFIX: stored cut at exactly 1 MiB or
# 5 MiB, or replayed with the original length and dropped after the stored 1.4–2.9 MB (measured on
# the Biblioteca da Presidência, 2026-10-02: 35 of 35 sampled "no text layer" failures). A PDF
# keeps its page tree and cross-reference table at the END, so a prefix opens nowhere (Adobe:
# "damaged"; qpdf: "root of pages tree has no /Kids array"; PDFium: "Data format error") even
# though its first pages are intact. `repair_truncated_pdf` rebuilds a page tree over the pages
# that survive; rows built from one are flagged `document_truncated` (`truncation_note`).

def truncation_note(data) -> str:
    """'' for a complete PDF (or anything that is not a PDF); otherwise a short description of
    what was stored, for the `document_truncated` column and error texts, e.g.
    '1048576 of 30462354 bytes stored' or '1404466 of 23680765 bytes stored (Archive hung up)'.
    Complete = an `%%EOF` trailer within the last 4 KB (the same test as run._complete_document).
    The original size comes from wayback.SnapshotBytes when the replay said what it was."""
    if not looks_like_pdf(data) or b"%%EOF" in bytes(data[-4096:]):
        return ""
    stored = len(data)
    real = getattr(data, "real_size", None)
    note = (f"{stored} of {real} bytes stored" if real and real > stored
            else f"{stored} bytes stored, end of file missing")
    if getattr(data, "hung_up", False):
        note += " (Archive hung up)"
    return note


_OBJ_RE = re.compile(rb"(?<!\d)(\d+)\s+(\d+)\s+obj\b")
_PAGE_TYPE_RE = re.compile(rb"/Type\s*/Page(?![A-Za-z])")


def repair_truncated_pdf(data: bytes) -> Optional[bytes]:
    """Rebuild a readable PDF from a truncated one: keep every complete object, append a new
    page tree over the `/Type /Page` objects that survived (in file order), a catalog and a
    trailer, then let pikepdf (qpdf) reconstruct the cross-reference table and save a clean
    file. Returns None if nothing survives or pikepdf is not installed (it ships with the
    `pdf-ocr` extra, as an ocrmypdf dependency).

    Measured 2026-10-02 on cut Biblioteca captures: a 1 MiB speech keeps 3-4 pages (the
    library's cover sheet, a section title, ~1 page of speech); a 5 MiB message to Congress
    up to 39 pages. Pages whose image lies past the cut render blank and simply OCR to nothing.
    A page tree inside a compressed object stream (/ObjStm) is not reachable this way."""
    try:
        import pikepdf
    except ImportError:
        return None
    if not looks_like_pdf(data):
        return None
    last = bytes(data).rfind(b"endobj")
    if last == -1:
        return None
    body = bytes(data[:last + len(b"endobj")])
    pages: list[tuple[int, int, int]] = []
    max_num = 0
    for m in _OBJ_RE.finditer(body):
        num = int(m.group(1))
        max_num = max(max_num, num)
        end = body.find(b"endobj", m.end())
        head = body[m.end():min(end if end != -1 else len(body), m.end() + 4000)]
        if _PAGE_TYPE_RE.search(head.split(b"stream", 1)[0]):
            pages.append((m.start(), num, int(m.group(2))))
    if not pages:
        return None
    pages.sort()
    kids = b" ".join(b"%d %d R" % (num, gen) for _, num, gen in pages)
    tree, catalog = max_num + 1, max_num + 2
    tail = (b"\n%d 0 obj\n<< /Type /Pages /Kids [ %s ] /Count %d /MediaBox [0 0 612 792] >>\nendobj\n"
            % (tree, kids, len(pages))
            + b"%d 0 obj\n<< /Type /Catalog /Pages %d 0 R >>\nendobj\n" % (catalog, tree)
            + b"trailer\n<< /Root %d 0 R /Size %d >>\n%%%%EOF\n" % (catalog, catalog + 1))
    try:
        with pikepdf.open(io.BytesIO(body + tail)) as doc:
            if len(doc.pages) == 0:
                return None
            for page in doc.pages:          # the old /Parent is past the cut
                page.obj.Parent = doc.Root.Pages
            out = io.BytesIO()
            doc.save(out)
            return out.getvalue()
    except Exception as e:  # a page dict cut mid-way, an object qpdf can't place, ...
        log.info("could not repair a truncated PDF: %s", _describe(e))
        return None


def _drop_last_page(data: bytes) -> Optional[bytes]:
    """The same PDF without its last page — the one most likely to reference an image past the
    cut. None if there is only one page or pikepdf can't do it."""
    try:
        import pikepdf
        with pikepdf.open(io.BytesIO(data)) as doc:
            if len(doc.pages) < 2:
                return None
            del doc.pages[-1]
            out = io.BytesIO()
            doc.save(out)
            return out.getvalue()
    except Exception:
        return None


def _describe(e: BaseException) -> str:
    """An exception as text that is never blank: ocrmypdf's InputFileError() has no message,
    which turned every failure on a cut PDF into a bare 'OCR failed to process a PDF: '."""
    return " ".join(str(e).split()) or type(e).__name__


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


# --- OCR ----------------------------------------------------------------------------------
# A text layer with fewer word characters than this counts as "no text layer" when OCR is on:
# scans often carry a stray page number or a scanner's stamp, and `text.strip()` alone would
# then skip the OCR that the page needs. The OCR text replaces the layer only if it is longer.
OCR_MIN_WORD_CHARS = 50

# Why the most recent pdf_bytes_to_text() call returned no text (None when it found some).
# run.py reads it with take_empty_reason() to write a useful `empty_text (...)` error and to
# keep a run of image-only scans from tripping the circuit breaker (they say nothing about
# being blocked).
_last_empty_reason: Optional[str] = None
# A missing Tesseract / language pack fails every later PDF the same way: warn once per
# distinct reason, then stay quiet (and don't pay for a second, plain ocrmypdf call).
_ocr_unavailable: dict[str, str] = {}
_warned: set[str] = set()


def take_empty_reason() -> Optional[str]:
    """Return (and clear) why the last PDF extraction came back empty."""
    global _last_empty_reason
    reason, _last_empty_reason = _last_empty_reason, None
    return reason


def _warn_once(key: str, msg: str, *args) -> None:
    if key in _warned:
        log.debug(msg, *args)
    else:
        _warned.add(key)
        log.warning(msg, *args)


def _word_chars(text: str) -> int:
    return len(re.findall(r"\w", text or ""))


# A text layer can be present and still unreadable: the Biblioteca da Presidência's PDFs extract
# as raw glyph codes ("(cid:111) (cid:46) ...") or letter-spaced ("M a g a l h ª e s"), while
# Tesseract reads the same pages as clean Portuguese. A layer with mostly-fine text and a few
# glyph codes (Gambia's newsletters: ~1%) is NOT suspicious. Measured 2026-10-02 over the corpus.
_CID_RE = re.compile(r"\(cid:\d+\)")
SUSPICIOUS_CID_SHARE = 0.05
SUSPICIOUS_SINGLE_LETTER_SHARE = 0.40


def _layer_suspicious(text: str) -> bool:
    """Does this text layer look like glyph codes or letter-spaced garbage? (OCR is then tried
    and wins if it reads more real words.)"""
    tokens = (text or "").split()
    if len(tokens) < 50:
        return False
    cid = len(_CID_RE.findall(text))
    single = sum(1 for t in tokens if len(t) == 1 and t.isalpha())
    return (cid / len(tokens) > SUSPICIOUS_CID_SHARE
            or single / len(tokens) > SUSPICIOUS_SINGLE_LETTER_SHARE)


def _real_words(text: str) -> int:
    """Whitespace tokens of 2+ characters with a letter in them, glyph codes removed."""
    return sum(1 for t in _CID_RE.sub(" ", text or "").split()
               if len(t) >= 2 and any(c.isalpha() for c in t))


class OcrUnavailable(Exception):
    """OCR could not run at all (no Tesseract, a missing language pack, a refused version) —
    as opposed to running and finding nothing."""


def _extract_ocr(data: bytes, language: str = "eng") -> str:
    """OCR the text off an image-only PDF via ocrmypdf + Tesseract.

    Opt-in and lazy-imported like the other backends — needs ``pip install
    'leaderspeech[pdf-ocr]'`` AND a system Tesseract binary with the language packs.
    Ghostscript is NOT needed: only ``output_type="none"`` (text sidecar only) or ``"pdf"``
    is requested, never PDF/A, and ocrmypdf ≥16 rasterizes with pypdfium2.
    `language` is a Tesseract spec ('eng', or '+'-joined e.g. 'por+eng').

    First call: sidecar only, with ``rotate_pages`` + ``deskew`` (old typewritten scans are
    often skewed or sideways). If that raises anything but a missing dependency, one plain
    retry. Lets ImportError propagate (no ocrmypdf); raises :class:`OcrUnavailable` when
    Tesseract or a language pack is missing; returns "" when OCR ran and found nothing."""
    import tempfile

    import ocrmypdf  # ImportError -> caller has no OCR backend installed

    if language in _ocr_unavailable:
        raise OcrUnavailable(_ocr_unavailable[language])
    from .ocr import ensure_tessdata_env
    ensure_tessdata_env()   # a window opened before setup_ocr.ps1 still lacks TESSDATA_PREFIX
    try:
        from ocrmypdf.exceptions import MissingDependencyError
    except Exception:  # very old ocrmypdf
        MissingDependencyError = ()  # type: ignore[assignment]

    langs = [x for x in language.replace("+", " ").split() if x] or ["eng"]
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.pdf")
        out = os.path.join(tmp, "out.pdf")
        sidecar = os.path.join(tmp, "out.txt")
        with open(src, "wb") as fh:
            fh.write(data)
        attempts = (
            # sidecar only: no output PDF is written at all. The target must be "-": with
            # os.devnull ("nul" on Windows) ocrmypdf 17 still validates the non-file as a PDF and
            # logs "The generated PDF is INVALID" for every document (measured 2026-09-30).
            ("-", dict(output_type="none", rotate_pages=True, deskew=True)),
            # the plain call that worked before 2026-09-30 (no deskew/rotation)
            (out, dict(output_type="pdf")),
        )
        last_err: Optional[Exception] = None
        for target, extra in attempts:
            try:
                if os.path.exists(sidecar):
                    os.remove(sidecar)
                # force_ocr: rasterize and OCR every page, ignoring a junk text layer.
                rc = ocrmypdf.ocr(src, target, sidecar=sidecar, language=langs, force_ocr=True,
                                  progress_bar=False, **extra)
                # Some failures come back as a non-zero ExitCode rather than an exception;
                # the sidecar is what we want either way.
                if os.path.exists(sidecar):
                    with open(sidecar, encoding="utf-8", errors="replace") as fh:
                        return fh.read()
                last_err = RuntimeError(f"ocrmypdf exit code {rc!r}, no text sidecar")
            except MissingDependencyError as e:  # type: ignore[misc]
                reason = " ".join(str(e).split())[:200] or type(e).__name__
                _ocr_unavailable[language] = reason
                _warn_once("dep:" + language, "OCR unavailable (%s): %s — see docs/ocr_setup.md",
                           language, reason)
                raise OcrUnavailable(reason) from e
            except Exception as e:  # a bad scan / an option this ocrmypdf lacks: try plain
                last_err = e
                log.debug("ocrmypdf attempt %s failed: %s", extra, _describe(e))
        log.warning("OCR failed to process a PDF: %s", _describe(last_err) if last_err else "?")
        return ""


def _any_backend_available() -> bool:
    for mod in ("pdfminer.high_level", "pypdf"):
        try:
            __import__(mod)
            return True
        except Exception:
            continue
    return False


def pdf_bytes_to_text(data: bytes, ocr: bool = False, ocr_language: str = "eng") -> str:
    """Extract text from PDF bytes, trying pdfminer.six then pypdf. Returns "" when the
    PDF has no extractable text (e.g. a scanned image), and raises a clear RuntimeError
    when no PDF library is installed at all.

    When ``ocr=True`` (per recipe ``pdf_ocr``, or a run's ``--ocr``) and the text layer is
    empty or near-empty (< :data:`OCR_MIN_WORD_CHARS` word characters) — an image-only scan —
    OCR it in `ocr_language` (issue #70). OCR needs a separate install
    (``leaderspeech[pdf-ocr]`` + Tesseract, see docs/ocr_setup.md); when it is missing the
    result degrades to the text layer, and :func:`take_empty_reason` says why it was empty.

    A layer that is present but unreadable — glyph codes or letter-spaced text
    (:func:`_layer_suspicious`) — is OCR'd too, and the OCR text wins if it reads more real words.

    A TRUNCATED PDF (no `%%EOF` trailer: an Archive capture that stored only a prefix) is first
    rebuilt over its surviving pages (:func:`repair_truncated_pdf`) and read from that; the caller
    flags the row with :func:`truncation_note`."""
    global _last_empty_reason
    _last_empty_reason = None
    cut = truncation_note(data)
    source = data
    repaired = False
    if cut:
        fixed = repair_truncated_pdf(data)
        if fixed is not None:
            source, repaired = fixed, True
    text = ""
    for extractor in (_extract_pdfminer, _extract_pypdf):
        try:
            got = extractor(source)
        except ImportError:
            continue  # this backend isn't installed; try the next
        if got and got.strip():
            text = got
            break
    suspicious = _layer_suspicious(text)
    # A cut PDF that could not be rebuilt has no page tree: ocrmypdf can't open it either
    # (InputFileError), so don't pay for two doomed calls per document.
    ocr_possible = not (cut and not repaired)
    if ocr and ocr_possible and (_word_chars(text) < OCR_MIN_WORD_CHARS or suspicious):
        reason = None
        try:
            ocr_text = _extract_ocr(source, ocr_language)
            if repaired and not ocr_text.strip():
                trimmed = _drop_last_page(source)     # a page whose image is past the cut
                if trimmed is not None:
                    ocr_text = _extract_ocr(trimmed, ocr_language)
        except ImportError:
            _warn_once("import", "OCR requested but ocrmypdf is not installed — `pip install -e "
                       "\".[pdf,pdf-ocr]\"` and a Tesseract binary (docs/ocr_setup.md).")
            reason = "OCR unavailable: ocrmypdf not installed"
        except OcrUnavailable as e:
            reason = f"OCR unavailable: {e}"
        else:
            better = (_real_words(ocr_text) > _real_words(text) if suspicious
                      else _word_chars(ocr_text) > _word_chars(text))
            if better:
                return ocr_text
            reason = ("OCR found no text on the surviving pages" if cut else "OCR found no text")
        if not text.strip():
            _last_empty_reason = (f"archived document truncated ({cut}); {reason}" if cut
                                  else f"document has no text layer; {reason}")
    elif not text.strip():
        if cut and not repaired:
            _last_empty_reason = (f"archived document truncated ({cut}); no page survives the cut "
                                  f"that could be rebuilt")
        elif cut:
            _last_empty_reason = (f"archived document truncated ({cut}); no text layer on the "
                                  f"surviving pages; OCR off (recipe pdf_ocr / run --ocr)")
        else:
            _last_empty_reason = "document has no text layer; OCR off (recipe pdf_ocr / run --ocr)"
    if text.strip():
        return text
    if not _any_backend_available():
        _last_empty_reason = None
        raise RuntimeError(
            "PDF support needs a PDF library — install with "
            "`pip install 'leaderspeech[pdf]'` (pdfminer.six)."
        )
    return ""  # a backend ran but the PDF yielded no text (e.g. image-only scan)
