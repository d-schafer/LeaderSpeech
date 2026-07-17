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
from pydantic import BaseModel, Field, field_validator, model_validator

try:  # used to auto-fill the numeric ISO code; optional at import time
    import pycountry
except Exception:  # pragma: no cover
    pycountry = None


class Renderer(str, Enum):
    static = "static"   # plain HTML over HTTP (httpx)
    js = "js"           # JavaScript-rendered (Playwright)


class ContentType(str, Enum):
    """Whether a speech page is HTML or a PDF.

    Default ``auto`` keeps the classic behavior: pages are HTML, and a harvested URL is
    only treated as a PDF if it *looks* like one (``.pdf`` / ``@@download``, or a real
    ``application/pdf`` response). ``pdf`` forces every harvested URL through the PDF
    text-extractor (for sources whose PDF URLs carry no ``.pdf`` hint); ``html`` pins the
    HTML path even for ``.pdf`` URLs (rare — a viewer page). See docs/recipes.md.
    """

    auto = "auto"
    html = "html"
    pdf = "pdf"


class PaginationType(str, Enum):
    query_param = "query_param"   # ?start=40 / ?page=2 style
    path = "path"                 # /discursos/2 style
    click = "click"               # click a "next" button (JS sites)
    next_link = "next_link"       # follow the listing's own "next" <a href> (static sites
                                  # whose page URL can't be synthesised: signed/opaque
                                  # tokens like TYPO3's cHash)
    url_list = "url_list"         # an explicit, pre-known list of SPEECH-page URLs, used
                                  # as-is (NOT listing pages -- see harvest_links)
    sitemap = "sitemap"           # enumerate all URLs from the site's sitemap(s)
    wayback = "wayback"           # enumerate archived captures from the Wayback CDX API
    api = "api"                   # enumerate from a JSON/search API (e.g. SharePoint _api/search)
    feed = "feed"                 # enumerate from an RSS/Atom feed
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


class KeepIf(BaseModel):
    """Keep a fetched page only if the page itself says it belongs to this source.

    `listing.link_pattern` filters by URL and is free (no fetch), so it stays the first
    choice. But plenty of sites categorise content **on the page** and not in the URL —
    Thailand's `thaigov.go.th/news/contents/details/<id>`, Bangladesh's
    `bssnews.net/news/<id>`, Azerbaijan's `president.az/az/articles/view/<id>` all have a
    bare numeric permalink shared by every ministry press release on the site. For those,
    a URL regex cannot express "PM speeches only" at all, and the archive is only
    reachable with a predicate over the fetched page.

    Two modes:
      * `selectors` + `pattern` — join the text of every matching element (a breadcrumb,
        a category chip, a nav crumb) and test `pattern` against it. This is the usual
        shape; list several selectors as alternatives.
      * `pattern` alone — test the WHOLE document's text (a PDF's extracted text when
        there is no DOM). Blunter; use when a category element doesn't exist.
      * `selectors` alone — keep pages where any of them is present at all.

    `negate: true` inverts the verdict (drop on match). Cost: one wasted fetch per
    rejected page — bandwidth, not money, and far cheaper than letting the cleaner spend
    a per-speech GPT call to reject the same row. A mis-specified `keep_if` can silently
    empty a source, so `run`/`probe` report a filtered-out count.
    """

    selectors: list[str] = Field(default_factory=list)  # CSS elements whose text is tested
    pattern: Optional[str] = None    # regex; prefix with (?i) for case-insensitive
    negate: bool = False             # invert: DROP the page when it matches

    @model_validator(mode="after")
    def _need_one(self):
        if not self.selectors and not self.pattern:
            raise ValueError("keep_if needs 'selectors' and/or 'pattern'")
        return self


