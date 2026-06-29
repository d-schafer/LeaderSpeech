"""Pagination URL construction — especially `path_format`, which lets a `path`
pager target non-numeric page URLs (e.g. president.ie's /P0, /P20, /P40)."""

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
