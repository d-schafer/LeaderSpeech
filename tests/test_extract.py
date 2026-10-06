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


def test_selector_attr_suffix_mixes_attribute_and_text_in_one_chain():
    """2026-09-30: one site generation carries an ISO date in an attribute, another only as
    text — a whole-chain `attr` could not read both."""
    from bs4 import BeautifulSoup
    from leaderspeech.text_scraper.extract import split_selector

    spec = FieldSpec(selectors=["span[property~='dc:date']@content", ".node-created"],
                     regex=r"(?P<value>\d{4}-\d{2}-\d{2})|\d{1,2} de \w+ de \d{4}",
                     regex_required=True)
    gen_2013 = BeautifulSoup("<span property='dc:date dc:created' content='2013-04-26T19:15:50-04:00'>"
                             "Vie, 04/26/2013 - 19:15</span>", "lxml")
    gen_2014 = BeautifulSoup("<div class='node-created'>Lunes, 11 de Agosto de 2014</div>", "lxml")
    assert first_match(gen_2013, spec) == "2013-04-26"      # the attribute, not the MM/DD text
    assert first_match(gen_2014, spec) == "11 de Agosto de 2014"
    # an element WITHOUT the attribute is a miss for that selector: the chain moves on
    no_attr = BeautifulSoup("<span property='dc:date'>x</span><div class='node-created'>"
                            "1 de Mayo de 2015</div>", "lxml")
    assert first_match(no_attr, spec) == "1 de Mayo de 2015"
    # "@" inside brackets or parentheses is part of the CSS, not a suffix
    assert split_selector("a[href*='@']") == ("a[href*='@']", None)
    assert split_selector("meta[name='x']@content") == ("meta[name='x']", "content")
    assert split_selector("time @ datetime") == ("time", "datetime")
    assert split_selector("h1") == ("h1", None)


def test_regex_miss_returns_the_whole_value_by_default():
    """Historical behaviour, unchanged: `regex` is a best-effort trim."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<b>SPEECH AT THE BANQUET</b>", "lxml")
    spec = FieldSpec(selectors=["b"], regex=r"\d{4}")
    assert first_match(soup, spec) == "SPEECH AT THE BANQUET"


def test_regex_required_makes_a_miss_skip_to_the_next_selector():
    """With `regex_required`, a selector whose text doesn't contain the pattern is treated
    as not matching — so a headline can never be handed to dateparser as if it were a date
    (which is how a real page dated itself to TODAY; see FieldSpec.regex_required)."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<b>SPEECH AT THE BANQUET</b><p>New Delhi, 10 May, 2001</p>", "lxml")
    spec = FieldSpec(selectors=["b", "p"], regex=r"\d{1,2}\s+\w+,?\s+(?:19|20)\d\d",
                     regex_required=True)
    assert first_match(soup, spec) == "10 May, 2001"

    nothing = FieldSpec(selectors=["b"], regex=r"\d{4}", regex_required=True)
    assert first_match(soup, nothing) is None


def test_date_min_year_lets_a_recipe_keep_pre_1900_dates():
    """Default floor 1900 unchanged; a recipe may lower it for a genuinely old source."""
    assert parse_date("22 de junio de 1823", ["es"]) is None
    assert parse_date("22 de junio de 1823", ["es"], min_year=1800) == "1823-06-22"
    # the lowered floor still rejects dateparser's year-0001 inventions
    assert parse_date("0001-11-30", ["en"], min_year=1800) is None


