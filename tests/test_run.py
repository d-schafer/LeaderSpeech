"""The stop -> identify -> fix -> resume workflow, exercised without network by
faking the link harvester and the fetcher."""

import json
from pathlib import Path

from leaderspeech.text_scraper import pdf, run

RECIPE_YAML = r"""
source_id: test_src
country: Argentina
source_language: Spanish
start_urls: ["http://x/list"]
listing: { link_selector: "a" }
title: { selectors: ["h1"] }
text: { selectors: ["div.body"] }
date: { selectors: [".date"] }
"""

WAYBACK_RECIPE_YAML = r"""
source_id: test_wayback
country: Argentina
source_language: Spanish
start_urls: ["casarosada.gob.ar/informacion/discursos"]
listing: { link_selector: "a", link_pattern: '/discursos/\d+$' }
pagination: { type: wayback, wayback_to: "20151210" }
title: { selectors: ["h1"] }
text: { selectors: [".body"] }
date: { selectors: ["time"] }
date_languages: ["es"]
"""

API_RECIPE_YAML = r"""
source_id: test_api
country: Argentina
source_language: Spanish
start_urls: ["http://x/_api/search/query"]
listing: { link_pattern: 'http://x/' }
pagination:
  type: api
  api: { results_path: results, url_field: url }
title: { selectors: ["h1"] }
text: { selectors: ["div.body"] }
date: { selectors: [".date"] }
date_languages: ["es"]
"""

EXTEND_RECIPE_YAML = r"""
source_id: test_extend
country: Argentina
source_language: Spanish
start_urls: ["http://x/list"]
listing: { link_selector: "a", link_pattern: '/(?:live|old)-' }
title: { selectors: ["h1"] }
text: { selectors: ["div.body"] }
date: { selectors: [".date"] }
date_languages: ["es"]
wayback_extend: true
"""

NO_DATE_HTML = "<html><h1>Page Title</h1><div class='body'>Cuerpo del discurso.</div></html>"

GOOD_HTML = (
    "<html><h1>Titulo</h1><span class='date'>1 de enero de 2020</span>"
    "<div class='body'>Hola mundo, esto es un discurso de prueba.</div></html>"
)

WAYBACK_HTML = (
    "<html><h1>Discurso de prueba</h1><time>1 de enero de 2008</time>"
    "<div class='body'>Texto archivado.</div></html>"
)


class FakeFetcher:
    behavior: dict = {}  # url -> "boom" to simulate a failure; otherwise serves GOOD_HTML

    def __init__(self, **kwargs):
        pass

    def get(self, url):
        if FakeFetcher.behavior.get(url) == "boom":
            raise RuntimeError("simulated network failure")
        return GOOD_HTML

    def close(self):
        pass


def _recipe(tmp_path):
    p = tmp_path / "test_src.yml"
    p.write_text(RECIPE_YAML, encoding="utf-8")
    return str(p)


def _wayback_recipe(tmp_path):
    p = tmp_path / "test_wayback.yml"
    p.write_text(WAYBACK_RECIPE_YAML, encoding="utf-8")
    return str(p)


def test_failure_is_logged_then_fixable_and_resumable(tmp_path, monkeypatch):
    urls = ["http://x/a-good", "http://x/b-boom"]
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: list(urls))
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)
    FakeFetcher.behavior = {"http://x/b-boom": "boom"}

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    recipe = _recipe(tmp_path)

    # 1) first run: one scrapes, one fails (and is recorded, not lost)
    res = run.scrape_recipe(recipe, out_root=str(out), state_root=str(state_dir))
    assert res["scraped_this_run"] == 1
    assert res["failed_this_run"] == 1
    assert res["failed_pending_retry"] == 1

    state = json.loads((state_dir / "Argentina.json").read_text(encoding="utf-8"))
    assert "http://x/a-good" in state["seen_urls"]
    assert "http://x/b-boom" in state["failed_urls"]      # failed, NOT marked done

    errors = (out / "Argentina" / "test_src_errors.csv").read_text(encoding="utf-8")
    assert "b-boom" in errors and "simulated network failure" in errors

    # 2) a plain re-run skips the known failure (and the already-done URL)
    assert run.scrape_recipe(recipe, out_root=str(out), state_root=str(state_dir))[
        "scraped_this_run"] == 0

    # 3) "fix" the source, then retry ONLY the failures
    FakeFetcher.behavior = {}
    res3 = run.scrape_recipe(recipe, out_root=str(out), state_root=str(state_dir),
                             retry_failed=True)
    assert res3["scraped_this_run"] == 1
    assert res3["failed_pending_retry"] == 0

    state = json.loads((state_dir / "Argentina.json").read_text(encoding="utf-8"))
    assert "http://x/b-boom" in state["seen_urls"]
    assert state["failed_urls"] == []

    # doc_ids stayed unique and contiguous across runs (ARG0001 then ARG0002)
    assert state["last_doc_num"] == 2


