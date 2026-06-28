"""Extraction + cleanup + link harvesting, on synthetic HTML (no network)."""

from leaderspeech.text_scraper.extract import clean_text, first_match, parse_date
from leaderspeech.text_scraper.paginate import extract_links
from leaderspeech.text_scraper.recipe import FieldSpec, Listing


def test_clean_text_collapses_ws_and_drops_blanks():
    raw = "  Hello   world \r\n\n   \n  second   line  "
    assert clean_text(raw) == "Hello world\nsecond line"
    assert clean_text(None) == ""


def test_parse_date_multilingual_and_messy():
    assert parse_date("January 6, 2021", ["en"]) == "2021-01-06"
    assert parse_date("25 de mayo de 2024", ["es"]) == "2024-05-25"
    # date wrapped in noise -> search_dates fallback
    assert parse_date("Buenos Aires, 25 de mayo de 2024", ["es"]) == "2024-05-25"
    assert parse_date("Publié le 14 juillet 2023", ["fr"]) == "2023-07-14"
    assert parse_date("", ["en"]) is None


def test_first_match_uses_fallback_chain():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<div><h2 class='t'>Title here</h2></div>", "lxml")
    spec = FieldSpec(selectors=["h1.title", "h2.t", "title"])  # first misses, second hits
    assert "Title here" in first_match(soup, spec)


def test_first_match_reads_attribute():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<time datetime="2020-02-03">Feb 3</time>', "lxml")
    spec = FieldSpec(selectors=["time"], attr="datetime")
    assert first_match(soup, spec) == "2020-02-03"


def test_extract_links_filters_pattern_dedupes_and_resolves():
    html = """
    <a class="d" href="/discursos/101">a</a>
    <a class="d" href="/discursos/102">b</a>
    <a class="d" href="/about">skip</a>
    <a class="d" href="/discursos/101">dup</a>
    """
    listing = Listing(link_selector="a.d", link_pattern=r"/discursos/\d+")
    links = extract_links(html, "https://ex.org/discursos", listing)
    assert links == [
        "https://ex.org/discursos/101",
        "https://ex.org/discursos/102",
    ]
