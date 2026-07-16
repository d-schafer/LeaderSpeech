"""Pagination URL construction — especially `path_format`, which lets a `path`
page target non-numeric URLs (e.g. president.ie's /P0, /P20, /P40)."""

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
