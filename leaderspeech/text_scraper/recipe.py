"""Recipe schema: the declarative description of a single source/site.

The whole point of the engine is that all per-site variation lives here, as
data, instead of being hardcoded across one-off scripts. A recipe says where the
listing pages are, how to page through them, how to find speech links, and which
selectors (with fallbacks) pull each field out of a speech page.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, model_validator

try:  # used to auto-fill the numeric ISO code; optional at import time
    import pycountry
except Exception:  # pragma: no cover
    pycountry = None


class Renderer(str, Enum):
    static = "static"   # plain HTML over HTTP (httpx)
    js = "js"           # JavaScript-rendered (Playwright)


class PaginationType(str, Enum):
    query_param = "query_param"   # ?start=40 / ?page=2 style
    path = "path"                 # /discursos/2 style
    click = "click"               # click a "next" button (JS sites)
    url_list = "url_list"         # an explicit, pre-known list of pages
    sitemap = "sitemap"           # enumerate all URLs from the site's sitemap(s)
    none = "none"                 # a single listing page, no pagination


class Listing(BaseModel):
    """How to harvest speech links from a listing/index page."""

    link_selector: Optional[str] = None   # CSS selector for the <a> elements
    link_pattern: Optional[str] = None     # regex an href must match to qualify

    @model_validator(mode="after")
    def _need_one(self):
        if not self.link_selector and not self.link_pattern:
            raise ValueError("listing needs link_selector and/or link_pattern")
        return self


class Pagination(BaseModel):
    type: PaginationType = PaginationType.none
    param: Optional[str] = None            # query param name (query_param type)
    start: int = 0                         # first page index/offset
    step: int = 1                          # increment between pages
    max_pages: Optional[int] = None        # safety cap; None => stop on empty page
    next_selector: Optional[str] = None    # "next" button selector (click type)
    url_list: Optional[list[str]] = None   # explicit listing URLs (url_list type)
    sitemap_urls: Optional[list[str]] = None  # sitemap.xml URLs (sitemap type); a
    # sitemap index is followed into its children. URLs are kept if they match
    # listing.link_pattern.


class FieldSpec(BaseModel):
    """An ordered fallback chain of selectors for one field.

    Selectors are tried in order; the first that matches wins. This mirrors the
    "try primary, else secondary" pattern in the existing R scrapers.
    """

    selectors: list[str] = Field(default_factory=list)
    attr: Optional[str] = None    # read this attribute instead of the text
    regex: Optional[str] = None   # optional regex to pull a substring out


class Politeness(BaseModel):
    # Light by default: these are small requests for public speeches on public sites.
    # No per-request wait; just a short breather every `pause_every` requests. Bump
    # delay_range / pause_seconds (or set them in a recipe) for a touchy server.
    delay_range: tuple[float, float] = (0.0, 0.0)  # optional per-request jitter
    pause_every: int = 50          # take a breather every N requests (0 = never)
    pause_seconds: float = 5.0     # how long that breather is
    retries: int = 3
    backoff: float = 5.0           # base seconds; grows exponentially per retry


class Recipe(BaseModel):
    # identity / provenance
    source_id: str                          # short slug, links recipe <-> outputs
    country: str
    iso3n: Optional[int] = None             # auto-filled from country if omitted
    source_language: str = "English"
    dataset: str = "LeaderSpeech"           # provenance tag for newly scraped rows

    # where + how to crawl
    start_urls: list[str]
    renderer: Renderer = Renderer.static
    listing: Listing
    pagination: Pagination = Field(default_factory=Pagination)

    # per-speech field extraction (title/text/date required; rest optional)
    title: FieldSpec
    text: FieldSpec
    date: FieldSpec
    speaker: Optional[FieldSpec] = None
    context: Optional[FieldSpec] = None

    # fixed values when a source is single-leader / single-office
    position: Optional[str] = None
    speaker_default: Optional[str] = None

    date_languages: list[str] = Field(default_factory=list)  # hints for dateparser
    politeness: Politeness = Field(default_factory=Politeness)
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _checks(self):
        for name in ("title", "text", "date"):
            fs: FieldSpec = getattr(self, name)
            if not fs.selectors:
                raise ValueError(f"field '{name}' needs at least one selector")
        if self.pagination.type == PaginationType.query_param and not self.pagination.param:
            raise ValueError("query_param pagination needs 'param'")
        if self.pagination.type == PaginationType.click and not self.pagination.next_selector:
            raise ValueError("click pagination needs 'next_selector'")
        if self.pagination.type == PaginationType.url_list and not self.pagination.url_list:
            raise ValueError("url_list pagination needs 'url_list'")
        if self.pagination.type == PaginationType.sitemap and not self.pagination.sitemap_urls:
            raise ValueError("sitemap pagination needs 'sitemap_urls'")
        # auto-fill numeric ISO code
        if self.iso3n is None and pycountry is not None:
            try:
                self.iso3n = int(pycountry.countries.lookup(self.country).numeric)
            except Exception:
                pass
        return self


def load_recipe(path: str | Path) -> Recipe:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Recipe(**data)
