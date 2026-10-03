"""PDF speech-page support: URL/byte detection, text extraction, and the URL-driven
record builder that stands in for selectors when there is no DOM."""

import io

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


def test_pdf_ocr_fallback_used_only_when_enabled(monkeypatch):
    """An image-only PDF (text backends yield "") is OCR'd only when ocr=True (issue #70).
    OCR itself is mocked here — a real run needs the pdf-ocr extra + a system Tesseract."""
    seen = {}
    monkeypatch.setattr(pdf, "_extract_pdfminer", lambda d: "")
    monkeypatch.setattr(pdf, "_extract_pypdf", lambda d: "")

    def fake_ocr(d, language="eng"):
        seen["lang"] = language
        return "OCR RECOVERED TEXT"
    monkeypatch.setattr(pdf, "_extract_ocr", fake_ocr)
    scan = b"%PDF-1.4 scan\n%%EOF"           # a COMPLETE file (a cut one is repaired first)
    assert pdf.pdf_bytes_to_text(scan, ocr=False) == ""                      # not requested
    assert pdf.pdf_bytes_to_text(scan, ocr=True, ocr_language="fas+pus+eng") == "OCR RECOVERED TEXT"
    assert seen["lang"] == "fas+pus+eng"                                     # language forwarded


def test_pdf_ocr_missing_backend_degrades_to_empty(monkeypatch):
    """ocr=True but the OCR lib isn't installed -> behave exactly like a 0-char extract."""
    monkeypatch.setattr(pdf, "_extract_pdfminer", lambda d: "")
    monkeypatch.setattr(pdf, "_extract_pypdf", lambda d: "")
    monkeypatch.setattr(pdf, "_extract_ocr", lambda d, language="eng": (_ for _ in ()).throw(ImportError()))
    assert pdf.pdf_bytes_to_text(b"%PDF-1.4 scan", ocr=True) == ""


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


def test_date_from_url_widens_a_two_digit_year():
    """DDMMYY filenames are the vintage-government-site norm — presidentofindia.nic.in
    dates ~1,000 speeches as /sp010108.html (1 Jan 2008). A 2-digit year group is widened
    with the POSIX pivot instead of being rejected by the <1900 sanity check."""
    spec = FieldSpec(url_regex=r"/sp(?P<day>\d{2})(?P<month>\d{2})(?P<year>\d{2})")
    assert extract.date_from_url(spec, "https://x/sp010108.html") == "2008-01-01"
    assert extract.date_from_url(spec, "https://x/sp311214-2.html") == "2014-12-31"
    # 69..99 are last century; 00..68 this one.
    assert extract.date_from_url(spec, "https://x/sp150385.html") == "1985-03-15"
    # A 4-digit year is untouched.
    four = FieldSpec(url_regex=r"/(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})")
    assert extract.date_from_url(four, "https://x/2008-01-01/s") == "2008-01-01"


def test_named_date_groups_that_dont_form_a_date_return_nothing():
    """When a recipe asks for assembled year/month/day, an impossible combination is a MISS.
    It must not fall back to parse_date(group(1)) — that hands dateparser a bare "99", which
    it happily completes with TODAY's month and day. A blank date beats a wrong one."""
    spec = FieldSpec(url_regex=r"/sp(?P<day>\d{2})(?P<month>\d{2})(?P<year>\d{2})")
    assert extract.date_from_url(spec, "https://x/sp993108.html") is None


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
                        lambda data, ocr=False, ocr_language="eng": "Primeira linha do discurso.\nSegundo paragrafo.")
    recipe = _pdf_recipe()
    url = "https://x/discursos/1o-mandato/2003/18-06-2003-discurso-mercosul.pdf"
    rec = extract.extract_pdf_record(b"%PDF-1.4 fake", url, recipe)

    assert rec["text"].startswith("Primeira linha do discurso.")
    assert rec["date"] == "2003-06-18"                 # DD-MM-YYYY from the URL, unambiguous
    assert rec["speaker"] == "Lula da Silva"           # speaker_default
    assert rec["title"] == "Primeira linha do discurso."   # first PDF line (no title url_regex)
    assert rec["source"] == url


