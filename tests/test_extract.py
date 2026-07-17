"""Extraction + cleanup + link harvesting, on synthetic HTML (no network)."""

from leaderspeech.text_scraper.extract import (clean_text, first_match, parse_date,
                                              should_keep)
from leaderspeech.text_scraper.paginate import extract_links
from leaderspeech.text_scraper.recipe import FieldSpec, KeepIf, Listing


def test_clean_text_collapses_ws_and_drops_blanks():
    raw = "  Hello   world \r\n\n   \n  second   line  "
    assert clean_text(raw) == "Hello world\nsecond line"
    assert clean_text(None) == ""


def test_parse_date_multilingual_and_messy():
    assert parse_date("January 6, 2021", ["en"]) == "2021-01-06"
    assert parse_date("25 de mayo de 2024", ["es"]) == "2024-05-25"
    assert parse_date("1995-09-03T15:40:00+03:00", ["ru"]) == "1995-09-03"
    # date wrapped in noise -> search_dates fallback
    assert parse_date("Buenos Aires, 25 de mayo de 2024", ["es"]) == "2024-05-25"
    assert parse_date("Publié le 14 juillet 2023", ["fr"]) == "2023-07-14"
    assert parse_date("", ["en"]) is None


def test_parse_date_rejects_implausible_years():
    # dateparser can return year 0001 from a date fragment with no real year;
    # a wrong date is worse than a blank one, so we reject implausible years.
    assert parse_date("0001-11-30", ["en"]) is None
    assert parse_date("November 30, 1850", ["en"]) is None


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


# --- keep_if: filter by ON-PAGE category, for sites whose URL carries none (issue #52)

# The Thailand shape: every article is /news/contents/details/<bare-id>, so link_pattern
# cannot tell a PM speech from a Ministry of Public Health press release. Only the page
# says which it is.
PM_PAGE = ("<html><nav class='breadcrumb'>หน้าแรก &gt; ข่าวนายกรัฐมนตรี</nav>"
           "<div class='body'>คำกล่าวของนายกรัฐมนตรี</div></html>")
MINISTRY_PAGE = ("<html><nav class='breadcrumb'>หน้าแรก &gt; ข่าวกระทรวงสาธารณสุข</nav>"
                 "<div class='body'>Press release.</div></html>")


def _soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "lxml")


def test_should_keep_is_a_noop_without_a_keep_if():
    assert should_keep(None, _soup(MINISTRY_PAGE)) is True


def test_should_keep_matches_on_page_category():
    spec = KeepIf(selectors=[".breadcrumb"], pattern="ข่าวนายกรัฐมนตรี")
    assert should_keep(spec, _soup(PM_PAGE)) is True
    assert should_keep(spec, _soup(MINISTRY_PAGE)) is False


def test_should_keep_tries_every_selector_as_an_alternative():
    """Sites move the crumb around; several selectors are ORed, not a first-match chain."""
    spec = KeepIf(selectors=[".nope", ".news-list-category", ".breadcrumb"],
                  pattern="ข่าวนายกรัฐมนตรี")
    assert should_keep(spec, _soup(PM_PAGE)) is True


def test_should_keep_drops_when_the_selector_is_absent():
    """No category element at all = no evidence this is a leader item = drop. The
    filtered_out counter is what makes a mis-specified selector visible."""
    spec = KeepIf(selectors=[".does-not-exist"], pattern="anything")
    assert should_keep(spec, _soup(PM_PAGE)) is False


def test_should_keep_negate_inverts_the_verdict():
    spec = KeepIf(selectors=[".breadcrumb"], pattern="สาธารณสุข", negate=True)
    assert should_keep(spec, _soup(MINISTRY_PAGE)) is False   # matches -> dropped
    assert should_keep(spec, _soup(PM_PAGE)) is True


def test_should_keep_without_selectors_tests_the_whole_document():
    spec = KeepIf(pattern="คำกล่าวของนายกรัฐมนตรี")
    assert should_keep(spec, _soup(PM_PAGE)) is True
    assert should_keep(spec, _soup(MINISTRY_PAGE)) is False


def test_should_keep_selectors_alone_test_mere_presence():
    assert should_keep(KeepIf(selectors=[".breadcrumb"]), _soup(PM_PAGE)) is True
    assert should_keep(KeepIf(selectors=[".missing"]), _soup(PM_PAGE)) is False


