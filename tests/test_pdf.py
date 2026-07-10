"""PDF speech-page support: URL/byte detection, text extraction, and the URL-driven
record builder that stands in for selectors when there is no DOM."""

import pytest

from leaderspeech.text_scraper import extract, pdf
from leaderspeech.text_scraper.recipe import ContentType, FieldSpec, Recipe, load_recipe


def make_minimal_pdf(body_text: str) -> bytes:
    """A tiny but valid one-page PDF containing `body_text` — enough for pdfminer to
    extract the text, without pulling in a PDF-authoring dependency."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = b"BT /F1 24 Tf 72 720 Td (" + body_text.encode("latin-1") + b") Tj ET"
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objs) + 1
    out += b"xref\n0 " + str(n).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R >>\n"
            b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF")
    return bytes(out)


# --- is_pdf_url ---------------------------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://x/discursos/2003/18-06-2003-discurso.pdf", True),
    ("https://x/a/foo.pdf/view", True),                          # .pdf mid-path (Plone view)
    ("https://x/a/foo.pdf/@@download/file/bar.pdf", True),       # download handler
    ("https://x/a/report.PDF", True),                            # case-insensitive
    ("https://x/a/2004/01-09-2004-discurso-de-ativos", False),  # PDF served w/o .pdf hint
    ("https://x/discursos/2003", False),
    ("", False),
])
def test_is_pdf_url(url, expected):
    assert pdf.is_pdf_url(url) is expected


def test_looks_like_pdf():
    assert pdf.looks_like_pdf(b"%PDF-1.7\n...") is True
    assert pdf.looks_like_pdf(b"<html>not a pdf</html>") is False
    assert pdf.looks_like_pdf("a string") is False


def test_pdf_bytes_to_text_roundtrip():
    pytest.importorskip("pdfminer")
    data = make_minimal_pdf("Discurso de prueba del presidente")
    assert "Discurso de prueba del presidente" in pdf.pdf_bytes_to_text(data)


def test_pdf_bytes_to_text_empty_when_no_text():
    pytest.importorskip("pdfminer")
    # A structurally-valid PDF with no text content -> empty string, not an error.
    assert pdf.pdf_bytes_to_text(make_minimal_pdf("")) == ""


def test_pdf_bytes_to_text_raises_without_backend(monkeypatch):
    """If no PDF library is importable, the error is explicit (install hint) rather than a
    silent empty-text failure."""
    monkeypatch.setattr(pdf, "_extract_pdfminer", lambda d: (_ for _ in ()).throw(ImportError()))
    monkeypatch.setattr(pdf, "_extract_pypdf", lambda d: (_ for _ in ()).throw(ImportError()))
    monkeypatch.setattr(pdf, "_any_backend_available", lambda: False)
    with pytest.raises(RuntimeError, match="PDF"):
        pdf.pdf_bytes_to_text(b"%PDF-1.4")


# --- match_url / date_from_url (the URL-as-selector helpers) -------------------------

def test_match_url_group_and_whole():
    spec = FieldSpec(url_regex=r"file/([^/]+)\.pdf$")
    assert extract.match_url(spec, "https://x/a.pdf/@@download/file/My%20Title.pdf") == "My%20Title"
    whole = FieldSpec(url_regex=r"\d{4}")
    assert extract.match_url(whole, "https://x/2003/foo") == "2003"
    assert extract.match_url(FieldSpec(), "https://x/foo") is None   # no url_regex


def test_date_from_url_named_groups_are_unambiguous():
    # /YYYY/DD-MM-... : day 18, month 06 must NOT be read as month 18.
    spec = FieldSpec(url_regex=r"/(?P<year>\d{4})/(?P<day>\d{2})-(?P<month>\d{2})-")
    url = "https://x/discursos/1o-mandato/2003/18-06-2003-discurso.pdf"
    assert extract.date_from_url(spec, url) == "2003-06-18"


def test_date_from_url_falls_back_to_parse_date():
    spec = FieldSpec(url_regex=r"(\d{2}-\d{2}-\d{4})")
    assert extract.date_from_url(spec, "https://x/a/18-06-2003-foo.pdf", ["pt"]) == "2003-06-18"


# --- extract_pdf_record -------------------------------------------------------------

def _pdf_recipe(**over) -> Recipe:
    base = dict(
        source_id="t", country="Brazil", source_language="Portuguese",
        start_urls=["https://x/discursos"], content_type="pdf",
        listing={"link_pattern": r"\.pdf$"},
        title={}, text={},
        date={"url_regex": r"/(?P<year>\d{4})/(?P<day>\d{2})-(?P<month>\d{2})-"},
        speaker_default="Lula da Silva", position="president",
    )
    base.update(over)
    return Recipe(**base)


def test_extract_pdf_record_pulls_body_date_and_speaker(monkeypatch):
    monkeypatch.setattr(pdf, "pdf_bytes_to_text",
                        lambda data: "Primeira linha do discurso.\nSegundo paragrafo.")
    recipe = _pdf_recipe()
    url = "https://x/discursos/1o-mandato/2003/18-06-2003-discurso-mercosul.pdf"
    rec = extract.extract_pdf_record(b"%PDF-1.4 fake", url, recipe)

    assert rec["text"].startswith("Primeira linha do discurso.")
    assert rec["date"] == "2003-06-18"                 # DD-MM-YYYY from the URL, unambiguous
    assert rec["speaker"] == "Lula da Silva"           # speaker_default
    assert rec["title"] == "Primeira linha do discurso."   # first PDF line (no title url_regex)
    assert rec["source"] == url


def test_extract_pdf_record_title_from_url_regex(monkeypatch):
    monkeypatch.setattr(pdf, "pdf_bytes_to_text", lambda data: "corpo")
    recipe = _pdf_recipe(title={"url_regex": r"/(\d{2}-\d{2}-\d{4}-[^/]+?)\.pdf"})
    url = "https://x/discursos/1o-mandato/2003/18-06-2003-discurso-mercosul.pdf"
    rec = extract.extract_pdf_record(b"%PDF-1.4 x", url, recipe)
    assert rec["title"] == "18-06-2003-discurso-mercosul"


# --- recipe validation --------------------------------------------------------------

def test_pdf_recipe_needs_no_html_selectors(tmp_path):
    """A content_type: pdf recipe validates with empty title/text/date selectors — the
    body comes from the PDF, title/date from url_regex (or nothing)."""
    p = tmp_path / "r.yml"
    p.write_text(
        "source_id: t\ncountry: Brazil\nstart_urls: ['https://x/d']\n"
        "content_type: pdf\nlisting: { link_pattern: '\\.pdf$' }\n"
        "title: {}\ntext: {}\ndate: {}\n",
        encoding="utf-8",
    )
    r = load_recipe(str(p))
    assert r.content_type == ContentType.pdf


def test_html_recipe_still_requires_a_selector_or_url_regex():
    with pytest.raises(ValueError, match="selector or a url_regex"):
        Recipe(
            source_id="t", country="Brazil", start_urls=["https://x/d"],
            listing={"link_selector": "a"},
            title={"selectors": ["h1"]}, text={}, date={"selectors": ["time"]},
        )


def test_html_recipe_url_regex_satisfies_field():
    r = Recipe(
        source_id="t", country="Brazil", start_urls=["https://x/d"],
        listing={"link_selector": "a"},
        title={"selectors": ["h1"]}, text={"selectors": ["article"]},
        date={"url_regex": r"/(\d{4})/"},   # date via URL instead of a selector
    )
    assert r.date.url_regex == r"/(\d{4})/"