class ApiConfig(BaseModel):
    """How to pull speech links + metadata from a JSON/search API (type='api').

    The exemplar is a SharePoint "search web-part" page whose visible HTML is only
    chrome: the speech list is fetched client-side from `…/_api/search/query`. Point
    `start_urls[0]` at that JSON endpoint (with its `querytext`/`rowlimit` already in
    the query string) and paginate it with the shared `pagination.param`/`start`/
    `step`/`max_pages` knobs (e.g. `param: startRow`, `step: 50`). Field paths are
    dotted (`a.b.c`); SharePoint's Key/Value `Cells` arrays are handled via cells mode.
    """

    # Dotted path to the array of result rows — or "." when the response IS the array
    # (a bare JSON list at the root, e.g. WordPress's /wp-json/wp/v2/posts).
    results_path: str
    url_field: str                          # row path (or cell Key) for the speech URL
    title_field: Optional[str] = None       # row path (or cell Key) for the title
    date_field: Optional[str] = None        # row path (or cell Key) for the date
    text_field: Optional[str] = None        # row path (or cell Key) if the JSON carries full text
    speaker_field: Optional[str] = None     # row path (or cell Key) for the speaker
    # Dotted field paths above also support list indices (`a.b[0].c`) and quoted keys
    # containing spaces/dots (`tags.metaData."Publish Date"[0].title`); plain `a.b.c`
    # behaves exactly as before.
    # SharePoint "cells" mode: each row's fields live in a list of {Key, Value} dicts.
    # When cells_path is set, the *_field names above are matched against cell keys.
    cells_path: Optional[str] = None        # dotted path within a row to the cells list
    cell_key: str = "Key"                   # attribute naming a cell's field name
    cell_value: str = "Value"               # attribute naming a cell's field value
    headers: dict[str, str] = Field(default_factory=dict)  # per-request header overrides
    delay: float = 0.0                      # courtesy pause between API page requests
    # HTTP method. Default GET (today's behavior). Set POST for endpoints whose listing
    # is a POST JSON call (SPA/SharePoint CSOM, e.g. president.kg /api/v1/news/search).
    method: str = "GET"                     # "GET" (default) | "POST"
    body: Optional[dict] = None             # JSON body sent on each POST request
    # When set (POST only), the per-page offset (start + page_idx*step) is written into
    # `body` at this dotted path each page; otherwise the source pages by query `param`
    # as usual (a POST can still page by query param). Supports the same list-index /
    # quoted-key dotted syntax as the *_field paths.
    body_page_field: Optional[str] = None
    # Base URL to resolve (urljoin) row URLs against. Defaults to start_urls[0]. Set it
    # when the JSON host != the site host, so relative row links (e.g. /en/pages/<slug>)
    # resolve to the site — not the API endpoint's host (gov.il is the exemplar).
    url_base: Optional[str] = None


class FeedConfig(BaseModel):
    """How to read an RSS/Atom feed (type='feed'). A lighter-weight sibling of `api`
    for sources that publish a feed. `start_urls` are the feed URL(s)."""

    format: str = "auto"        # "auto" | "rss" | "atom"
    use_content: bool = True    # populate text from the feed body (false => fetch the page)


class Pagination(BaseModel):
    type: PaginationType = PaginationType.none
    param: Optional[str] = None            # query param name (query_param/api/feed types)
    start: int = 0                         # first page index/offset
    step: int = 1                          # increment between pages
    path_format: Optional[str] = None      # Only used when type='path'; suffix template with a `{n}` placeholder.
    max_pages: Optional[int] = None        # safety cap; None => stop on empty page
    next_selector: Optional[str] = None    # "next" control selector (click + next_link types)
    url_list: Optional[list[str]] = None   # explicit SPEECH-page URLs (url_list type);
    # returned verbatim as the scrape targets -- they are NOT fetched as listings and
    # listing.link_pattern is not applied to them. To enumerate several *listing* pages,
    # put them all in start_urls with pagination.type = none.
    sitemap_urls: Optional[list[str]] = None  # sitemap.xml URLs (sitemap type); a
    # sitemap index is followed into its children. URLs are kept if they match
    # listing.link_pattern.
    wayback_limit: Optional[int] = None    # cap archived captures listed per query
    wayback_match_type: str = "prefix"     # CDX `matchType`
    wayback_collapse: str = "urlkey"       # CDX `collapse`
    wayback_delay: float = 5.0             # seconds to wait before each archived fetch
    wayback_from: Optional[str] = None     # CDX `from` (YYYYMMDD)
    wayback_to: Optional[str] = None       # CDX `to` (YYYYMMDD)
    # Extra CDX `filter=` expressions (field:regex), ANDed. e.g.
    # ["mimetype:application/pdf", "statuscode:200"] to keep only real PDF captures and
    # drop the text/html listing/redirect noise a prefix query returns. None => no filter.
    wayback_filter: Optional[list[str]] = None
    api: Optional[ApiConfig] = None        # JSON/search-API config (api type)
    feed: Optional[FeedConfig] = None      # RSS/Atom config (feed type)


