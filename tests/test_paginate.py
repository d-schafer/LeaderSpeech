"""Pagination URL construction — especially `path_format`, which lets a `path`
page target non-numeric URLs (e.g. president.ie's /P0, /P20, /P40)."""

import gzip

import pytest

from leaderspeech.text_scraper import paginate
from leaderspeech.text_scraper.recipe import Recipe


def _recipe(**pagination):
    return Recipe(
        source_id="x",
        country="Ireland",
        start_urls=["https://example.org/speeches"],
        listing={"link_selector": "a", "link_pattern": "/s/"},
        title={"selectors": ["h1"]},
        text={"selectors": ["article"]},
        date={"selectors": [".date"]},
        pagination=pagination,
    )


class RecordingFetcher:
    """Records each requested URL and returns one fresh qualifying link per page,
    so harvesting keeps paginating until `max_pages`."""

    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return f'<a href="/s/{len(self.urls)}">item</a>'


def test_path_format_builds_prefixed_pages():
    # the president.ie case: /speeches/P0, /speeches/P20, /speeches/P40
    r = _recipe(type="path", path_format="P{n}", start=0, step=20, max_pages=3)
    f = RecordingFetcher()
    paginate.harvest_links(r, f)
    assert f.urls == [
        "https://example.org/speeches/P0",
        "https://example.org/speeches/P20",
        "https://example.org/speeches/P40",
    ]


def test_path_without_format_still_appends_bare_number():
    # backward-compat: existing `path` behavior is unchanged when path_format is unset
    r = _recipe(type="path", start=1, step=1, max_pages=2)
    f = RecordingFetcher()
    paginate.harvest_links(r, f)
    assert f.urls == [
        "https://example.org/speeches/1",
        "https://example.org/speeches/2",
    ]


def test_path_format_supports_padding():
    r = _recipe(type="path", path_format="page/{n:03d}", start=0, step=1, max_pages=2)
    f = RecordingFetcher()
    paginate.harvest_links(r, f)
    assert f.urls == [
        "https://example.org/speeches/page/000",
        "https://example.org/speeches/page/001",
    ]


def test_path_format_requires_placeholder():
    with pytest.raises(ValueError, match="must contain the '\\{n\\}' page-index placeholder"):
        _recipe(type="path", path_format="Pnnn", start=0, step=20)


# --- next_link: follow the listing's own "next" <a href> (static, unsynthesisable pagers)


class NextLinkFetcher:
    """Serves a chain of listing pages joined by a signed 'next' link.

    Models the TYPO3 cHash case: the page URL carries an opaque token, so it can only
    be *followed*, never constructed. The last page has no next link.
    """

    def __init__(self, pages=3, wrapper=False):
        self.pages, self.wrapper, self.urls = pages, wrapper, []

    def get(self, url):
        self.urls.append(url)
        n = len(self.urls)
        html = f'<a href="/s/{n}">item{n}</a>'
        if n < self.pages:
            nxt = f'/list?page={n + 1}&cHash=deadbeef{n + 1}'
            html += (f'<li class="next"><a data-nextlink href="{nxt}">next</a></li>'
                     if self.wrapper else
                     f'<a class="next" data-nextlink href="{nxt}">next</a>')
        return html


def test_next_link_follows_chain_until_exhausted():
    r = _recipe(type="next_link", next_selector="a[data-nextlink]", max_pages=10)
    f = NextLinkFetcher(pages=3)
    links = paginate.harvest_links(r, f)
    assert f.urls == [
        "https://example.org/speeches",
        "https://example.org/list?page=2&cHash=deadbeef2",
        "https://example.org/list?page=3&cHash=deadbeef3",
    ]
    assert links == ["https://example.org/s/1", "https://example.org/s/2",
                     "https://example.org/s/3"]


def test_next_link_selector_may_wrap_the_anchor():
    # `li.next` points at a wrapper; the descendant <a href> is used.
    r = _recipe(type="next_link", next_selector="li.next", max_pages=10)
    f = NextLinkFetcher(pages=2, wrapper=True)
    paginate.harvest_links(r, f)
    assert f.urls == ["https://example.org/speeches",
                      "https://example.org/list?page=2&cHash=deadbeef2"]


