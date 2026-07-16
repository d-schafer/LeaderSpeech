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
