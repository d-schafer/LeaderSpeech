"""Tests for Word (.docx/.doc) speech-file support (msword.py) + the document dispatcher."""
import io
import types
import zipfile

from leaderspeech.text_scraper import extract, msword, pdf

_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _make_docx(paragraphs, extra_files=None) -> bytes:
    """A minimal valid .docx (a zip with word/document.xml), stdlib only."""
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    document = (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<w:document xmlns:w="{_NS}"><w:body>{body}</w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", document)
        for name, content in (extra_files or {}).items():
            z.writestr(name, content)
    return buf.getvalue()


def test_looks_like_docx_true_for_word_zip_false_otherwise():
    assert msword.looks_like_docx(_make_docx(["hi"])) is True
    # a plain zip without word/document.xml is not a docx
    plainzip = io.BytesIO()
    with zipfile.ZipFile(plainzip, "w") as z:
        z.writestr("hello.txt", "x")
    assert msword.looks_like_docx(plainzip.getvalue()) is False
    assert msword.looks_like_docx(b"%PDF-1.4 not a zip") is False
    assert msword.looks_like_docx("not bytes") is False


def test_docx_bytes_to_text_extracts_paragraphs():
    data = _make_docx(["Speech by the President", "Second paragraph."])
    assert msword.docx_bytes_to_text(data) == "Speech by the President\nSecond paragraph."


def test_docx_bytes_to_text_bad_zip_returns_empty():
    assert msword.docx_bytes_to_text(b"PK\x03\x04 corrupt") == ""


def test_looks_like_doc_ole_magic():
    assert msword.looks_like_doc(msword.DOC_MAGIC + b"rest of an OLE file") is True
    assert msword.looks_like_doc(b"%PDF-1.4") is False


def test_doc_bytes_to_text_degrades_without_backend(monkeypatch):
    # no antiword/catdoc on PATH -> "" (never raises), and it warns once
    monkeypatch.setattr(msword.shutil, "which", lambda name: None)
    msword._DOC_BACKEND_WARNED = False
    assert msword.doc_bytes_to_text(msword.DOC_MAGIC + b"whatever") == ""


def test_find_doc_tool_falls_back_to_git_for_windows(monkeypatch, tmp_path):
    # antiword is not on PATH (a PowerShell session), but Git for Windows bundles it
    root = tmp_path / "Git"
    (root / "cmd").mkdir(parents=True)
    (root / "mingw64" / "bin").mkdir(parents=True)
    (root / "cmd" / "git.exe").write_bytes(b"")
    bundled = root / "mingw64" / "bin" / "antiword.exe"
    bundled.write_bytes(b"")
    paths = {"git": str(root / "cmd" / "git.exe")}
    monkeypatch.setattr(msword.shutil, "which", lambda name: paths.get(name))
    assert msword._find_doc_tool() == str(bundled)


def test_find_doc_tool_none_without_path_or_git(monkeypatch):
    monkeypatch.setattr(msword.shutil, "which", lambda name: None)
    assert msword._find_doc_tool() is None


def test_doc_bytes_to_text_asks_antiword_for_utf8(monkeypatch):
    # Without `-m UTF-8.txt` antiword emits ISO-8859-1 and every accent decodes to U+FFFD.
    calls = []

    def fake_run(args, capture_output, timeout):
        calls.append(args)
        return types.SimpleNamespace(stdout="Discurso do presidente da República".encode("utf-8"))

    monkeypatch.setattr(msword, "_find_doc_tool", lambda: "/usr/bin/antiword")
    monkeypatch.setattr(msword.subprocess, "run", fake_run)
    assert msword.doc_bytes_to_text(msword.DOC_MAGIC + b"x") == "Discurso do presidente da República"
    assert calls[0][1:3] == ["-m", "UTF-8.txt"]


def test_doc_bytes_to_text_catdoc_utf8_and_latin1_fallback(monkeypatch):
    calls = []

    def fake_run(args, capture_output, timeout):
        calls.append(args)
        # first call (UTF-8 requested) yields nothing -> fallback call, default mapping
        out = b"" if len(calls) == 1 else "República".encode("latin-1")
        return types.SimpleNamespace(stdout=out)

    monkeypatch.setattr(msword, "_find_doc_tool", lambda: "/usr/bin/catdoc")
    monkeypatch.setattr(msword.subprocess, "run", fake_run)
    assert msword.doc_bytes_to_text(msword.DOC_MAGIC + b"x") == "República"
    assert calls[0][1:3] == ["-d", "utf-8"]
    assert len(calls[1]) == 2          # the fallback drops the mapping flag


def test_doc_url_vs_docx_url():
    assert msword.is_docx_url("http://x/gov/Speech.docx") is True
    assert msword.is_doc_url("http://x/gov/Speech.docx") is False   # .docx is not .doc
    assert msword.is_doc_url("http://x/gov/2013 Budget Speech.doc") is True
    assert msword.is_docx_url("http://x/gov/report.pdf") is False


def test_looks_like_document_covers_pdf_docx_doc():
    assert extract.looks_like_document(b"%PDF-1.5 ...") is True
    assert extract.looks_like_document(_make_docx(["x"])) is True
    assert extract.looks_like_document(msword.DOC_MAGIC + b"...") is True
    assert extract.looks_like_document(b"<html>plain</html>") is False


def test_document_to_text_dispatches_by_type(monkeypatch):
    rec = types.SimpleNamespace(pdf_ocr=False, pdf_ocr_language="eng")
    # docx -> stdlib docx extractor
    assert extract.document_to_text(_make_docx(["Hello docx"]), rec) == "Hello docx"
    # pdf bytes -> pdf backend (monkeypatched)
    monkeypatch.setattr(pdf, "pdf_bytes_to_text", lambda data, ocr=False, ocr_language="eng": "PDF-TEXT")
    assert extract.document_to_text(b"%PDF-1.4 xxxx", rec) == "PDF-TEXT"
    # legacy .doc with no converter -> "" (graceful)
    monkeypatch.setattr(msword.shutil, "which", lambda name: None)
    msword._DOC_BACKEND_WARNED = True
    assert extract.document_to_text(msword.DOC_MAGIC + b"legacy", rec) == ""