def test_next_link_respects_max_pages():
    r = _recipe(type="next_link", next_selector="a[data-nextlink]", max_pages=2)
    f = NextLinkFetcher(pages=99)
    paginate.harvest_links(r, f)
    assert len(f.urls) == 2


def test_next_link_stops_on_self_referential_pager():
    """A pager whose 'next' points back at the current page must not spin forever."""

    class Loop:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            return ('<a href="/s/1">item</a>'
                    '<a data-nextlink href="https://example.org/speeches">next</a>')

    r = _recipe(type="next_link", next_selector="a[data-nextlink]", max_pages=50)
    f = Loop()
    paginate.harvest_links(r, f)
    assert f.urls == ["https://example.org/speeches"]


def test_next_link_needs_a_next_selector():
    with pytest.raises(ValueError, match="next_link pagination needs 'next_selector'"):
        _recipe(type="next_link", max_pages=3)


def test_next_link_keeps_paginating_past_a_page_with_no_new_links():
    """Unlike query_param/path, a duplicate interior page must not truncate the crawl —
    only the absence of a next link ends it."""

    class DupeMiddle:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            n = len(self.urls)
            item = 1 if n == 2 else n  # page 2 repeats page 1's link
            html = f'<a href="/s/{item}">item</a>'
            if n < 3:
                html += f'<a data-nextlink href="/list?p={n + 1}&cHash=x{n + 1}">next</a>'
            return html

    r = _recipe(type="next_link", next_selector="a[data-nextlink]", max_pages=10)
    f = DupeMiddle()
    links = paginate.harvest_links(r, f)
    assert len(f.urls) == 3           # did not stop at the duplicate page
    assert links == ["https://example.org/s/1", "https://example.org/s/3"]


# --- url_list: explicit SPEECH urls, returned verbatim (docs/recipes.md used to call
# these "listing URLs", which is wrong — pin the real contract here).


def test_url_list_returns_speech_urls_verbatim_without_fetching():
    r = _recipe(type="url_list", url_list=["https://example.org/a", "https://example.org/b"])
    f = RecordingFetcher()
    links = paginate.harvest_links(r, f)
    assert links == ["https://example.org/a", "https://example.org/b"]
    assert f.urls == []  # never fetched as listings...


def test_url_list_ignores_link_pattern():
    # ...and listing.link_pattern (here "/s/") is NOT applied to them.
    r = _recipe(type="url_list", url_list=["https://example.org/not-matching-the-pattern"])
    assert paginate.harvest_links(r, RecordingFetcher()) == [
        "https://example.org/not-matching-the-pattern"
    ]


# --- issue #53: pagination must not end SILENTLY. A pager that breaks has to be
# distinguishable from an archive that genuinely ran out of pages.


class FakePage:
    """Minimal stand-in for a Playwright page driving `click` pagination.

    `click_raises` models the Austria case (#19/#53): the next control IS in the DOM, so
    `query_selector` finds it, but the site's JS hid it, so Playwright's actionability
    check times out and `.click()` raises.
    """

    def __init__(self, pages=3, click_raises=False, button=True):
        self.pages, self.click_raises, self.button = pages, click_raises, button
        self.n, self.url = 1, "https://example.org/speeches"

    def goto(self, url, **kw):
        self.url = url

    def content(self):
        return f'<a href="/s/{self.n}">item{self.n}</a>'

    def query_selector(self, selector):
        if not self.button or self.n >= self.pages:
            return None
        return self._Button(self)

    def wait_for_load_state(self, *a, **kw):
        pass

    class _Button:
        def __init__(self, page):
            self.page = page

        def click(self):
            if self.page.click_raises:
                raise TimeoutError("ElementHandle.click: Timeout 5000ms exceeded.\n"
                                   "  - element is not visible")
            self.page.n += 1


class FakeJsFetcher:
    def __init__(self, page):
        self.page = page


def test_click_pagination_broken_pager_warns_and_flags_stopped_early(caplog):
    """The Austria failure: the click raises, the crawl returns page 1, and every other
    signal says success. It must be loud, and the caller must be able to see it."""
    r = _recipe(type="click", next_selector="a.next", max_pages=10)
    page = FakePage(pages=99, click_raises=True)
    stats = {}
    with caplog.at_level("WARNING", logger="leaderspeech.text_scraper.paginate"):
        links = paginate.harvest_links(r, FakeJsFetcher(page), stats=stats)

    assert links == ["https://example.org/s/1"]      # truncated to page 1...
    assert stats["stopped_early"] is True            # ...and the caller can tell
    assert stats["stop_reason"] == "next_click_failed"
    assert "stopped EARLY" in caplog.text
    assert "next_link" in caplog.text                # the warning names the actual fix


