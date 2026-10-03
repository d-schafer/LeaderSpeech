"""OCR plumbing (2026-09-30): language derivation, the near-empty trigger, why-empty reasons,
the ocrmypdf call shape and its fallbacks, the run-level --ocr override, and scans not
tripping the circuit breaker. ocrmypdf itself is faked — a real OCR run needs Tesseract
(`python -m leaderspeech.text_scraper.ocr_check` checks a machine)."""

import sys
import types

import pytest

from leaderspeech.text_scraper import ocr, pdf, run


@pytest.fixture(autouse=True)
def _fresh_ocr_state():
    pdf._ocr_unavailable.clear()
    pdf._warned.clear()
    pdf.take_empty_reason()
    yield
    pdf._ocr_unavailable.clear()
    pdf.take_empty_reason()


# --- language derivation -------------------------------------------------------------------

@pytest.mark.parametrize("lang,explicit,expected", [
    ("Portuguese", None, "por+eng"),
    ("Spanish", None, "spa+eng"),
    ("English", None, "eng"),
    ("Dari", None, "fas+eng"),
    ("Serbian", None, "srp+srp_latn+eng"),
    ("Somali", None, "eng"),                 # no Tesseract pack
    ("Klingon", None, "eng"),                # unknown -> eng
    ("Dari", "fas+pus+eng", "fas+pus+eng"),  # an explicit spec always wins
])
def test_ocr_language_for(lang, explicit, expected):
    rec = types.SimpleNamespace(source_language=lang, pdf_ocr_language=explicit)
    assert ocr.ocr_language_for(rec) == expected


def test_ocr_language_for_tolerates_objects_without_the_fields():
    # test_msword passes a bare namespace with only pdf_ocr / pdf_ocr_language
    assert ocr.ocr_language_for(types.SimpleNamespace(pdf_ocr=False, pdf_ocr_language="eng")) == "eng"
    assert ocr.ocr_language_for(types.SimpleNamespace()) == "eng"


def test_needed_codes_reads_recipes(tmp_path):
    (tmp_path / "a.yml").write_text("source_language: Portuguese\ncontent_type: pdf\n", encoding="utf-8")
    (tmp_path / "b.yml").write_text("source_language: Amharic\n", encoding="utf-8")
    (tmp_path / "c.yml").write_text("source_language: Dari\npdf_ocr: true\npdf_ocr_language: fas+pus\n",
                                    encoding="utf-8")
    (tmp_path / "broken.yml").write_text("source_language: [unclosed\n", encoding="utf-8")
    assert ocr.needed_codes(tmp_path) == ["amh", "eng", "fas", "osd", "por", "pus"]
    assert ocr.needed_codes(tmp_path, documents_only=True) == ["eng", "fas", "osd", "por", "pus"]


def test_missing_codes():
    assert ocr.missing_codes("por+eng", ["eng", "spa"]) == ["por"]


def test_stale_window_still_finds_the_user_tessdata(tmp_path, monkeypatch):
    """A process started before setup_ocr.ps1 has no TESSDATA_PREFIX; the engine must find the
    per-user packs anyway (registry value first, else the default folder) — or every non-English
    scan fails as 'no language data' (2026-09-30)."""
    packs = tmp_path / "tessdata"
    packs.mkdir()
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setattr(ocr, "_user_env_tessdata", lambda: None)
    monkeypatch.setattr(ocr, "DEFAULT_TESSDATA", packs)
    assert ocr.ensure_tessdata_env() is None                  # empty folder: leave Tesseract alone
    (packs / "eng.traineddata").write_bytes(b"x")
    assert ocr.ensure_tessdata_env() == str(packs)
    import os
    assert os.environ["TESSDATA_PREFIX"] == str(packs)
    monkeypatch.setenv("TESSDATA_PREFIX", "C:/explicit")       # an explicit setting always wins
    assert ocr.ensure_tessdata_env() == "C:/explicit"


# --- pdf_bytes_to_text: trigger + reasons ---------------------------------------------------

def _layer(monkeypatch, text):
    monkeypatch.setattr(pdf, "_extract_pdfminer", lambda d: text)
    monkeypatch.setattr(pdf, "_extract_pypdf", lambda d: "")