class FieldSpec(BaseModel):
    """An ordered fallback chain of selectors for one field.

    Selectors are tried in order; the first that matches wins. This mirrors the
    "try primary, else secondary" pattern in the existing R scrapers.
    """

    selectors: list[str] = Field(default_factory=list)
    attr: Optional[str] = None    # read this attribute instead of the text
    regex: Optional[str] = None   # optional regex to pull a substring out
    # Extract this field from the page URL when no selector matches (or when there is no
    # DOM at all — PDFs). Applied to the speech URL; the whole match is used, or group(1)
    # if the regex captures. For dates, named groups (?P<year>)/(?P<month>)/(?P<day>) are
    # assembled into an ISO date (handy for /YYYY/DD-MM-... archive paths). See docs.
    url_regex: Optional[str] = None


class WaybackExtend(BaseModel):
    """Opt-in: after a LIVE recipe's crawl finishes, automatically continue into the
    Internet Archive to reach speeches older than the live site covers — without
    hand-writing a separate `<id>_wayback.yml`.

    Every field defaults to reusing the live recipe, so `wayback_extend: true` alone is
    enough. The engine computes the earliest date already scraped for the source and
    bounds the archive harvest with `wayback_to = that date` (so live+archive don't
    overlap and `doc_id` continuity holds); dedupe by URL drops any capture already
    scraped live.

    IMPORTANT: this reuses the live site's SAME host+prefix. Sources that relocated old
    content to a *different* domain (e.g. US NARA `*whitehouse.archives.gov`, Korea
    `webarchives.pa.go.kr`) are NOT reached by this — author a dedicated archive recipe.
    """

    enabled: bool = True
    # CDX prefix to enumerate; default = derived from start_urls[0] (host+path, no scheme).
    # Set this when speeches don't live under the listing path (e.g. listing is /news/ but
    # speeches are /remarks/...), so the archive harvest points at the right prefix.
    prefix: Optional[str] = None
    link_pattern: Optional[str] = None    # default = listing.link_pattern
    # selector overrides for the (often differently-structured) archived pages; each
    # defaults to reusing the live recipe's selector chain. The generic text fallback
    # still applies automatically for drifted old layouts.
    title: Optional[FieldSpec] = None
    text: Optional[FieldSpec] = None
    date: Optional[FieldSpec] = None
    speaker: Optional[FieldSpec] = None
    context: Optional[FieldSpec] = None
    # archive pacing / bounds (mirror the `wayback` pagination knobs)
    wayback_from: Optional[str] = None    # CDX `from` (YYYYMMDD)
    wayback_to: Optional[str] = None      # explicit CDX `to`; overrides the auto earliest-date floor
    wayback_delay: float = 5.0            # seconds before each archived fetch
    wayback_limit: Optional[int] = None   # cap captures listed per query
    wayback_match_type: str = "prefix"    # CDX `matchType`
    wayback_collapse: str = "urlkey"      # CDX `collapse`
    wayback_filter: Optional[list[str]] = None  # extra CDX `filter=` expressions (see Pagination)


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
    # HTML (default) or PDF speech pages. `auto` treats a page as HTML unless the URL/
    # response says PDF; `pdf` forces the PDF text-extractor for every harvested URL.
    content_type: ContentType = ContentType.auto
    verify_ssl: bool = True       # set false for sites with a broken/incomplete cert chain
    user_agent: Optional[str] = None   # override the default bot UA for a WAF that hard-blocks it
    listing: Listing
    # Optional predicate over the FETCHED page, for sites whose category lives on the page
    # rather than in the URL (see KeepIf). Default off; applies to every source type.
    keep_if: Optional[KeepIf] = None
    pagination: Pagination = Field(default_factory=Pagination)
    # Opt-in continuation into the Wayback CDX after the live crawl (see WaybackExtend).
    # Accepts `true` (reuse everything) or a mapping of overrides; `false`/absent = off.
    wayback_extend: Optional[WaybackExtend] = None

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

    @field_validator("wayback_extend", mode="before")
    @classmethod
    def _coerce_wayback_extend(cls, v):
        # Accept the ergonomic `wayback_extend: true` (reuse everything) and a mapping of
        # overrides alike; `false`/absent stays off. A dict is enabled unless it says otherwise.
        if v is None or v is False:
            return None
        if v is True:
            return {"enabled": True}
        if isinstance(v, dict):
            return {"enabled": True, **v}
        return v

    @model_validator(mode="after")
    def _checks(self):
        # A field is satisfied by a selector chain OR a url_regex. PDF recipes have no DOM,
        # so the body `text` always comes from the PDF itself (no selector required); a PDF
        # source may still pull title/date off the URL via url_regex, but need not.
        is_pdf = self.content_type == ContentType.pdf
        for name in ("title", "text", "date"):
            fs: FieldSpec = getattr(self, name)
            if fs.selectors or fs.url_regex:
                continue
            if is_pdf:
                continue  # PDF: text from the body; title/date optional (url_regex or none)
            raise ValueError(f"field '{name}' needs at least one selector or a url_regex")
        if self.pagination.type == PaginationType.query_param and not self.pagination.param:
            raise ValueError("query_param pagination needs 'param'")
        if self.pagination.type == PaginationType.click and not self.pagination.next_selector:
            raise ValueError("click pagination needs 'next_selector'")
        if self.pagination.type == PaginationType.next_link and not self.pagination.next_selector:
            raise ValueError("next_link pagination needs 'next_selector'")
        if self.pagination.type == PaginationType.url_list and not self.pagination.url_list:
            raise ValueError("url_list pagination needs 'url_list'")
        if self.pagination.path_format:
            try:
                substituted = self.pagination.path_format.format(n=0)
            except (KeyError, ValueError):
                raise ValueError("pagination.path_format is not a valid format string; "
                                 "use a '{n}' page-index placeholder, e.g. 'P{n}' or '{n:03d}'")
            if substituted == self.pagination.path_format:
                raise ValueError("pagination.path_format must contain the '{n}' page-index placeholder")
        if self.pagination.type == PaginationType.sitemap and not self.pagination.sitemap_urls:
            raise ValueError("sitemap pagination needs 'sitemap_urls'")
        if self.pagination.type == PaginationType.wayback and not self.start_urls:
            raise ValueError("wayback pagination needs start_urls with CDX prefixes")
        if self.pagination.type == PaginationType.api:
            if not self.pagination.api:
                raise ValueError("api pagination needs a 'pagination.api' block")
            if not self.pagination.api.results_path or not self.pagination.api.url_field:
                raise ValueError("api pagination needs 'api.results_path' and 'api.url_field'")
            if (self.pagination.api.method or "GET").upper() not in ("GET", "POST"):
                raise ValueError("api.method must be 'GET' or 'POST'")
        if self.pagination.type == PaginationType.feed and not self.start_urls:
            raise ValueError("feed pagination needs start_urls with the feed URL(s)")
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
