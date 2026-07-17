"""Probe diagnostics — what the reviewer is told, and whether it is true.

The probe is the only cheap check before a FULL RUN, so a misleading report is not a
cosmetic bug: it gets working recipes "fixed" and broken ones merged (issues #53/#54).
"""

from bs4 import BeautifulSoup

from leaderspeech.text_scraper import probe, wayback
from leaderspeech.text_scraper.extract import extract_pdf_record, extract_record
from leaderspeech.text_scraper.recipe import Recipe, WaybackExtend

# A date that exists ONLY in the URL. Deliberate: aus_gg_wayback and
# tha_royaloffice_wayback both drop their body-date selector on purpose (one would
# mis-stamp speeches that quote another date, the other renders the Buddhist era, where
# 2565 = 2022), so url_regex is the *correct* mechanism, not a missing selector.
URL_DATE_RECIPE = Recipe(
    source_id="x", country="Australia",
    start_urls=["https://example.org/speeches"],
    listing={"link_selector": "a"},
    title={"selectors": ["h1"]},
    text={"selectors": ["article"]},
    date={"url_regex": r"/speeches/(?P<year>\d{4})/\d{2}(?P<month>\d{2})(?P<day>\d{2})[a-z]?\.html"},
    speaker_default="Sir William Deane",
)

URL_DATE_HTML = "<html><h1>An Address</h1><article>The body of the speech.</article></html>"
URL_DATE_URL = "https://example.org/speeches/html/speeches/2000/000813.html"


def _report(recipe, name, html, url):
    rec = extract_record(html, url, recipe)
    return rec, probe._html_field_report(recipe, name, BeautifulSoup(html, "lxml"), url, rec)


def test_url_regex_only_field_reports_its_source_not_no_match():
    rec, f = _report(URL_DATE_RECIPE, "date", URL_DATE_HTML, URL_DATE_URL)

    assert rec["date"] == "2000-08-13"                     # the field DID resolve...
    assert f["matched_selector"] == (                      # ...so say how, don't cry ✗
        r"url_regex: /speeches/(?P<year>\d{4})/\d{2}(?P<month>\d{2})(?P<day>\d{2})[a-z]?\.html")


def test_speaker_default_reports_its_source():
    rec, f = _report(URL_DATE_RECIPE, "speaker", URL_DATE_HTML, URL_DATE_URL)

    assert rec["speaker"] == "Sir William Deane"
    assert f["matched_selector"] == "speaker_default: Sir William Deane"


def test_selector_backed_field_still_reports_the_selector():
    _, f = _report(URL_DATE_RECIPE, "title", URL_DATE_HTML, URL_DATE_URL)
    assert f["matched_selector"] == "h1"


def test_field_that_truly_resolves_to_nothing_is_still_flagged():
    """The other half: ✗ has to keep meaning something, or it stops being a signal."""
    rec, f = _report(URL_DATE_RECIPE, "date", URL_DATE_HTML, "https://example.org/no-date-here")

    assert rec["date"] is None
    assert f["matched_selector"] is None
    assert f["tried"] == [
        r"url_regex: /speeches/(?P<year>\d{4})/\d{2}(?P<month>\d{2})(?P<day>\d{2})[a-z]?\.html"]


def test_tried_list_names_url_regex_and_default_not_an_empty_list():
    """'NO MATCH (tried: [])' was a lie for a url_regex field — nothing was listed as
    tried because only `selectors` was reported."""
    _, f = _report(URL_DATE_RECIPE, "speaker", URL_DATE_HTML, "https://example.org/x")
    assert f["tried"] == ["speaker_default: Sir William Deane"]


def test_url_regex_wins_when_the_date_selector_matches_but_does_not_parse():
    """A date selector can match text that isn't a date; extract_record then falls through
    to url_regex. Report the mechanism that actually produced the value, and say why the
    selector didn't."""
    recipe = URL_DATE_RECIPE.model_copy(update={
        "date": URL_DATE_RECIPE.date.model_copy(update={"selectors": [".date"]}),
    })
    html = ("<html><h1>An Address</h1><span class='date'>Court Circular</span>"
            "<article>Body.</article></html>")
    rec, f = _report(recipe, "date", html, URL_DATE_URL)

    assert rec["date"] == "2000-08-13"
    assert f["matched_selector"].startswith("url_regex:")
    assert "did not parse as a date" in f["note"]