def test_near_empty_text_layer_is_ocred(monkeypatch):
    """A scan carrying only a page number in its text layer is still a scan."""
    _layer(monkeypatch, "  12 \n")
    monkeypatch.setattr(pdf, "_extract_ocr", lambda d, language="eng": "Mensagem ao Congresso Nacional")
    assert pdf.pdf_bytes_to_text(b"%PDF", ocr=True) == "Mensagem ao Congresso Nacional"
    # but never when OCR is off — the page number is what the layer has
    assert pdf.pdf_bytes_to_text(b"%PDF", ocr=False).strip() == "12"


def test_a_real_text_layer_is_never_ocred(monkeypatch):
    _layer(monkeypatch, "Discurso do Presidente da República na cerimônia de posse " * 3)
    monkeypatch.setattr(pdf, "_extract_ocr",
                        lambda d, language="eng": pytest.fail("OCR must not run on a real text layer"))
    assert "Discurso" in pdf.pdf_bytes_to_text(b"%PDF", ocr=True)
    assert pdf.take_empty_reason() is None


def test_shorter_ocr_text_does_not_replace_the_layer(monkeypatch):
    _layer(monkeypatch, "Fala do Presidente 1907")
    monkeypatch.setattr(pdf, "_extract_ocr", lambda d, language="eng": "x")
    assert pdf.pdf_bytes_to_text(b"%PDF", ocr=True) == "Fala do Presidente 1907"


@pytest.mark.parametrize("ocr_on,ocr_impl,expect", [
    (False, None, "OCR off"),
    (True, lambda d, language="eng": (_ for _ in ()).throw(ImportError()), "ocrmypdf not installed"),
    (True, lambda d, language="eng": (_ for _ in ()).throw(pdf.OcrUnavailable("no tesseract")),
     "OCR unavailable: no tesseract"),
    (True, lambda d, language="eng": "", "OCR found no text"),
])
def test_empty_result_records_why(monkeypatch, ocr_on, ocr_impl, expect):
    _layer(monkeypatch, "")
    if ocr_impl:
        monkeypatch.setattr(pdf, "_extract_ocr", ocr_impl)
    assert pdf.pdf_bytes_to_text(b"%PDF", ocr=ocr_on) == ""
    reason = pdf.take_empty_reason()
    assert reason.startswith("document has no text layer") and expect in reason
    assert pdf.take_empty_reason() is None          # taking it clears it


# --- _extract_ocr: the ocrmypdf call ----------------------------------------------------------

class _MissingDependencyError(Exception):
    pass


def _fake_ocrmypdf(monkeypatch, behaviour):
    """Install a fake `ocrmypdf` whose ocr() records its calls and runs `behaviour`."""
    calls = []

    def ocr_fn(src, target, sidecar=None, **kw):
        calls.append((target, kw))
        return behaviour(len(calls), sidecar, kw)

    mod = types.ModuleType("ocrmypdf")
    mod.ocr = ocr_fn
    exc = types.ModuleType("ocrmypdf.exceptions")
    exc.MissingDependencyError = _MissingDependencyError
    monkeypatch.setitem(sys.modules, "ocrmypdf", mod)
    monkeypatch.setitem(sys.modules, "ocrmypdf.exceptions", exc)
    return calls