def test_click_pagination_last_page_is_not_flagged_as_early(caplog):
    """The other half of the contract: a pager that genuinely runs out is NORMAL and must
    not cry wolf, or the warning above becomes noise people learn to ignore."""
    r = _recipe(type="click", next_selector="a.next", max_pages=10)
    stats = {}
    with caplog.at_level("WARNING", logger="leaderspeech.text_scraper.paginate"):
        links = paginate.harvest_links(r, FakeJsFetcher(FakePage(pages=3)), stats=stats)

    assert links == ["https://example.org/s/1", "https://example.org/s/2",
                     "https://example.org/s/3"]
    assert stats["stopped_early"] is False
    assert stats["stop_reason"] == "no_next_button"
    assert caplog.text == ""


def test_query_param_pager_ignored_by_site_is_flagged(caplog):
    """A listing that serves page 1 forever looks identical to a 1-page archive: same
    links, zero errors. Detect it by 'served links, but none new'."""

    class IgnoresPageParam:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            return '<a href="/s/1">always the same item</a>'

    r = _recipe(type="query_param", param="page", start=1, step=1, max_pages=10)
    f = IgnoresPageParam()
    stats = {}
    with caplog.at_level("WARNING", logger="leaderspeech.text_scraper.paginate"):
        links = paginate.harvest_links(r, f, stats=stats)

    assert links == ["https://example.org/s/1"]
    assert len(f.urls) == 2                # stopped once page 2 repeated page 1
    assert stats["stopped_early"] is True
    assert stats["stop_reason"] == "no_new_links"
    assert "ignoring the 'page' pager" in caplog.text


def test_query_param_empty_page_ends_normally(caplog):
    """Running off the end of the results (a page with no links at all) is the normal
    terminator and stays quiet."""

    class TwoPages:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            n = len(self.urls)
            return f'<a href="/s/{n}">item</a>' if n <= 2 else "<p>no results</p>"

    r = _recipe(type="query_param", param="page", start=1, step=1, max_pages=10)
    stats = {}
    with caplog.at_level("WARNING", logger="leaderspeech.text_scraper.paginate"):
        links = paginate.harvest_links(r, TwoPages(), stats=stats)

    assert links == ["https://example.org/s/1", "https://example.org/s/2"]
    assert stats["stopped_early"] is False
    assert stats["stop_reason"] == "empty_page"
    assert caplog.text == ""


def test_listing_fetch_failure_flags_stopped_early():
    """A listing page that won't load truncates the crawl — that is not a clean finish."""

    class Breaks:
        def __init__(self):
            self.urls = []

        def get(self, url):
            self.urls.append(url)
            if len(self.urls) > 1:
                raise RuntimeError("503")
            return '<a href="/s/1">item</a>'

    r = _recipe(type="query_param", param="page", start=1, step=1, max_pages=10)
    stats = {}
    paginate.harvest_links(r, Breaks(), stats=stats)
    assert stats["stopped_early"] is True
    assert stats["stop_reason"] == "listing_fetch_failed"


def test_next_link_exhausted_chain_ends_normally():
    r = _recipe(type="next_link", next_selector="a[data-nextlink]", max_pages=10)
    stats = {}
    paginate.harvest_links(r, NextLinkFetcher(pages=3), stats=stats)
    assert stats["stopped_early"] is False
    assert stats["stop_reason"] == "no_next_link"


def test_harvest_stats_are_optional():
    """Callers that don't pass `stats` (and every existing test above) are unaffected."""
    assert paginate.harvest_links(_recipe(type="none"), RecordingFetcher()) == [
        "https://example.org/s/1"
    ]


def test_none_type_fetches_every_start_url_as_a_listing():
    """The counterpart to url_list: several *listing* pages go in start_urls."""
    r = Recipe(
        source_id="x", country="Austria",
        start_urls=["https://example.org/p1", "https://example.org/p2"],
        listing={"link_selector": "a", "link_pattern": "/s/"},
        title={"selectors": ["h1"]}, text={"selectors": ["article"]},
        date={"selectors": [".date"]},
        pagination={"type": "none"},
    )
    f = RecordingFetcher()
    links = paginate.harvest_links(r, f)
    assert f.urls == ["https://example.org/p1", "https://example.org/p2"]
    assert links == ["https://example.org/s/1", "https://example.org/s/2"]