def test_circuit_breaker_aborts_on_consecutive_failures(tmp_path, monkeypatch):
    urls = [f"http://x/{i}-boom" for i in range(20)]
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: list(urls))
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)
    FakeFetcher.behavior = {u: "boom" for u in urls}

    res = run.scrape_recipe(
        _recipe(tmp_path), out_root=str(tmp_path / "s"), state_root=str(tmp_path / "st"),
        max_consecutive_failures=5,
    )
    assert res["aborted_early"] is True
    assert res["scraped_this_run"] == 0
    assert res["failed_this_run"] == 5  # stopped right after the 5th, didn't grind through 20


def test_wayback_recipe_scrapes_archived_snapshots(tmp_path, monkeypatch):
    entries = [
        {"timestamp": "20080100", "original": "https://www.casarosada.gob.ar/informacion/discursos"},
        {"timestamp": "20080100", "original": "https://www.casarosada.gob.ar/informacion/discursos?start=40"},
        {"timestamp": "20080101", "original": "https://www.casarosada.gob.ar/informacion/discursos/1"},
        {"timestamp": "20080101", "original": "https://www.casarosada.gob.ar/informacion/discursos/18-nuestro-pais/galeria-de-presidentes/1"},
        {"timestamp": "20080102", "original": "https://www.casarosada.gob.ar/informacion/discursos/2"},
    ]
    monkeypatch.setattr(run.wayback, "list_snapshots_for_queries", lambda *a, **k: list(entries))
    monkeypatch.setattr(
        run.wayback,
        "fetch_snapshot",
        lambda entry, delay=3.0, timeout=60.0, client=None: WAYBACK_HTML,
    )
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    res = run.scrape_recipe(_wayback_recipe(tmp_path), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 2
    assert res["failed_this_run"] == 0
    assert res["links_found"] == 2

    state = json.loads((state_dir / "Argentina.json").read_text(encoding="utf-8"))
    assert state["seen_urls"] == [entries[2]["original"], entries[4]["original"]]

    csv = (out / "Argentina" / "test_wayback.csv").read_text(encoding="utf-8")
    assert "Discurso de prueba" in csv
    assert "2008-01-01" in csv


def test_api_carries_json_metadata_and_skips_fetch_when_text_present(tmp_path, monkeypatch):
    """api/feed entries carry metadata: the page-extracted record is enriched from the
    JSON for fields it missed (here, the date), and an entry whose text is already in
    the JSON is used directly without fetching the speech page at all."""
    entries = [
        # page is fetchable but has no parseable date -> the JSON date must be carried
        {"url": "http://x/no-date", "title": "JSON Title", "date": "2019-05-01",
         "text": "", "speaker": ""},
        # JSON carries the full text -> the page must NOT be fetched
        {"url": "http://x/embedded", "title": "Embedded Title", "date": "2018-03-03",
         "text": "Texto completo desde el JSON.", "speaker": "Quien Sea"},
    ]
    monkeypatch.setattr(run.api, "harvest_entries", lambda *a, **k: [dict(e) for e in entries])

    class ApiFetcher:
        def __init__(self, **kwargs):
            pass

        def get(self, url):
            if url == "http://x/embedded":
                raise AssertionError("embedded entry should not be fetched")
            return NO_DATE_HTML

        def close(self):
            pass

    monkeypatch.setattr(run, "Fetcher", ApiFetcher)

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    p = tmp_path / "test_api.yml"
    p.write_text(API_RECIPE_YAML, encoding="utf-8")
    res = run.scrape_recipe(str(p), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 2
    assert res["failed_this_run"] == 0

    csv = (out / "Argentina" / "test_api.csv").read_text(encoding="utf-8")
    assert "Cuerpo del discurso." in csv         # page body for the fetched item
    assert "2019-05-01" in csv                    # date carried from JSON (page had none)
    assert "Texto completo desde el JSON." in csv  # embedded text used (fetch skipped)
    assert "2018-03-03" in csv                     # embedded entry date


def _extend_recipe(tmp_path):
    p = tmp_path / "test_extend.yml"
    p.write_text(EXTEND_RECIPE_YAML, encoding="utf-8")
    return str(p)


def test_wayback_extend_continues_after_live_and_dedupes(tmp_path, monkeypatch):
    """A live recipe with `wayback_extend: true` continues into the archive: the CDX
    harvest is bounded by the earliest LIVE date, doc_ids keep counting, and any archived
    capture whose URL was already scraped live is deduped away."""
    live_urls = ["http://x/live-a", "http://x/live-b"]
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: list(live_urls))
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)
    FakeFetcher.behavior = {}

    # archived captures: one dup of a live URL (must be skipped) + two genuinely older ones
    archive_entries = [
        {"timestamp": "20140101", "original": "http://x/live-a"},   # already scraped live
        {"timestamp": "20140102", "original": "http://x/old-1"},
        {"timestamp": "20140103", "original": "http://x/old-2"},
    ]
    captured = {}

    def fake_lsfq(urls, from_date=None, to_date=None, limit=None,
                  match_type="prefix", collapse="urlkey", filters=None):
        captured["urls"] = list(urls)
        captured["to_date"] = to_date
        return [dict(e) for e in archive_entries]

    monkeypatch.setattr(run.wayback, "list_snapshots_for_queries", fake_lsfq)
    monkeypatch.setattr(
        run.wayback, "fetch_snapshot",
        lambda entry, delay=5.0, timeout=60.0, client=None: WAYBACK_HTML,
    )

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    res = run.scrape_recipe(_extend_recipe(tmp_path), out_root=str(out), state_root=str(state_dir))

    # the archive harvest was bounded by the earliest live date (GOOD_HTML => 2020-01-01)
    assert captured["to_date"] == "20200101"
    # 2 live + 2 new archive (the live-a dup was deduped, so not 3)
    assert res["scraped_this_run"] == 4
    assert res["extended_links_found"] == 3     # all 3 passed the CDX filter
    assert res["extended_scraped"] == 2         # but only the 2 new ones were scraped
    assert res["failed_this_run"] == 0
    assert res["aborted_early"] is False

    state = json.loads((state_dir / "Argentina.json").read_text(encoding="utf-8"))
    assert state["last_doc_num"] == 4           # doc_ids continued across the two phases
    assert set(state["seen_urls"]) == {"http://x/live-a", "http://x/live-b",
                                       "http://x/old-1", "http://x/old-2"}

    csv = (out / "Argentina" / "test_extend.csv").read_text(encoding="utf-8")
    assert "ARG0003" in csv and "ARG0004" in csv  # archive rows got the next doc_ids
    assert "Texto archivado." in csv