def _write(sidecar, text):
    with open(sidecar, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


def test_ocr_call_is_sidecar_only_with_rotation_and_deskew(monkeypatch):
    calls = _fake_ocrmypdf(monkeypatch, lambda n, side, kw: _write(side, "texto reconhecido"))
    assert pdf._extract_ocr(b"%PDF", "por+eng") == "texto reconhecido"
    target, kw = calls[0]
    assert target == "-"                                   # never os.devnull (see pdf.py)
    assert kw["output_type"] == "none" and kw["rotate_pages"] and kw["deskew"]
    assert kw["language"] == ["por", "eng"] and kw["force_ocr"] is True
    assert "pdfa" not in str(kw.get("output_type"))        # no PDF/A -> no Ghostscript


def test_ocr_falls_back_to_a_plain_call(monkeypatch):
    def behaviour(n, side, kw):
        if n == 1:
            raise ValueError("deskew not supported by this ocrmypdf")
        return _write(side, "plain call text")
    calls = _fake_ocrmypdf(monkeypatch, behaviour)
    assert pdf._extract_ocr(b"%PDF", "eng") == "plain call text"
    assert calls[1][1]["output_type"] == "pdf" and "deskew" not in calls[1][1]


def test_ocr_nonzero_exit_without_sidecar_tries_the_plain_call(monkeypatch):
    calls = _fake_ocrmypdf(monkeypatch, lambda n, side, kw: 4 if n == 1 else _write(side, "ok"))
    assert pdf._extract_ocr(b"%PDF", "eng") == "ok" and len(calls) == 2


def test_missing_dependency_is_unavailable_and_cached(monkeypatch):
    def behaviour(n, side, kw):
        raise _MissingDependencyError("tesseract: language data for 'amh' not found")
    calls = _fake_ocrmypdf(monkeypatch, behaviour)
    with pytest.raises(pdf.OcrUnavailable, match="amh"):
        pdf._extract_ocr(b"%PDF", "amh+eng")
    assert len(calls) == 1                     # no pointless plain retry
    with pytest.raises(pdf.OcrUnavailable):
        pdf._extract_ocr(b"%PDF", "amh+eng")
    assert len(calls) == 1                     # cached: the next scan doesn't pay again


# --- run: --ocr override and the circuit breaker -------------------------------------------

PDF_RECIPE = r"""
source_id: test_ocr
country: Brazil
source_language: Portuguese
start_urls: ["http://x/discursos"]
content_type: pdf
listing: { link_pattern: '\.pdf' }
title: {}
text: {}
date: {}
date_languages: ["pt"]
"""


class _PdfFetcher:
    def __init__(self, **kwargs):
        pass

    def get_bytes(self, url):
        return "application/pdf", b"%PDF-1.4 scan"

    def get(self, url):
        raise AssertionError("bytes only")

    def close(self):
        pass


def _run(tmp_path, monkeypatch, n, extractor, **kw):
    urls = [f"http://x/discursos/{i:03d}.pdf" for i in range(n)]
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: list(urls))
    monkeypatch.setattr(run, "Fetcher", _PdfFetcher)
    monkeypatch.setattr(pdf, "pdf_bytes_to_text", extractor)
    p = tmp_path / "test_ocr.yml"
    p.write_text(PDF_RECIPE, encoding="utf-8")
    out = tmp_path / "scraped"
    res = run.scrape_recipe(str(p), out_root=str(out), state_root=str(tmp_path / "state"), **kw)
    return res, out


def test_run_ocr_flag_turns_ocr_on_with_the_derived_language(tmp_path, monkeypatch):
    seen = []

    def extractor(data, ocr=False, ocr_language="eng"):
        seen.append((ocr, ocr_language))
        return "Discurso recuperado por OCR."
    res, _ = _run(tmp_path, monkeypatch, 2, extractor, ocr=True)
    assert res["scraped_this_run"] == 2
    assert seen == [(True, "por+eng")] * 2

    seen.clear()
    (tmp_path / "again").mkdir()
    _run(tmp_path / "again", monkeypatch, 1, extractor)   # without the flag: the recipe's own off
    assert seen == [(False, "por+eng")]


def test_a_run_of_scans_does_not_trip_the_circuit_breaker(tmp_path, monkeypatch):
    """30 image-only PDFs in a row (> the 25-failure breaker) must not abort the source: an
    unreadable scan says nothing about being blocked."""
    def scan(data, ocr=False, ocr_language="eng"):
        pdf._last_empty_reason = "document has no text layer; OCR off (recipe pdf_ocr / run --ocr)"
        return ""
    res, out = _run(tmp_path, monkeypatch, 30, scan)
    assert res["failed_this_run"] == 30
    assert res["documents_no_text"] == 30
    errors = (out / "Brazil" / "test_ocr_errors.csv").read_text(encoding="utf-8")
    assert errors.count("empty_text (document has no text layer; OCR off") == 30