# --- issue #56: <base href> resolution --------------------------------------------------
# Government Site Builder (bundespraesident.de + a family of German government sites) ships
# <base href> on every page while serving hrefs with no leading slash, so resolving against
# the page URL sent every link to a soft-404 that returns HTTP 200 with a full layout.

from leaderspeech.text_scraper.recipe import Listing  # noqa: E402


def test_extract_links_honours_base_href():
    html = (
        '<html><head><base href="https://x.de/"/></head><body>'
        '<a href="SharedDocs/Reden/DE/a.html">a</a>'      # relative, no leading slash
        '</body></html>'
    )
    links = paginate.extract_links(html, "https://x.de/listing/reden_node.html",
                                   Listing(link_selector="a"))
    # resolved against <base>, NOT against the /listing/ page URL
    assert links == ["https://x.de/SharedDocs/Reden/DE/a.html"]


def test_extract_links_without_base_is_unchanged():
    html = '<a href="a/b.html">a</a>'
    links = paginate.extract_links(html, "https://x.de/listing/", Listing(link_selector="a"))
    assert links == ["https://x.de/listing/a/b.html"]


def test_extract_links_resolves_a_relative_base():
    # <base href> may itself be relative; it resolves against the page URL first.
    html = '<head><base href="../"/></head><a href="a.html">a</a>'
    links = paginate.extract_links(html, "https://x.de/one/two/list.html",
                                   Listing(link_selector="a"))
    assert links == ["https://x.de/one/a.html"]


def test_next_href_honours_base_href():
    """The pager has the same bug: without honouring <base> it walks the crawl off the
    site after page 1, even if extract_links resolves the speech links correctly."""
    html = ('<head><base href="https://x.de/"/></head>'
            '<a class="next" href="reden_node.html?gtp=2">next</a>')
    assert paginate._next_href(html, "https://x.de/listing/reden_node.html", "a.next") == \
        "https://x.de/reden_node.html?gtp=2"


# --- issue #55: carry the listing's date/title onto the row -----------------------------
# Trimmed from the real pmo.gov.et markup, and it must reproduce the two things that make
# the design non-trivial: the date sits in a SIBLING column of the link (no ancestor walk
# from the <a> reaches it), and <h1 class="heading"> appears both page-wide (the "More on
# News" banner) and once per item.

ETH_LISTING = """
<html><body>
  <h1 class="heading">More on News</h1>
  <div class="row content-display">
    <div class="col-md-4">
      <div class="col-md-12 meta-data"><p>Oct. 6, 2023 <i class="icon"></i></p><p></p></div>
    </div>
    <div class="col-md-8 content-body">
      <h1 class="heading">Erecha</h1>
      <div class="text"><a href="/media/documents/Erecha.pdf">Download here</a></div>
    </div>
  </div>
  <div class="row content-display">
    <div class="col-md-4">
      <div class="col-md-12 meta-data"><p>May 14, 2018 <i class="icon"></i></p><p></p></div>
    </div>
    <div class="col-md-8 content-body">
      <h1 class="heading">Inaugural</h1>
      <div class="text"><a href="/media/documents/Inaugural.pdf">Download here</a></div>
    </div>
  </div>
</body></html>
"""

ETH_LISTING_CONF = Listing(
    link_pattern=r"/media/documents/.*\.pdf",
    item_selector="div.row.content-display",
    item_date={"selectors": ["div.meta-data p"]},
)

# Same shape, but a permissive pattern for the small synthetic-URL cases below.
ITEM_ANY_PDF = Listing(
    link_pattern=r"\.pdf",
    item_selector="div.row.content-display",
    item_date={"selectors": ["div.meta-data p"]},
)


def test_listing_item_metadata_is_collected_beside_the_links():
    meta = {}
    links = paginate.extract_links(ETH_LISTING, "https://pmo.gov.et/speeches/",
                                   ETH_LISTING_CONF, meta, ["am", "en"])
    assert links == [
        "https://pmo.gov.et/media/documents/Erecha.pdf",
        "https://pmo.gov.et/media/documents/Inaugural.pdf",
    ]
    assert meta["https://pmo.gov.et/media/documents/Erecha.pdf"]["date"] == "2023-10-06"
    assert meta["https://pmo.gov.et/media/documents/Inaugural.pdf"]["date"] == "2018-05-14"