def test_extend_wayback_flag_triggers_without_recipe_field(tmp_path, monkeypatch):
    """The `--extend-wayback` run flag turns on the continuation even for a recipe that
    has no `wayback_extend` field."""
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: ["http://x/a-good"])
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)
    FakeFetcher.behavior = {}
    monkeypatch.setattr(
        run.wayback, "list_snapshots_for_queries",
        lambda *a, **k: [{"timestamp": "20140102", "original": "http://x/old-1"}],
    )
    monkeypatch.setattr(
        run.wayback, "fetch_snapshot",
        lambda entry, delay=5.0, timeout=60.0, client=None: WAYBACK_HTML,
    )

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    res = run.scrape_recipe(_recipe(tmp_path), out_root=str(out), state_root=str(state_dir),
                            extend_wayback=True)

    assert res["extended_scraped"] == 1         # the archive capture was scraped via the flag
    assert res["scraped_this_run"] == 2         # 1 live + 1 archive


PDF_STATIC_RECIPE_YAML = r"""
source_id: test_pdf
country: Brazil
source_language: Portuguese
start_urls: ["http://x/discursos"]
content_type: pdf
listing: { link_pattern: '\.pdf' }
title: {}
text: {}
date: { url_regex: '/(?P<year>\d{4})/(?P<day>\d{2})-(?P<month>\d{2})-' }
speaker_default: Lula da Silva
position: president
date_languages: ["pt"]
"""