def test_extract_pdf_record_title_from_url_regex(monkeypatch):
    monkeypatch.setattr(pdf, "pdf_bytes_to_text", lambda data, ocr=False, ocr_language="eng": "corpo")
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


# --- truncated PDFs: an Archive capture that holds only a prefix of the file ------------------

def make_tail_tree_pdf(page_texts: list[str]) -> bytes:
    """A multi-page PDF that writes its page objects FIRST and the page tree + catalog LAST, as
    the Biblioteca da Presidência's do — so cutting it mid-file keeps whole pages but loses the
    tree, exactly the shape the Archive stores at 1 MiB. The font comes first: a font object
    past the cut leaves pdfminer without glyph widths, and it then reads one letter per line —
    the letter-spaced layer `_layer_suspicious` sends to OCR."""
    n_pages = len(page_texts)
    font = 1
    pages_obj, catalog = 2 * n_pages + 2, 2 * n_pages + 3
    objs: dict[int, bytes] = {}
    for i, text in enumerate(page_texts):
        page, content = 2 * i + 2, 2 * i + 3
        objs[page] = (b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                      b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_obj, content, font))
        stream = b"BT /F1 18 Tf 72 720 Td (" + text.encode("latin-1") + b") Tj ET"
        objs[content] = (b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
                         + b"\nendstream")
    objs[font] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    kids = b" ".join(b"%d 0 R" % (2 * i + 2) for i in range(n_pages))
    objs[pages_obj] = b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % n_pages
    objs[catalog] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += str(num).encode() + b" 0 obj\n" + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    size = catalog + 1
    out += b"xref\n0 " + str(size).encode() + b"\n0000000000 65535 f \n"
    for num in range(1, size):
        out += ("%010d 00000 n \n" % offsets[num]).encode()
    out += (b"trailer\n<< /Size " + str(size).encode() + b" /Root %d 0 R >>\n" % catalog
            + b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF")
    return bytes(out)


def _cut_after_page(data: bytes, n: int) -> bytes:
    """Cut `data` a few bytes into the object after page n's content stream (a mid-object cut)."""
    marker = b"%d 0 obj" % (2 * n + 2)
    return data[:data.index(marker) + len(marker) + 5]


def test_truncation_note():
    full = make_tail_tree_pdf(["one", "two"])
    assert pdf.truncation_note(full) == ""                         # complete: %%EOF trailer
    assert pdf.truncation_note(b"<html>not a pdf</html>") == ""    # only PDFs are judged
    cut = full[:200]
    assert pdf.truncation_note(cut) == "200 bytes stored, end of file missing"
    from leaderspeech.text_scraper.wayback import SnapshotBytes
    assert pdf.truncation_note(SnapshotBytes(cut, real_size=1904015)) == "200 of 1904015 bytes stored"
    assert (pdf.truncation_note(SnapshotBytes(cut, real_size=23680765, hung_up=True))
            == "200 of 23680765 bytes stored (Archive hung up)")


def test_repair_recovers_the_pages_that_survive_the_cut():
    pikepdf = pytest.importorskip("pikepdf")
    full = make_tail_tree_pdf(["Primeira pagina do discurso", "Segunda pagina do discurso",
                               "Terceira pagina perdida"])
    cut = _cut_after_page(full, 2)                 # page 3's object is cut mid-way
    with pytest.raises(Exception):
        pikepdf.open(io.BytesIO(cut)).pages[0]     # unreadable as stored ...
    fixed = pdf.repair_truncated_pdf(cut)
    assert fixed is not None
    with pikepdf.open(io.BytesIO(fixed)) as doc:   # ... readable after the repair
        assert len(doc.pages) == 2


def test_truncated_pdf_text_comes_from_the_surviving_pages():
    pytest.importorskip("pikepdf")
    pytest.importorskip("pdfminer")
    full = make_tail_tree_pdf(["Primeira pagina do discurso", "Segunda pagina do discurso",
                               "Terceira pagina perdida"])
    text = pdf.pdf_bytes_to_text(_cut_after_page(full, 2))
    assert "Primeira pagina" in text and "Segunda pagina" in text
    assert "Terceira" not in text
    assert pdf.take_empty_reason() is None


def test_repair_gives_up_when_no_page_survives():
    assert pdf.repair_truncated_pdf(b"%PDF-1.4\n1 0 obj\n<< /Length 9 >>\nstream\nxxxxx") is None
    assert pdf.repair_truncated_pdf(b"<html></html>") is None


def test_a_cut_pdf_that_cannot_be_rebuilt_skips_ocr_and_says_why(monkeypatch):
    """No page tree survives -> ocrmypdf can't open it either (InputFileError, blank message):
    don't pay for the doomed calls, and say it was the cut, not a missing text layer."""
    monkeypatch.setattr(pdf, "_extract_pdfminer", lambda d: "")
    monkeypatch.setattr(pdf, "_extract_pypdf", lambda d: "")
    monkeypatch.setattr(pdf, "_extract_ocr", lambda d, language="eng": pytest.fail("OCR on a cut file"))
    assert pdf.pdf_bytes_to_text(b"%PDF-1.4 cut mid-way", ocr=True) == ""
    reason = pdf.take_empty_reason()
    assert reason.startswith("archived document truncated (20 bytes stored, end of file missing)")


def test_ocr_runs_on_the_repaired_file(monkeypatch):
    seen = {}
    monkeypatch.setattr(pdf, "repair_truncated_pdf", lambda d: b"%PDF-1.4 repaired\n%%EOF")
    monkeypatch.setattr(pdf, "_extract_pdfminer", lambda d: "")
    monkeypatch.setattr(pdf, "_extract_pypdf", lambda d: "")

    def fake_ocr(d, language="eng"):
        seen["data"] = d
        return "Discurso reconhecido na pagina que sobreviveu"
    monkeypatch.setattr(pdf, "_extract_ocr", fake_ocr)
    assert pdf.pdf_bytes_to_text(b"%PDF-1.4 cut", ocr=True).startswith("Discurso")
    assert seen["data"] == b"%PDF-1.4 repaired\n%%EOF"


# --- unreadable text layers (glyph codes, letter-spacing) --------------------------------------

LETTER_SPACED = " ".join("M a g a l h a e s P i n t o s e l e v a n t a r a m".split() * 12)
CID_CODES = " ".join("(cid:%d)" % (40 + i % 60) for i in range(300))


@pytest.mark.parametrize("layer", [LETTER_SPACED, CID_CODES])
def test_a_garbage_layer_is_ocred_and_ocr_wins(monkeypatch, layer):
    monkeypatch.setattr(pdf, "_extract_pdfminer", lambda d: layer)
    monkeypatch.setattr(pdf, "_extract_ocr",
                        lambda d, language="eng": "Magalhaes Pinto se levantaram os mineiros em defesa")
    out = pdf.pdf_bytes_to_text(b"%PDF-1.4 scan\n%%EOF", ocr=True)
    assert out.startswith("Magalhaes Pinto")


def test_a_layer_with_a_few_glyph_codes_is_left_alone(monkeypatch):
    """Gambia's newsletters: ~1% (cid:) codes in otherwise good text — never OCR'd."""
    layer = " ".join(["the government will transform livelihoods across the country"] * 40) + " (cid:32)"
    monkeypatch.setattr(pdf, "_extract_pdfminer", lambda d: layer)
    monkeypatch.setattr(pdf, "_extract_ocr", lambda d, language="eng": pytest.fail("OCR on a good layer"))
    assert pdf.pdf_bytes_to_text(b"%PDF-1.4\n%%EOF", ocr=True) == layer


def test_garbage_layer_is_kept_when_ocr_reads_less(monkeypatch):
    monkeypatch.setattr(pdf, "_extract_pdfminer", lambda d: LETTER_SPACED + " real words here and there")
    monkeypatch.setattr(pdf, "_extract_ocr", lambda d, language="eng": "")
    assert pdf.pdf_bytes_to_text(b"%PDF-1.4\n%%EOF", ocr=True).startswith("M a g")


def test_describe_never_blank():
    class InputFileError(Exception):
        pass
    assert pdf._describe(InputFileError()) == "InputFileError"
    assert pdf._describe(ValueError("bad\n  thing")) == "bad thing"
