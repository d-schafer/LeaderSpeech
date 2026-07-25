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
    monkeypatch.setattr(run, "pdf_bytes_to_text", lambda d: "THE REAL SPEECH TEXT from the pdf")
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


def test_wayback_pdf_follow_uses_nearest_capture(monkeypatch):
    captured = {}

    def fake_fetch_snapshot_bytes(entry, delay=0.0, client=None):
        captured["entry"] = entry
        return "application/pdf", b"%PDF-..."
    monkeypatch.setattr(run.wayback, "fetch_snapshot_bytes", fake_fetch_snapshot_bytes)
    monkeypatch.setattr(run, "looks_like_pdf", lambda d: True)
    monkeypatch.setattr(run, "pdf_bytes_to_text", lambda d: "archived pdf speech text")

    rec = {"text": "chrome", "title": ""}
    ok = run._follow_pdf_body(rec, HTML, PAGE_URL, _recipe(), is_wayback=True,
                              timestamp="20210816003406", wayback_client=object(), wayback_delay=0.0)
    assert ok is True
    assert rec["text"] == "archived pdf speech text"
    assert rec["title"] == "archived pdf speech text"    # title backfilled from the PDF (was empty)
    # the synthesized CDX entry pairs the PAGE's capture timestamp with the ORIGINAL pdf url,
    # so Wayback serves the PDF capture nearest that moment
    assert captured["entry"] == {"timestamp": "20210816003406", "original": PDF_URL}