def test_item_scoping_beats_a_page_wide_selector():
    """The date is in a sibling column, and h1.heading is page-wide — only naming the item
    block reads the right one. An ancestor walk from the <a> would miss the date entirely."""
    conf = Listing(
        link_pattern=r"\.pdf",
        item_selector="div.row.content-display",
        item_title={"selectors": ["h1.heading"]},
        item_date={"selectors": ["div.meta-data p"]},
    )
    meta = {}
    paginate.extract_links(ETH_LISTING, "https://pmo.gov.et/speeches/", conf, meta, ["en"])
    titles = [m["title"] for m in meta.values()]
    assert titles == ["Erecha", "Inaugural"]     # not "More on News"


def test_listing_meta_never_carries_text():
    meta = {}
    paginate.extract_links(ETH_LISTING, "https://pmo.gov.et/speeches/",
                           ETH_LISTING_CONF, meta, ["en"])
    assert meta                                   # something WAS collected
    assert all("text" not in m for m in meta.values())


def test_harvest_is_unchanged_without_a_meta_dict():
    """No meta arg, or item_selector set but meta not requested: identical link list, and
    no crash — the feature is strictly additive."""
    links_a = paginate.extract_links(ETH_LISTING, "https://pmo.gov.et/speeches/",
                                     Listing(link_pattern=r"\.pdf"))
    links_b = paginate.extract_links(ETH_LISTING, "https://pmo.gov.et/speeches/",
                                     ETH_LISTING_CONF)   # item_selector set, no meta dict
    assert links_a == links_b


def test_a_link_outside_every_item_block_still_harvests_undated():
    html = ('<div class="row content-display">'
            '<div class="meta-data"><p>May 14, 2018</p></div>'
            '<a href="/a.pdf">in</a></div>'
            '<a href="/loose.pdf">out</a>')       # not inside any item block
    meta = {}
    links = paginate.extract_links(html, "https://x/", ITEM_ANY_PDF, meta, ["en"])
    assert links == ["https://x/a.pdf", "https://x/loose.pdf"]   # BOTH harvested
    assert "https://x/a.pdf" in meta
    assert "https://x/loose.pdf" not in meta                     # just no date


def test_item_selector_that_matches_nothing_loses_dates_not_links():
    conf = Listing(link_pattern=r"\.pdf", item_selector="div.no-such-class",
                   item_date={"selectors": ["p"]})
    meta = {}
    links = paginate.extract_links(ETH_LISTING, "https://pmo.gov.et/speeches/",
                                   conf, meta, ["en"])
    assert len(links) == 2
    assert meta == {}


def test_first_occurrence_wins_when_a_url_repeats():
    html = ('<div class="row content-display"><div class="meta-data"><p>May 14, 2018</p></div>'
            '<a href="/a.pdf">first</a></div>'
            '<div class="row content-display"><div class="meta-data"><p>Oct. 6, 2023</p></div>'
            '<a href="/a.pdf">dup</a></div>')
    meta = {}
    links = paginate.extract_links(html, "https://x/", ITEM_ANY_PDF, meta, ["en"])
    assert links == ["https://x/a.pdf"]
    assert meta["https://x/a.pdf"]["date"] == "2018-05-14"   # the first block's date


# --- issue #63: gzipped (.gz) sitemaps ---------------------------------------------------
# Many government sitemaps are `*.xml.gz` served as application/gzip (NOT
# Content-Encoding: gzip), so httpx never decompresses them and the old `fetcher.get`
# (decoded text) path found 0 <loc>. The engine now fetches sitemap BYTES and gunzips
# when the URL ends in .gz or the payload carries the gzip magic. (Sweden's Royal Court:
# /sitemapindex.xml -> /sitemap1.xml.gz with 2611 /arkiv/tal/ speech URLs.)

_SITEMAP_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    '<url><loc>https://x.se/arkiv/tal/2020-01-02-a</loc></url>'
    '<url><loc>https://x.se/press/2020-01-03-note</loc></url>'   # filtered out by pattern
    '<url><loc>https://x.se/arkiv/tal/2019-06-07-b</loc></url>'
    '</urlset>'
)