def test_print_marks_a_url_regex_field_with_a_tick(capsys):
    rec, _ = _report(URL_DATE_RECIPE, "date", URL_DATE_HTML, URL_DATE_URL)
    soup = BeautifulSoup(URL_DATE_HTML, "lxml")
    probe._print({
        "recipe": "aus_gg_wayback", "country": "Australia", "renderer": "static",
        "listing": {"mode": "wayback snapshots", "snapshots_found": 1, "sampled": 1},
        "pages": [{"url": URL_DATE_URL, "parsed_date": rec["date"], "recipe_text_len": 21,
                   "generic_text_len": 21,
                   "fields": {name: probe._html_field_report(
                       URL_DATE_RECIPE, name, soup, URL_DATE_URL, rec)
                       for name in probe.FIELDS}}],
    })
    out = capsys.readouterr().out

    assert "✓ date" in out
    assert "✗ date" not in out


# --- issue #53: a truncated harvest must not be reported as a coverage number ----------


def test_wayback_probe_prints_snapshot_count(capsys):
    report = {
        "recipe": "arg_casarosada_wayback",
        "country": "Argentina",
        "renderer": "static",
        "listing": {
            "mode": "wayback snapshots",
            "snapshots_found": 2,
            "sampled": 1,
            "sample": ["https://example.org/a"],
        },
        "pages": [],
    }

    probe._print(report)
    out = capsys.readouterr().out

    assert "LISTING ✓ 2 snapshot(s)" in out
    assert "0 link(s)" not in out


def test_print_flags_a_harvest_that_stopped_early(capsys):
    """Austria reported 'LISTING ✓ 10 link(s)' while silently missing 1,288 of them."""
    probe._print({
        "recipe": "aut_bundespraesident", "country": "Austria", "renderer": "js",
        "listing": {"mode": "spread (full history)", "links_found": 10, "sampled": 2,
                    "stopped_early": True, "stop_reason": "next_click_failed"},
        "pages": [],
    })
    out = capsys.readouterr().out

    assert "PAGINATION STOPPED EARLY (next_click_failed)" in out
    assert "NOT the size of the archive" in out


# --- issue #54: probe can exercise wayback_extend ---------------------------------------

EXTEND_RECIPE = Recipe(
    source_id="x_extend", country="Argentina",
    start_urls=["https://www.casarosada.gob.ar/discursos/"],
    listing={"link_selector": "a", "link_pattern": r"/discursos/\d+$"},
    title={"selectors": ["h1"]},
    text={"selectors": [".modern-body"]},
    date={"selectors": ["time"]},
    wayback_extend={"text": {"selectors": [".legacy-body"]}},
)


def test_extend_prefix_and_link_pattern_default_to_the_live_recipe():
    ext = EXTEND_RECIPE.wayback_extend
    assert wayback.extend_prefix(EXTEND_RECIPE, ext) == "www.casarosada.gob.ar/discursos"
    assert wayback.extend_link_pattern(EXTEND_RECIPE, ext) == r"/discursos/\d+$"


def test_extend_recipe_applies_only_the_declared_overrides():
    """The archived layout differs, so the probe must extract with the OVERRIDES applied —
    otherwise it validates selectors the run won't use."""
    ext_recipe = wayback.extend_recipe(EXTEND_RECIPE, EXTEND_RECIPE.wayback_extend)

    assert ext_recipe.text.selectors == [".legacy-body"]     # overridden
    assert ext_recipe.title.selectors == ["h1"]              # inherited
    assert EXTEND_RECIPE.text.selectors == [".modern-body"]  # live recipe untouched


def test_extend_to_date_prefers_the_explicit_override(tmp_path):
    to_date, source = probe._extend_to_date(
        EXTEND_RECIPE, WaybackExtend(wayback_to="20200101"), str(tmp_path), "20150101")
    assert (to_date, source) == ("20150101", "--wayback-to")


def test_extend_to_date_falls_back_to_the_recipe_then_the_scraped_floor(tmp_path):
    assert probe._extend_to_date(
        EXTEND_RECIPE, WaybackExtend(wayback_to="20200101"), str(tmp_path), None)[0] == "20200101"

    csv_dir = tmp_path / "Argentina"
    csv_dir.mkdir()
    (csv_dir / "x_extend.csv").write_text(
        "doc_id,date\nARG0001,2015-12-10\nARG0002,2019-03-04\n", encoding="utf-8")
    to_date, source = probe._extend_to_date(EXTEND_RECIPE, WaybackExtend(), str(tmp_path), None)

    assert to_date == "20151210"             # CDX form of the earliest live row
    assert "date_floor" in source


