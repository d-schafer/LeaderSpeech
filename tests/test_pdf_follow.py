"""PDF-following (`recipe.pdf_link`): a page that is only a title + a link to the speech PDF
pulls its body from that (archived) PDF instead of scraping the HTML chrome. See
run._follow_pdf_body + the wiring in _scrape_phase."""

from leaderspeech.text_scraper import run
from leaderspeech.text_scraper.recipe import FieldSpec, Listing, Recipe

HTML = ('<html><head><title>AOP</title></head><body><nav>menu menu</nav>'
        '<a href="/storage/uploads/international/408.pdf">Download</a></body></html>')
PAGE_URL = "https://aop.gov.af/dr/information_details/408"
PDF_URL = "https://aop.gov.af/storage/uploads/international/408.pdf"


def _recipe(**kw):
    base = dict(
        source_id="t", country="Afghanistan", start_urls=["aop.gov.af/dr"],
        listing=Listing(link_pattern="/dr/"),
        title=FieldSpec(selectors=["title"]), text=FieldSpec(selectors=[".body"]),
        date=FieldSpec(selectors=[".date"]),
        pdf_link=FieldSpec(selectors=["a[href*='/storage/uploads/']"], attr="href"),
    )
    base.update(kw)
    return Recipe(**base)


class FakeFetcher:
    def __init__(self, data=b"%PDF-1.4"):
        self.data = data
        self.calls = []

    def get_bytes(self, url):
        self.calls.append(url)
        return "application/pdf", self.data


def test_live_pdf_follow_replaces_chrome_body(monkeypatch):
    monkeypatch.setattr(run, "looks_like_pdf", lambda d: True)
    monkeypatch.setattr(run, "pdf_bytes_to_text", lambda d, ocr=False, ocr_language="eng": "THE REAL SPEECH TEXT from the pdf")
    rec = {"text": "menu chrome", "title": "AOP"}
    f = FakeFetcher()
    assert run._follow_pdf_body(rec, HTML, PAGE_URL, _recipe(), is_wayback=False, fetcher=f) is True
    assert rec["text"] == "THE REAL SPEECH TEXT from the pdf"
    assert f.calls == [PDF_URL]                          # relative href resolved against the page URL


def test_no_pdf_link_configured_is_noop():
    rec = {"text": "keep me", "title": "t"}
    assert run._follow_pdf_body(rec, HTML, PAGE_URL, _recipe(pdf_link=None),
                                is_wayback=False, fetcher=None) is False
    assert rec["text"] == "keep me"


def test_no_matching_href_is_noop():
    rec = {"text": "keep me"}
    html = "<html><body><a href='/about'>no pdf here</a></body></html>"
    assert run._follow_pdf_body(rec, html, PAGE_URL, _recipe(), is_wayback=False,
                                fetcher=FakeFetcher()) is False
    assert rec["text"] == "keep me"


# --- attr + regex: an element without the attribute is read as TEXT (2026-09-27) --------
# presidencia.gob.sv links some speech PDFs as <a href> and names others only in a dead
# "[gview file=»…pdf»]" shortcode, both inside .post-content, next to a sidebar of
# unrelated PDF links. One spec must catch both forms and never the sidebar.

SV_PAGE = "https://www.presidencia.gob.sv/discurso-toma-de-posesion/"
SV_RX = r"https?://[^\s»«\"'<>\[\]]+?\.pdf"
SV_SIDEBAR = '<aside><a href="https://www.presidencia.gob.sv/wp-content/uploads/memoria.pdf">M</a></aside>'


def _sv_recipe(**kw):
    spec = dict(selectors=[".post-content a[href$='.pdf']", ".post-content"],
                attr="href", regex=SV_RX)
    spec.update(kw)
    return _recipe(pdf_link=FieldSpec(**spec))


def _sv_follow(html, recipe, monkeypatch):
    monkeypatch.setattr(run, "looks_like_pdf", lambda d: True)
    monkeypatch.setattr(run, "pdf_bytes_to_text", lambda d, ocr=False, ocr_language="eng": "SPEECH")
    f = FakeFetcher()
    ok = run._follow_pdf_body({"text": "stub"}, html, SV_PAGE, recipe, is_wayback=False, fetcher=f)
    return ok, f.calls


def test_attr_regex_reads_a_shortcode_named_pdf_from_text(monkeypatch):
    html = ('<div class="post-content"><p>[gview file=»https://www.presidencia.gob.sv/'
            'wp-content/uploads/2020/09/Toma-de-posesión-01-06-2019-1.pdf»]</p></div>'
            + SV_SIDEBAR)
    ok, calls = _sv_follow(html, _sv_recipe(), monkeypatch)
    assert ok is True
    assert calls == ["https://www.presidencia.gob.sv/wp-content/uploads/2020/09/"
                     "Toma-de-posesión-01-06-2019-1.pdf"]


def test_attr_regex_still_prefers_the_href(monkeypatch):
    html = ('<div class="post-content"><p><a href="/wp-content/uploads/2026/09/DISCURSO.pdf">'
            'Discurso</a></p></div>' + SV_SIDEBAR)
    ok, calls = _sv_follow(html, _sv_recipe(), monkeypatch)
    assert ok is True
    assert calls == ["https://www.presidencia.gob.sv/wp-content/uploads/2026/09/DISCURSO.pdf"]


def test_attr_regex_text_pass_never_returns_unmatched_text(monkeypatch):
    # an ordinary article body with no PDF named: the text pass must miss, not hand the
    # prose to the fetcher as a "URL" — and the sidebar PDF is out of scope.
    html = '<div class="post-content"><p>El Presidente inauguró la obra.</p></div>' + SV_SIDEBAR
    ok, calls = _sv_follow(html, _sv_recipe(), monkeypatch)
    assert ok is False and calls == []