def test_date_min_year_reaches_page_url_and_listing_dates():
    from bs4 import BeautifulSoup

    from leaderspeech.text_scraper.extract import (date_from_url, extract_record,
                                                   listing_meta)
    from leaderspeech.text_scraper.recipe import Recipe

    base = dict(source_id="t", country="Peru", start_urls=["https://x.example/"],
                listing={"link_pattern": "/m"},
                title={"selectors": ["h1"]}, text={"selectors": ["p"]},
                date={"selectors": ["h1"], "regex": r"\d{1,2} de \w+ de \d{4}",
                      "url_regex": r"/(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"},
                date_languages=["es"])
    html = "<h1>MENSAJE … EL 22 DE JUNIO DE 1823</h1><p>Texto</p>"
    old = Recipe(**base)
    new = Recipe(**base, date_min_year=1800)
    assert extract_record(html, "https://x.example/m", old)["date"] is None
    assert extract_record(html, "https://x.example/m", new)["date"] == "1823-06-22"
    # url_regex named groups honour the floor too
    assert date_from_url(new.date, "https://x.example/1851-03-20.pdf", ["es"],
                         min_year=1800) == "1851-03-20"
    assert date_from_url(old.date, "https://x.example/1851-03-20.pdf", ["es"]) is None
    # and a listing item date
    item = BeautifulSoup("<div><h3>Mensaje (28 de julio de 1895)</h3></div>", "lxml").div
    listing = Listing(link_pattern="/m", item_selector="div",
                      item_date=FieldSpec(selectors=["h3"]))
    assert listing_meta(item, listing, ["es"], min_year=1800)["date"] == "1895-07-28"
    assert "date" not in listing_meta(item, listing, ["es"])


def test_parse_date_ignores_line_breaks_inside_the_date():
    """A date split across text nodes ("de \\n2019") must keep its year. Without whitespace
    collapsing, search_dates found only "2 de marzo" and completed it with today's year."""
    assert parse_date("\n\nOruro, 2 de marzo de \n2019", ["es"]) == "2019-03-02"
    assert parse_date("10 de febrero\nde 2017", ["es"]) == "2017-02-10"


def test_regex_named_value_group_returns_only_that_group():
    """An anchored regex can require context (the dateline's place name) without returning
    it: a `(?P<value>…)` group is what the field gets."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<div class='b'>Oruro, 2 de marzo de 2019.- El presidente …</div>",
                         "lxml")
    spec = FieldSpec(selectors=["div.b"],
                     regex=r"^\W{0,3}(?:[^,.()]{2,60},\s*)?(?P<value>\d{1,2} de \w+ de \d{4})",
                     regex_required=True)
    assert first_match(soup, spec) == "2 de marzo de 2019"


def test_regex_plain_groups_still_return_the_whole_match():
    """Backward compatibility: an unnamed group used for alternation doesn't change the
    returned value (existing recipes rely on group(0))."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<p>Dated 10 May 2001 here</p>", "lxml")
    spec = FieldSpec(selectors=["p"], regex=r"\d{1,2} (May|June) \d{4}")
    assert first_match(soup, spec) == "10 May 2001"


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


def test_html_parser_option_recovers_a_page_whose_head_closes_html():
    # guatemala.gob.gt's 2008 discurso.php: a broken Dreamweaver template closes
    # </body></html> INSIDE <head>. lxml stops there and every selector misses (the whole
    # 18 KB speech parsed to 45 chars); Python's html.parser keeps reading.
    from leaderspeech.text_scraper.extract import extract_record
    from leaderspeech.text_scraper.recipe import Recipe

    html = ("<html><head><title>Gobierno de Guatemala</title></head></body></html>"
            "<style>td{}</style></head><body><table><tr><td class='style12'>"
            "Discurso del Presidente Álvaro Colom en La Unión, Zacapa. "
            "El Presidente se solidarizó con los afectados.</td></tr></table></body></html>")
    base = dict(source_id="t", country="Guatemala", start_urls=["https://x.example/"],
                listing={"link_pattern": "discurso"}, title={"selectors": ["title"]},
                text={"selectors": ["td.style12"]}, date={"selectors": ["time"]})
    default = Recipe(**base)
    assert default.html_parser == "lxml"                       # unchanged default
    # Not asserted: that lxml LOSES the text. That depends on the libxml2 bundled in the
    # lxml wheel — the Windows wheel (libxml2 2.11.9) drops it, the Linux CI wheel recovers
    # it — so it is a platform fact, not a property of our code.
    fixed = Recipe(**base, html_parser="html.parser")
    rec = extract_record(html, "https://x.example/discurso.php", fixed)
    assert rec["text"].startswith("Discurso del Presidente Álvaro Colom")