PDF_WAYBACK_RECIPE_YAML = r"""
source_id: test_pdf_wb
country: Brazil
source_language: Portuguese
start_urls: ["biblioteca.presidencia.gov.br/discursos"]
content_type: pdf
listing: { link_pattern: '/\d{4}/\d{2}-\d{2}' }
pagination:
  type: wayback
  wayback_filter: ["mimetype:application/pdf", "statuscode:200"]
title: {}
text: {}
date: { url_regex: '/(?P<year>\d{4})/(?P<day>\d{2})-(?P<month>\d{2})-' }
speaker_default: Lula da Silva
position: president
date_languages: ["pt"]
"""


class PdfFetcher:
    """A fetcher whose get_bytes serves PDF magic bytes (so looks_like_pdf passes); the
    actual text comes from a monkeypatched pdf.pdf_bytes_to_text."""
    payload = b"%PDF-1.4 fake pdf bytes"

    def __init__(self, **kwargs):
        pass

    def get_bytes(self, url):
        return "application/pdf", PdfFetcher.payload

    def get(self, url):
        raise AssertionError("a content_type: pdf recipe must fetch bytes, not text")

    def close(self):
        pass


def test_pdf_static_recipe_extracts_body_and_url_date(tmp_path, monkeypatch):
    """A live static content_type: pdf recipe: each harvested URL is fetched as bytes,
    the body comes from the PDF, and the date is read unambiguously off the URL."""
    urls = ["http://x/discursos/1o-mandato/2003/18-06-2003-discurso-a.pdf",
            "http://x/discursos/2o-mandato/2009/01-05-2009-discurso-b.pdf"]
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: list(urls))
    monkeypatch.setattr(run, "Fetcher", PdfFetcher)
    monkeypatch.setattr(pdf, "pdf_bytes_to_text", lambda data: "Corpo do discurso do presidente.")

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    p = tmp_path / "test_pdf.yml"
    p.write_text(PDF_STATIC_RECIPE_YAML, encoding="utf-8")
    res = run.scrape_recipe(str(p), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 2
    assert res["failed_this_run"] == 0
    csv = (out / "Brazil" / "test_pdf.csv").read_text(encoding="utf-8")
    assert "Corpo do discurso do presidente." in csv   # PDF body -> text_originlanguage (pt)
    assert "2003-06-18" in csv and "2009-05-01" in csv  # DD-MM-YYYY from the URL
    assert "Lula da Silva" in csv                       # speaker_default


def test_pdf_wayback_recipe_extracts_archived_pdf(tmp_path, monkeypatch):
    """content_type: pdf over pagination: wayback — archived captures are fetched as bytes
    (fetch_snapshot_bytes) and run through the PDF extractor, and the CDX `filters` are
    passed through."""
    entries = [
        {"timestamp": "20081010", "original": "http://x/discursos/1o-mandato/2003/18-06-2003-a.pdf"},
        {"timestamp": "20091111", "original": "http://x/discursos/2o-mandato/2009/01-05-2009-b.pdf"},
    ]
    captured = {}

    def fake_lsfq(urls, filters=None, **k):
        captured["filters"] = filters
        return [dict(e) for e in entries]

    monkeypatch.setattr(run.wayback, "list_snapshots_for_queries", fake_lsfq)
    monkeypatch.setattr(
        run.wayback, "fetch_snapshot_bytes",
        lambda entry, delay=5.0, timeout=60.0, client=None: ("application/pdf", b"%PDF-1.4 x"),
    )
    monkeypatch.setattr(pdf, "pdf_bytes_to_text", lambda data: "Texto do PDF arquivado.")

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    p = tmp_path / "test_pdf_wb.yml"
    p.write_text(PDF_WAYBACK_RECIPE_YAML, encoding="utf-8")
    res = run.scrape_recipe(str(p), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 2
    assert res["failed_this_run"] == 0
    assert captured["filters"] == ["mimetype:application/pdf", "statuscode:200"]
    csv = (out / "Brazil" / "test_pdf_wb.csv").read_text(encoding="utf-8")
    assert "Texto do PDF arquivado." in csv
    assert "2003-06-18" in csv and "2009-05-01" in csv


def test_pdf_mode_falls_back_to_html_when_payload_is_not_a_pdf(tmp_path, monkeypatch):
    """A content_type: pdf URL that actually returns HTML (a mixed listing / error page) is
    parsed as HTML instead of fed to the PDF extractor."""
    html = ("<html><h1>Titulo</h1><span class='date'>1 de enero de 2020</span>"
            "<div class='body'>Cuerpo HTML.</div></html>").encode("utf-8")

    class HtmlBytesFetcher(PdfFetcher):
        def get_bytes(self, url):
            return "text/html", html

    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: ["http://x/d/2020/01-01-x.pdf"])
    monkeypatch.setattr(run, "Fetcher", HtmlBytesFetcher)

    recipe_yaml = PDF_STATIC_RECIPE_YAML.replace("text: {}", "text: { selectors: ['div.body'] }")
    p = tmp_path / "test_pdf_html.yml"
    p.write_text(recipe_yaml, encoding="utf-8")
    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    res = run.scrape_recipe(str(p), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 1
    csv = (out / "Brazil" / "test_pdf.csv").read_text(encoding="utf-8")
    assert "Cuerpo HTML." in csv   # recovered via the HTML selector, not the PDF path


def test_no_wayback_extend_by_default(tmp_path, monkeypatch):
    """Backward-compat: a plain recipe with no field and no flag never touches the CDX."""
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: ["http://x/a-good"])
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)
    FakeFetcher.behavior = {}

    def boom(*a, **k):
        raise AssertionError("wayback CDX must not be queried without the field/flag")

    monkeypatch.setattr(run.wayback, "list_snapshots_for_queries", boom)

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    res = run.scrape_recipe(_recipe(tmp_path), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 1
    assert res["extended_links_found"] == 0
    assert res["extended_scraped"] == 0


# --- keep_if: the harvest is filtered by the PAGE, not just the URL (issue #52) --------

KEEP_IF_RECIPE_YAML = r"""
source_id: test_keep
country: Argentina
source_language: Spanish
start_urls: ["http://x/list"]
listing: { link_selector: "a" }
keep_if:
  selectors: [".breadcrumb"]
  pattern: "Discursos"
title: { selectors: ["h1"] }
text: { selectors: ["div.body"] }
date: { selectors: [".date"] }
date_languages: ["es"]
"""

# Both permalinks are bare ids — indistinguishable by link_pattern. Only the breadcrumb
# separates the president's speech from the ministry's press release.
SPEECH_HTML = (
    "<html><nav class='breadcrumb'>Inicio &gt; Discursos</nav><h1>Titulo</h1>"
    "<span class='date'>1 de enero de 2020</span>"
    "<div class='body'>Palabras del Presidente.</div></html>"
)
PRESS_RELEASE_HTML = (
    "<html><nav class='breadcrumb'>Inicio &gt; Salud</nav><h1>Comunicado</h1>"
    "<span class='date'>2 de enero de 2020</span>"
    "<div class='body'>Comunicado del ministerio.</div></html>"
)


class CategoryFetcher:
    """Serves a speech for /keep-* URLs and a ministry press release for /drop-* ones."""

    def __init__(self, **kwargs):
        pass

    def get(self, url):
        return SPEECH_HTML if "keep" in url else PRESS_RELEASE_HTML

    def close(self):
        pass


def _keep_recipe(tmp_path):
    p = tmp_path / "test_keep.yml"
    p.write_text(KEEP_IF_RECIPE_YAML, encoding="utf-8")
    return str(p)


def test_keep_if_filters_by_page_category_and_counts_it(tmp_path, monkeypatch):
    urls = ["http://x/12345-keep", "http://x/23456-drop", "http://x/34567-drop"]
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: list(urls))
    monkeypatch.setattr(run, "Fetcher", CategoryFetcher)

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    res = run.scrape_recipe(_keep_recipe(tmp_path), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 1
    assert res["filtered_out_this_run"] == 2
    # A rejection is a decision, not a failure: no error rows, nothing to retry.
    assert res["failed_this_run"] == 0
    assert res["failed_pending_retry"] == 0
    assert not (out / "Argentina" / "test_keep_errors.csv").exists()

    rows = (out / "Argentina" / "test_keep.csv").read_text(encoding="utf-8")
    assert "Palabras del Presidente." in rows
    assert "Comunicado del ministerio." not in rows
    # doc_ids are only spent on kept rows
    assert json.loads((state_dir / "Argentina.json").read_text(encoding="utf-8"))[
        "last_doc_num"] == 1


def test_filtered_urls_are_remembered_and_never_refetched(tmp_path, monkeypatch):
    """The whole point on a 5,903-capture archive: don't re-fetch the rejects every run."""
    urls = ["http://x/12345-keep", "http://x/23456-drop"]
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: list(urls))
    monkeypatch.setattr(run, "Fetcher", CategoryFetcher)

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    recipe = _keep_recipe(tmp_path)
    run.scrape_recipe(recipe, out_root=str(out), state_root=str(state_dir))

    state = json.loads((state_dir / "Argentina.json").read_text(encoding="utf-8"))
    assert state["filtered_urls"] == ["http://x/23456-drop"]
    assert state["seen_urls"] == ["http://x/12345-keep"]   # kept apart from scraped
    assert state["failed_urls"] == []

    fetched = []

    class Recording(CategoryFetcher):
        def get(self, url):
            fetched.append(url)
            return super().get(url)

    monkeypatch.setattr(run, "Fetcher", Recording)
    res = run.scrape_recipe(recipe, out_root=str(out), state_root=str(state_dir))

    assert res["filtered_out_this_run"] == 0     # nothing re-judged...
    assert res["filtered_total"] == 1            # ...but the decision is still recorded
    assert fetched == []

    # --retry-failed retries FAILURES, not rejections: a keep_if decision stands.
    run.scrape_recipe(recipe, out_root=str(out), state_root=str(state_dir), retry_failed=True)
    assert fetched == []


