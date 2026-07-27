"""Microsoft Word speech-file support (.docx / .doc), the sibling of pdf.py.

Some archives store speeches as Word files rather than PDFs (e.g. Botswana's gov.bw
publishes State-of-the-Nation Addresses and ministerial speeches as .doc/.docx). The
engine's `content_type: pdf` path fetches these as bytes; this module turns them into text:

  * :func:`is_docx_url` / :func:`is_doc_url` — does a URL look like a Word file? (auto-detection)
  * :func:`looks_like_docx` / :func:`looks_like_doc` — do the bytes have the right magic?
  * :func:`docx_bytes_to_text` — extract text from .docx bytes (STDLIB ONLY: a .docx is an
    Open-Packaging zip of XML, so no third-party dependency is needed).
  * :func:`doc_bytes_to_text` — extract text from the legacy binary .doc (OLE) format. Pure
    Python can't do this reliably, so it shells out to an optional `antiword`/`catdoc` binary
    if one is on PATH, and otherwise degrades to "" (like an image-only PDF) — never crashes.
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

DOCX_MAGIC = b"PK\x03\x04"                          # any zip (a .docx is a zip)
DOC_MAGIC = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"     # OLE2 compound file (legacy .doc)
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

_DOCX_URL_RE = re.compile(r"\.docx($|[/?#])", re.IGNORECASE)
# .doc but NOT .docx (the negative lookahead stops .docx matching the .doc rule).
_DOC_URL_RE = re.compile(r"\.doc(?!x)($|[/?#])", re.IGNORECASE)

_DOC_BACKEND_WARNED = False


def is_docx_url(url: str) -> bool:
    return bool(url) and bool(_DOCX_URL_RE.search(urlparse(url).path))


def is_doc_url(url: str) -> bool:
    return bool(url) and bool(_DOC_URL_RE.search(urlparse(url).path))


def looks_like_docx(data) -> bool:
    """True if `data` is a zip whose contents look like a Word document (has
    word/document.xml) — distinguishes a .docx from a plain zip / .xlsx / .pptx."""
    if not isinstance(data, (bytes, bytearray)):
        return False
    b = bytes(data)
    if not b.startswith(DOCX_MAGIC):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            return "word/document.xml" in z.namelist()
    except Exception:
        return False


def looks_like_doc(data) -> bool:
    """True if `data` begins with the OLE2 compound-file magic (a legacy binary .doc).
    NB .xls/.ppt share this magic — pair with the URL/mimetype to be sure it's a Word doc."""
    return isinstance(data, (bytes, bytearray)) and bytes(data[:8]).startswith(DOC_MAGIC)


def _paragraph_text(para: ET.Element) -> str:
    """Concatenate the runs of one <w:p> paragraph, honouring tabs and line breaks."""
    out = []
    for node in para.iter():
        tag = node.tag
        if tag == _W_NS + "t":
            out.append(node.text or "")
        elif tag == _W_NS + "tab":
            out.append("\t")
        elif tag in (_W_NS + "br", _W_NS + "cr"):
            out.append("\n")
    return "".join(out)


def docx_bytes_to_text(data) -> str:
    """Extract the visible text from .docx bytes using only the stdlib (zipfile + xml).
    One line per <w:p> paragraph; returns "" on any parse failure (never raises)."""
    try:
        with zipfile.ZipFile(io.BytesIO(bytes(data))) as z:
            xml = z.read("word/document.xml")
        root = ET.fromstring(xml)
        body = root.find(_W_NS + "body")
        paras = (body if body is not None else root).iter(_W_NS + "p")
        return "\n".join(_paragraph_text(p) for p in paras)
    except Exception as e:  # a malformed/encrypted docx shouldn't crash the run
        log.warning("failed to parse a .docx: %s", e)
        return ""


def doc_bytes_to_text(data) -> str:
    """Extract text from a legacy binary .doc via an optional `antiword`/`catdoc` binary on
    PATH. Returns "" (with a one-time warning) when neither is installed — the row then fails
    cleanly as empty text, exactly like an image-only PDF, rather than crashing the run."""
    global _DOC_BACKEND_WARNED
    tool = shutil.which("antiword") or shutil.which("catdoc")
    if not tool:
        if not _DOC_BACKEND_WARNED:
            log.warning("legacy .doc files can't be extracted without a converter — install "
                        "`antiword` or `catdoc` on PATH (or convert the .doc to .docx). Skipping.")
            _DOC_BACKEND_WARNED = True
        return ""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as fh:
            fh.write(bytes(data))
            tmp = fh.name
        proc = subprocess.run([tool, tmp], capture_output=True, timeout=120)
        return proc.stdout.decode("utf-8", "replace")
    except Exception as e:
        log.warning("%s failed to convert a .doc: %s", os.path.basename(tool), e)
        return ""
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