def test_extend_to_date_is_unbounded_when_nothing_has_been_scraped(tmp_path):
    to_date, source = probe._extend_to_date(EXTEND_RECIPE, WaybackExtend(), str(tmp_path), None)
    assert to_date is None
    assert "unbounded" in source


def test_probe_samples_the_archived_continuation(monkeypatch, tmp_path):
    """End to end: `wayback_extend` used to run ONLY inside a full crawl, so its
    archived-layout selectors were unverifiable until after the money was spent."""

    class FakeFetcher:
        def __init__(self, *a, **kw):
            pass

        def get(self, url):
            return '<a href="/discursos/9">live</a>'

        def close(self):
            pass

    monkeypatch.setattr(probe, "Fetcher", FakeFetcher)
    monkeypatch.setattr(probe.wayback, "create_client", lambda *a, **kw: None)
    monkeypatch.setattr(
        probe.wayback, "list_snapshots_for_queries",
        lambda *a, **kw: [{"timestamp": "20090101",
                           "original": "https://www.casarosada.gob.ar/discursos/1"}])
    # The archived page uses the OLD markup, which only the override selects.
    monkeypatch.setattr(probe.wayback, "fetch_snapshot",
                        lambda *a, **kw: "<h1>Discurso viejo</h1>"
                                         "<div class='legacy-body'>Palabras de 2009.</div>")

    recipe_path = tmp_path / "x_extend.yml"
    recipe_path.write_text(EXTEND_RECIPE.model_dump_json(), encoding="utf-8")  # YAML ⊃ JSON

    report = probe.probe(str(recipe_path), n=1, out_root=str(tmp_path))
    ext = report["wayback_extend"]

    assert ext["snapshots_found"] == 1
    assert ext["prefix"] == "www.casarosada.gob.ar/discursos"
    assert ext["overrides"] == ["text"]
    assert ext["to_date"] is None                       # nothing scraped yet -> unbounded
    page = report["extend_pages"][0]
    assert page["fields"]["text"]["matched_selector"] == ".legacy-body"
    assert page["recipe_text_len"] == len("Palabras de 2009.")


def test_print_warns_that_an_unbounded_extend_probe_proves_less(capsys):
    probe._print({
        "recipe": "x_extend", "country": "Argentina", "renderer": "static",
        "listing": {"url": "https://x/", "links_found": 1, "sample": []},
        "pages": [],
        "wayback_extend": {"prefix": "www.casarosada.gob.ar/discursos", "link_pattern": None,
                           "to_date": None,
                           "to_date_source": "unbounded (nothing scraped yet, no wayback_to)",
                           "overrides": [], "snapshots_found": 3, "sampled": 1, "sample": []},
        "extend_pages": [],
    })
    out = capsys.readouterr().out

    assert "WAYBACK-EXTEND  ✓ 3 archived capture(s)" in out
    assert "UNBOUNDED" in out


# --- issue #52: the probe has to show what keep_if did, or a filter that empties a
# source looks identical to a healthy recipe.

KEEP_IF_RECIPE = Recipe(
    source_id="x_keep", country="Thailand",
    start_urls=["https://example.org/news"],
    listing={"link_selector": "a"},
    keep_if={"selectors": ["div.panel-heading span.headtitle-2"], "pattern": "PM speeches"},
    title={"selectors": ["h1"]},
    text={"selectors": ["div.body"]},
    date={"selectors": [".date"]},
)


def _keep_page(category):
    return (f"<html><div class='panel-heading'><span class='headtitle-2'>{category}</span></div>"
            f"<h1>T</h1><div class='body'>Body text.</div></html>")


def test_keep_if_summary_counts_kept_and_filtered():
    pages = [{"keep": True}, {"keep": False}, {"keep": False}, {"url": "u", "error": "boom"}]
    summary = probe._keep_if_summary(KEEP_IF_RECIPE, pages)

    assert summary["sampled"] == 3          # the fetch error isn't a keep_if verdict
    assert summary["kept"] == 1
    assert summary["filtered_out"] == 2
    assert summary["pattern"] == "PM speeches"


def test_probe_reports_the_keep_if_verdict_per_page(monkeypatch, tmp_path):
    """A page keep_if drops must be visibly dropped, not silently absent."""

    class FakeFetcher:
        def __init__(self, *a, **kw):
            pass

        def get(self, url):
            if url.endswith("/news"):
                return '<a href="/details/1">a</a><a href="/details/2">b</a>'
            return _keep_page("PM speeches" if url.endswith("1") else "Ministry of Health")

        def close(self):
            pass

    monkeypatch.setattr(probe, "Fetcher", FakeFetcher)
    recipe_path = tmp_path / "x_keep.yml"
    recipe_path.write_text(KEEP_IF_RECIPE.model_dump_json(), encoding="utf-8")

    report = probe.probe(str(recipe_path), n=2)

    assert [p["keep"] for p in report["pages"]] == [True, False]
    assert report["keep_if"]["kept"] == 1
    assert report["keep_if"]["filtered_out"] == 1