def test_attr_without_regex_keeps_the_old_behaviour(monkeypatch):
    # no regex -> no text pass: the shortcode form is simply not followed (pre-2026-09-27)
    html = ('<div class="post-content">[gview file=»https://x/a.pdf»]</div>')
    ok, calls = _sv_follow(html, _sv_recipe(regex=None), monkeypatch)
    assert ok is False and calls == []


def test_fetch_failure_falls_back_to_html_body():
    class BoomFetcher:
        def get_bytes(self, url):
            raise RuntimeError("PDF not archived")
    rec = {"text": "html chrome body"}
    assert run._follow_pdf_body(rec, HTML, PAGE_URL, _recipe(), is_wayback=False,
                                fetcher=BoomFetcher()) is False
    assert rec["text"] == "html chrome body"             # unchanged -> row keeps the HTML body


def test_non_pdf_bytes_are_ignored():
    # the link resolved but the fetched bytes aren't actually a PDF (an HTML error page) -> no change
    rec = {"text": "chrome"}
    assert run._follow_pdf_body(rec, HTML, PAGE_URL, _recipe(), is_wayback=False,
                                fetcher=FakeFetcher(b"<html>404</html>")) is False
    assert rec["text"] == "chrome"


def test_wayback_pdf_follow_falls_back_to_page_timestamp(monkeypatch):
    # When CDX has no complete capture of the PDF, fall back to the synthesized entry:
    # the PAGE's capture timestamp + the ORIGINAL pdf url (the pre-#70 behavior).
    captured = {}

    def fake_fetch_snapshot_bytes(entry, delay=0.0, client=None, pacer=None):
        captured["entry"] = entry
        return "application/pdf", b"%PDF-..."
    monkeypatch.setattr(run.wayback, "best_capture", lambda url, **kw: None)
    monkeypatch.setattr(run.wayback, "fetch_snapshot_bytes", fake_fetch_snapshot_bytes)
    monkeypatch.setattr(run, "looks_like_pdf", lambda d: True)
    monkeypatch.setattr(run, "pdf_bytes_to_text", lambda d, ocr=False, ocr_language="eng": "archived pdf speech text")

    rec = {"text": "chrome", "title": ""}
    ok = run._follow_pdf_body(rec, HTML, PAGE_URL, _recipe(), is_wayback=True,
                              timestamp="20210816003406", wayback_client=object(), wayback_delay=0.0)
    assert ok is True
    assert rec["text"] == "archived pdf speech text"
    assert rec["title"] == "archived pdf speech text"    # title backfilled from the PDF (was empty)
    assert captured["entry"] == {"timestamp": "20210816003406", "original": PDF_URL}


def test_wayback_pdf_follow_picks_complete_capture(monkeypatch):
    # #70 Problem 1: when CDX has a complete capture of the PDF, fetch THAT one (not the
    # page-timestamp redirect, which may resolve to a truncated 1 MB partial).
    captured = {}
    complete = {"timestamp": "20200101000000", "original": PDF_URL, "statuscode": "200", "length": "6000000"}

    def fake_best_capture(url, **kw):
        captured["queried"] = url
        return complete

    def fake_fetch_snapshot_bytes(entry, delay=0.0, client=None, pacer=None):
        captured["entry"] = entry
        return "application/pdf", b"%PDF-..."
    monkeypatch.setattr(run.wayback, "best_capture", fake_best_capture)
    monkeypatch.setattr(run.wayback, "fetch_snapshot_bytes", fake_fetch_snapshot_bytes)
    monkeypatch.setattr(run, "looks_like_pdf", lambda d: True)
    monkeypatch.setattr(run, "pdf_bytes_to_text", lambda d, ocr=False, ocr_language="eng": "complete pdf text")

    rec = {"text": "chrome", "title": "t"}
    ok = run._follow_pdf_body(rec, HTML, PAGE_URL, _recipe(), is_wayback=True,
                              timestamp="20210816003406", wayback_client=object(), wayback_delay=0.0)
    assert ok is True
    assert captured["queried"] == PDF_URL
    assert captured["entry"] is complete                 # fetched the complete capture, not the synthesized one


def test_unextractable_pdf_clears_body(monkeypatch):
    # #70 Problem 3: a real PDF that yields no text (image-only scan / truncated capture) —
    # the pdf_link page's HTML is only chrome, so clear the body to fail the row cleanly.
    monkeypatch.setattr(run, "looks_like_pdf", lambda d: True)
    monkeypatch.setattr(run, "pdf_bytes_to_text", lambda d, ocr=False, ocr_language="eng": "")   # no text layer
    rec = {"text": "html chrome body", "title": "t"}
    ok = run._follow_pdf_body(rec, HTML, PAGE_URL, _recipe(), is_wayback=False, fetcher=FakeFetcher())
    assert ok is False
    assert rec["text"] == ""                             # cleared -> downstream empty_text, not chrome


def test_pdf_ocr_flag_is_forwarded(monkeypatch):
    # #70 Problem 2: recipe.pdf_ocr flows into pdf_bytes_to_text so the OCR fallback can fire.
    seen = {}

    def fake_extract(data, ocr=False, ocr_language="eng"):
        seen["ocr"] = ocr
        return "ocr recovered text"
    monkeypatch.setattr(run, "looks_like_pdf", lambda d: True)
    monkeypatch.setattr(run, "pdf_bytes_to_text", fake_extract)
    rec = {"text": "chrome", "title": "t"}
    ok = run._follow_pdf_body(rec, HTML, PAGE_URL, _recipe(pdf_ocr=True),
                              is_wayback=False, fetcher=FakeFetcher())
    assert ok is True
    assert seen["ocr"] is True
    assert rec["text"] == "ocr recovered text"