def _sitemap_recipe(sitemap_urls):
    return Recipe(
        source_id="swe", country="Sweden",
        start_urls=["https://x.se/"],
        listing={"link_pattern": r"/arkiv/tal/\d{4}-\d{2}-\d{2}-"},
        title={"selectors": ["h1"]}, text={"selectors": ["article"]},
        date={"selectors": [".date"]},
        pagination={"type": "sitemap", "sitemap_urls": sitemap_urls},
    )


class SitemapBytesFetcher:
    """Serves sitemap payloads as raw BYTES (like the real Fetcher.get_bytes), keyed by
    URL. Values may be plain or gzip-compressed bytes."""

    def __init__(self, payloads: dict):
        self.payloads = payloads
        self.urls = []

    def get_bytes(self, url):
        self.urls.append(url)
        return "application/octet-stream", self.payloads[url]


def test_sitemap_plain_xml_is_unchanged():
    f = SitemapBytesFetcher({"https://x.se/sitemap.xml": _SITEMAP_XML.encode("utf-8")})
    r = _sitemap_recipe(["https://x.se/sitemap.xml"])
    links = paginate.harvest_links(r, f)
    assert links == ["https://x.se/arkiv/tal/2020-01-02-a",
                     "https://x.se/arkiv/tal/2019-06-07-b"]


def test_sitemap_gzip_by_url_suffix_is_decompressed():
    gz = gzip.compress(_SITEMAP_XML.encode("utf-8"))
    f = SitemapBytesFetcher({"https://x.se/sitemap1.xml.gz": gz})
    r = _sitemap_recipe(["https://x.se/sitemap1.xml.gz"])
    links = paginate.harvest_links(r, f)
    assert links == ["https://x.se/arkiv/tal/2020-01-02-a",
                     "https://x.se/arkiv/tal/2019-06-07-b"]


def test_sitemap_gzip_detected_by_magic_without_gz_suffix():
    # served gzip at a plain .xml URL — caught by the 0x1f 0x8b magic, not the suffix.
    gz = gzip.compress(_SITEMAP_XML.encode("utf-8"))
    f = SitemapBytesFetcher({"https://x.se/sitemap.xml": gz})
    r = _sitemap_recipe(["https://x.se/sitemap.xml"])
    links = paginate.harvest_links(r, f)
    assert links == ["https://x.se/arkiv/tal/2020-01-02-a",
                     "https://x.se/arkiv/tal/2019-06-07-b"]


def test_sitemap_index_followed_into_gzipped_children():
    # The Sweden shape: an .xml index whose children are all .gz.
    index_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        '<sitemap><loc>https://x.se/sitemap1.xml.gz</loc></sitemap>'
        '</sitemapindex>'
    )
    f = SitemapBytesFetcher({
        "https://x.se/sitemapindex.xml": index_xml.encode("utf-8"),
        "https://x.se/sitemap1.xml.gz": gzip.compress(_SITEMAP_XML.encode("utf-8")),
    })
    r = _sitemap_recipe(["https://x.se/sitemapindex.xml"])
    links = paginate.harvest_links(r, f)
    assert links == ["https://x.se/arkiv/tal/2020-01-02-a",
                     "https://x.se/arkiv/tal/2019-06-07-b"]
    assert "https://x.se/sitemap1.xml.gz" in f.urls   # the child WAS opened


def test_next_link_pagination_threads_meta():
    """One of the two indirect branches (click is the other): meta must reach through it."""

    class OnePage:
        def get(self, url):
            return ('<div class="row content-display">'
                    '<div class="meta-data"><p>Oct. 6, 2023</p></div>'
                    '<a href="/media/documents/x.pdf">dl</a></div>')

    r = Recipe(
        source_id="eth", country="Ethiopia", date_languages=["am", "en"],
        start_urls=["https://pmo.gov.et/speeches/"],
        listing=ETH_LISTING_CONF,
        title={}, text={}, date={}, content_type="pdf",
        pagination={"type": "next_link", "next_selector": "a.nope", "max_pages": 1},
    )
    meta = {}
    links = paginate.harvest_links(r, OnePage(), meta=meta)
    assert links == ["https://pmo.gov.et/media/documents/x.pdf"]
    assert meta[links[0]]["date"] == "2023-10-06"