def test_print_shouts_when_keep_if_keeps_nothing(capsys):
    probe._print({
        "recipe": "x_keep", "country": "Thailand", "renderer": "static",
        "listing": {"url": "https://x/", "links_found": 2, "sample": []},
        "keep_if": {"selectors": [".missing"], "pattern": "PM speeches", "negate": False,
                    "sampled": 2, "kept": 0, "filtered_out": 2},
        "pages": [],
    })
    out = capsys.readouterr().out

    assert "KEEP_IF ✗ kept 0 of 2" in out
    assert "a real run would write 0 rows" in out


def test_print_warns_when_keep_if_filters_nothing(capsys):
    """The opposite mis-specification: a pattern matching the site's nav keeps the whole
    wire, and every per-field tick still says ✓."""
    probe._print({
        "recipe": "x_keep", "country": "Thailand", "renderer": "static",
        "listing": {"url": "https://x/", "links_found": 2, "sample": []},
        "keep_if": {"selectors": ["nav"], "pattern": "PM speeches", "negate": False,
                    "sampled": 5, "kept": 5, "filtered_out": 0},
        "pages": [],
    })
    out = capsys.readouterr().out

    assert "filtered out nothing in this sample" in out


# --- issue #54, PDF path: a url_regex-resolved DATE was still reported as ✗ NO MATCH ----

def test_pdf_report_names_url_regex_for_a_date_it_resolved():
    """Regression: found while authoring gmb_op. extract_pdf_record PARSES the url_regex
    match into an ISO date, so rec["date"] is "2022-11-18" while match_url returns the raw
    first group ("11"). Comparing those never matched, so the probe printed
    `✗ date <- NO MATCH` directly above `parsed_date: 2022-11-18`."""
    from tests.test_pdf import make_minimal_pdf

    recipe = Recipe(
        source_id="gmb_x", country="Gambia",
        start_urls=["https://op.gov.gm/speeches"],
        listing={"link_pattern": r"\.pdf"},
        content_type="pdf",
        title={"url_regex": r"/([^/]+)\.pdf"},
        text={},
        date={"url_regex": r"/(?P<month>\d{2})(?P<day>\d{2})(?P<year>20\d{2})(?:%20|\s|_|-)"},
        speaker_default="Adama Barrow",
    )
    url = "https://op.gov.gm/sites/default/files/11182022%20H.E%20Barrow%20Trade.pdf"
    rec = extract_pdf_record(make_minimal_pdf("Statement by the President."), url, recipe)
    report = probe._pdf_page_report(recipe, url, rec)

    assert rec["date"] == "2022-11-18"                       # MMDDYYYY, resolved
    assert report["fields"]["date"]["matched_selector"] == (
        r"url_regex: /(?P<month>\d{2})(?P<day>\d{2})(?P<year>20\d{2})(?:%20|\s|_|-)")
    assert report["fields"]["title"]["matched_selector"] == r"url_regex: /([^/]+)\.pdf"
    assert report["fields"]["speaker"]["matched_selector"] == "speaker_default: Adama Barrow"


def test_pdf_report_still_flags_a_date_that_resolved_to_nothing():
    from tests.test_pdf import make_minimal_pdf

    recipe = Recipe(
        source_id="gmb_x", country="Gambia",
        start_urls=["https://op.gov.gm/speeches"],
        listing={"link_pattern": r"\.pdf"},
        content_type="pdf",
        title={"url_regex": r"/([^/]+)\.pdf"},
        text={},
        date={"url_regex": r"/(?P<month>\d{2})(?P<day>\d{2})(?P<year>20\d{2})(?:%20|\s|_|-)"},
    )
    # No MMDDYYYY prefix -> genuinely undated (17 of gmb_op's 58 PDFs look like this).
    url = "https://op.gov.gm/sites/default/files/EngFinalCommunique.pdf"
    rec = extract_pdf_record(make_minimal_pdf("Communique text."), url, recipe)
    report = probe._pdf_page_report(recipe, url, rec)

    assert rec["date"] is None
    assert report["fields"]["date"]["matched_selector"] is None