def test_a_keep_if_that_matches_nothing_is_shouted_about(tmp_path, monkeypatch):
    """The dangerous mis-specification: every page dropped, no errors, empty source."""
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: ["http://x/1-drop", "http://x/2-drop"])
    monkeypatch.setattr(run, "Fetcher", CategoryFetcher)

    res = run.scrape_recipe(_keep_recipe(tmp_path), out_root=str(tmp_path / "s"),
                            state_root=str(tmp_path / "st"))

    assert res["scraped_this_run"] == 0
    assert res["filtered_out_this_run"] == 2
    log_text = Path(res["log"]).read_text(encoding="utf-8")
    assert "FILTERED OUT ALL" in log_text


# --- issue #55: a listing's date lands on a dateless PDF row -----------------------------

ETH_PDF_RECIPE_YAML = r"""
source_id: eth_pmo_test
country: Ethiopia
source_language: Amharic
start_urls: ["https://pmo.gov.et/speeches/"]
renderer: static
content_type: pdf
listing:
  link_pattern: '/media/documents/.*\.pdf'
  item_selector: "div.row.content-display"
  item_date: { selectors: ["div.meta-data p"] }
title: {}
text: {}
date: {}
position: prime minister
speaker_default: Abiy Ahmed
date_languages: ["am", "en"]
"""