def test_html_parser_rejects_unknown_values():
    import pytest
    from pydantic import ValidationError
    from leaderspeech.text_scraper.recipe import Recipe
    with pytest.raises(ValidationError):
        Recipe(source_id="t", country="Guatemala", start_urls=["https://x.example/"],
               listing={"link_pattern": "x"}, title={"selectors": ["h1"]},
               text={"selectors": ["p"]}, date={"selectors": ["time"]}, html_parser="html5lib")


def test_weekday_date_resolves_a_yearless_date_inside_the_span():
    # presidencia.gob.mx 2006-08 prints "Jueves, 7 de Junio | Comunicado" with no year.
    from leaderspeech.text_scraper.extract import weekday_date
    assert weekday_date("Jueves, 7 de Junio | Comunicado", 2006, 2010) == "2007-06-07"
    assert weekday_date("Lunes, 4 de Diciembre | Discurso", 2006, 2010) == "2006-12-04"
    assert weekday_date("Thursday, April 26 | Speech", 2006, 2010) == "2007-04-26"
    assert weekday_date("Miércoles, 9 de septiembre", 2006, 2010) == "2009-09-09"


def test_weekday_date_refuses_ambiguity_a_year_and_nonsense():
    from leaderspeech.text_scraper.extract import weekday_date
    # 7 June fell on a Thursday in 2007 AND 2012: a wide span must not guess
    assert weekday_date("Jueves, 7 de Junio", 2000, 2020) is None
    # wrong weekday for every year in the span
    assert weekday_date("Lunes, 7 de Junio", 2007, 2007) is None
    # a 4-digit year present: the ordinary parser's job, not this one
    assert weekday_date("Viernes, 28 de Marzo de 2008", 2006, 2010) is None
    assert weekday_date("Comunicado 154", 2006, 2010) is None
    assert weekday_date("Lunes, 31 de Febrero", 2006, 2010) is None
    assert weekday_date(None, 2006, 2010) is None


def test_extract_record_uses_weekday_years_only_when_the_chain_yields_no_date():
    from leaderspeech.text_scraper.extract import extract_record
    from leaderspeech.text_scraper.recipe import Recipe

    date_spec = {"selectors": [".fecha"], "weekday_years": [2006, 2010],
                 "regex": r"(?P<value>\d{1,2} de \w+ de \d{4})", "regex_required": True}
    r = Recipe(source_id="t", country="Mexico", start_urls=["https://x.example/"],
               listing={"link_pattern": "x"}, title={"selectors": ["h1"]},
               text={"selectors": ["p"]}, date=date_spec, date_languages=["es"])
    yearless = "<h1>T</h1><p class='fecha'>Jueves, 7 de Junio | Comunicado</p><p>Cuerpo.</p>"
    dated = "<h1>T</h1><p class='fecha'>Viernes, 28 de Marzo de 2008 | Comunicado</p><p>C.</p>"
    assert extract_record(yearless, "https://x.example/a", r)["date"] == "2007-06-07"
    assert extract_record(dated, "https://x.example/b", r)["date"] == "2008-03-28"
    plain = Recipe(source_id="t", country="Mexico", start_urls=["https://x.example/"],
                   listing={"link_pattern": "x"}, title={"selectors": ["h1"]},
                   text={"selectors": ["p"]},
                   date={k: v for k, v in date_spec.items() if k != "weekday_years"},
                   date_languages=["es"])
    assert extract_record(yearless, "https://x.example/a", plain)["date"] is None