def test_should_keep_ignores_a_malformed_selector_instead_of_raising():
    spec = KeepIf(selectors=["<<not css>>", ".breadcrumb"], pattern="ข่าวนายกรัฐมนตรี")
    assert should_keep(spec, _soup(PM_PAGE)) is True


def test_selector_keep_if_is_a_noop_without_a_dom():
    """A PDF (or api/feed-carried text) has no DOM. Rejecting the whole source would be
    worse than passing it to the cleaner's gate, so an unevaluatable selector keeps."""
    spec = KeepIf(selectors=[".breadcrumb"], pattern="ข่าวนายกรัฐมนตรี")
    assert should_keep(spec, None, "some pdf text") is True


def test_pattern_only_keep_if_still_filters_a_pdf_by_its_text():
    spec = KeepIf(pattern="Prime Minister")
    assert should_keep(spec, None, "Remarks by the Prime Minister") is True
    assert should_keep(spec, None, "Ministry of Health bulletin") is False


def test_keep_if_needs_selectors_or_a_pattern():
    import pytest

    with pytest.raises(ValueError, match="keep_if needs 'selectors' and/or 'pattern'"):
        KeepIf()


# --- issue #55: shared carried-metadata helpers -----------------------------------------
from bs4 import BeautifulSoup  # noqa: E402

from leaderspeech.text_scraper.extract import (apply_entry_meta, entry_source,  # noqa: E402
                                              listing_meta)


def test_apply_entry_meta_only_fills_blanks():
    """The one rule the whole feature rests on: a value the page produced always wins."""
    rec = {"title": "Real title", "text": "", "date": None, "speaker": ""}
    entry = {"title": "Listing title", "date": "2023-10-06", "speaker": "Abiy Ahmed"}

    filled = apply_entry_meta(rec, entry)

    assert rec["title"] == "Real title"          # page wins, untouched
    assert rec["date"] == "2023-10-06"           # blank -> filled
    assert rec["speaker"] == "Abiy Ahmed"
    assert set(filled) == {"date", "speaker"}


def test_apply_entry_meta_ignores_an_empty_entry():
    rec = {"title": "", "date": None}
    assert apply_entry_meta(rec, {}) == []
    assert apply_entry_meta(rec, None) == []
    assert rec == {"title": "", "date": None}


def test_apply_entry_meta_does_not_invent_missing_keys():
    # an entry that carries only a date must not add empty text/speaker to the record
    rec = {"title": "", "text": "body", "date": None, "speaker": ""}
    filled = apply_entry_meta(rec, {"date": "2018-05-14"})
    assert filled == ["date"]
    assert rec["title"] == ""


ITEM_HTML = ('<div class="row"><div class="meta-data"><p>Oct. 6, 2023</p></div>'
             '<h1 class="heading">Erecha</h1></div>')


def _item():
    return BeautifulSoup(ITEM_HTML, "lxml").select_one("div.row")


def test_listing_meta_parses_the_date_in_the_sites_language():
    from leaderspeech.text_scraper.recipe import Listing
    listing = Listing(link_pattern=r"\.pdf", item_selector="div.row",
                      item_date={"selectors": ["div.meta-data p"]},
                      item_title={"selectors": ["h1.heading"]})
    meta = listing_meta(_item(), listing, ["am", "en"])
    assert meta["date"] == "2023-10-06"
    assert meta["title"] == "Erecha"
    assert "text" not in meta                     # never text
    assert meta["_from"]["date"] == "listing: div.meta-data p"


def test_listing_meta_is_scoped_to_the_block():
    """first_match runs on the item Tag, so a selector that would match elsewhere on the
    page but not inside this block resolves to nothing."""
    from leaderspeech.text_scraper.recipe import Listing
    listing = Listing(link_pattern=r"\.pdf", item_selector="div.row",
                      item_date={"selectors": [".not-here"]})
    assert listing_meta(_item(), listing, ["en"]) == {}


def test_entry_source_prefers_the_recorded_selector():
    entry = {"date": "2023-10-06", "_from": {"date": "listing: div.meta-data p"}}
    assert entry_source(entry, "date") == "listing: div.meta-data p"
    # api/feed entries carry no _from -> a generic label
    assert entry_source({"date": "2023-10-06"}, "date") == "carried entry metadata"
    assert entry_source(None, "date") == "carried entry metadata"