def test_listing_date_lands_on_a_pdf_row(tmp_path, monkeypatch):
    """The eth_pmo case: the body is a dateless PDF whose only date sits on the HTML
    listing. The date must come from the listing — and must NOT be recovered from the
    filename, whose `_2015` is an ETHIOPIAN-calendar year for a speech listed Jan 27 2023."""
    url = "https://pmo.gov.et/media/documents/festival_2015.pdf"

    def fake_harvest(recipe, fetcher, *a, meta=None, **k):
        # what extract_links would have written into the out-param from the listing block
        if meta is not None:
            meta[url] = {"date": "2023-01-27", "_from": {"date": "listing: div.meta-data p"}}
        return [url]

    monkeypatch.setattr(run, "harvest_links", fake_harvest)
    monkeypatch.setattr(run, "Fetcher", PdfFetcher)
    monkeypatch.setattr(pdf, "pdf_bytes_to_text", lambda data: "የንግግር ጽሑፍ።")

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    p = tmp_path / "eth.yml"
    p.write_text(ETH_PDF_RECIPE_YAML, encoding="utf-8")
    res = run.scrape_recipe(str(p), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 1
    csv = (out / "Ethiopia" / "eth_pmo_test.csv").read_text(encoding="utf-8")
    assert "2023-01-27" in csv          # from the listing
    assert "2015-" not in csv           # the Ethiopian-calendar mis-stamp never happens


def test_the_page_always_wins_over_listing_metadata(tmp_path, monkeypatch):
    """Carried metadata only ever fills a blank. Here the PDF's own first line IS a title,
    so a (hypothetical) listing title must not overwrite it."""
    url = "https://pmo.gov.et/media/documents/x.pdf"

    def fake_harvest(recipe, fetcher, *a, meta=None, **k):
        if meta is not None:
            meta[url] = {"title": "Listing title", "date": "2023-01-27"}
        return [url]

    monkeypatch.setattr(run, "harvest_links", fake_harvest)
    monkeypatch.setattr(run, "Fetcher", PdfFetcher)
    monkeypatch.setattr(pdf, "pdf_bytes_to_text", lambda data: "PDF first line is the title\nbody")

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    p = tmp_path / "eth.yml"
    p.write_text(ETH_PDF_RECIPE_YAML, encoding="utf-8")
    run.scrape_recipe(str(p), out_root=str(out), state_root=str(state_dir))

    csv = (out / "Ethiopia" / "eth_pmo_test.csv").read_text(encoding="utf-8")
    assert "PDF first line is the title" in csv   # page wins
    assert "Listing title" not in csv


def test_listing_metadata_never_skips_the_pdf_fetch(tmp_path, monkeypatch):
    """A carried `text` would make run.py skip the page fetch; listing metadata must never
    carry one, so the PDF body is always actually read. PdfFetcher.get() raises if the
    fetch is routed wrong, so a passing run proves the bytes path was taken."""
    url = "https://pmo.gov.et/media/documents/x.pdf"

    def fake_harvest(recipe, fetcher, *a, meta=None, **k):
        if meta is not None:                     # date + title, but crucially no text
            meta[url] = {"date": "2023-01-27", "title": "Listing title"}
        return [url]

    monkeypatch.setattr(run, "harvest_links", fake_harvest)
    monkeypatch.setattr(run, "Fetcher", PdfFetcher)
    monkeypatch.setattr(pdf, "pdf_bytes_to_text", lambda data: "Real PDF body text.")

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    p = tmp_path / "eth.yml"
    p.write_text(ETH_PDF_RECIPE_YAML, encoding="utf-8")
    res = run.scrape_recipe(str(p), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 1
    csv = (out / "Ethiopia" / "eth_pmo_test.csv").read_text(encoding="utf-8")
    assert "Real PDF body text." in csv          # the PDF really was fetched + extracted
