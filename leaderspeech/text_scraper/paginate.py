"""Pagination + link harvesting.

`harvest_links` walks a source's listing pages (however that source paginates)
and returns the de-duplicated list of speech-page URLs to scrape. The strategies
seen across the old scrapers are unified behind it: query-param offsets, path
segments, JS "next" clicks, following a static "next" link, an explicit URL list,
or a single page.

Note the difference between the two "explicit" cases:
  * `url_list` is a list of **speech** URLs -- returned verbatim as the scrape
    targets, never fetched as listings.
  * several **listing** pages go in `start_urls` with `type = none`, which fetches
    each one and extracts links from it.
"""

from __future__ import annotations

import gzip
import logging
import re
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from .extract import listing_meta
from .recipe import Listing, PaginationType, Recipe

log = logging.getLogger(__name__)


def _doc_base(soup: BeautifulSoup, base_url: str) -> str:
    """The document's base URL for resolving its relative links.

    Per the HTML spec a `<base href>` REPLACES the page URL as the resolution base for the
    whole document. Rare, but Government Site Builder — the CMS behind much of the German
    federal web — ships one on every page *and* serves hrefs with no leading slash
    (`SharedDocs/Reden/DE/...`). Resolving those against the page URL yielded a 404 that
    the site returns as **HTTP 200 with a full layout**, so nothing raised, the probe
    reported a healthy listing, and a run would have written rows of "page not found"
    chrome (issue #56).

    `<base href>` may itself be relative, so it resolves against the page URL first. With
    no `<base>` this returns `base_url` and nothing changes.
    """
    el = soup.find("base", href=True)
    if not el:
        return base_url
    href = (el.get("href") or "").strip()
    return urljoin(base_url, href) if href else base_url


def _item_index(soup: BeautifulSoup, item_selector: str) -> dict:
    """Map id(tag) -> item block. Keyed by IDENTITY, not equality: bs4 Tags compare by
    value, so two listing rows with identical markup would collapse into one."""
    return {id(el): el for el in soup.select(item_selector)}


def _owning_item(anchor, index: dict):
    """The nearest ancestor of `anchor` that is an item block, or None. Nearest, so nested
    blocks resolve to the tightest one; by lookup, so nothing depends on a counted depth."""
    for parent in anchor.parents:
        item = index.get(id(parent))
        if item is not None:
            return item
    return None


def extract_links(html: str, base_url: str, listing: Listing,
                  meta: dict | None = None,
                  date_languages: list[str] | None = None) -> list[str]:
    """Pull qualifying speech links off one listing page, order-preserving.

    `meta` is an optional caller-supplied dict, mutated in place — the same out-param shape
    as `stats` (issue #53). The return type stays `list[str]` deliberately: a `list[dict]`
    would break every caller and the dozen tests that assert on it, for no gain.

    When `listing.item_selector` is set, each qualifying link inside a block gets
    `meta[url] = {title?, date?, date_raw?, _from}` read from THAT block (issue #55). First
    occurrence wins, matching the harvest's own first-wins dedupe. The anchor loop itself
    is untouched, so metadata can only ever be *added* to links we already found — a
    mistyped item_selector costs dates, never links.
    """
    soup = BeautifulSoup(html, "lxml")
    doc_base = _doc_base(soup, base_url)
    anchors = soup.select(listing.link_selector) if listing.link_selector else soup.find_all("a")
    pattern = re.compile(listing.link_pattern) if listing.link_pattern else None
    items = (_item_index(soup, listing.item_selector)
             if meta is not None and listing.item_selector else {})

    out, seen = [], set()
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
        # some sites (e.g. gob.mx) wrap hrefs in escaped quotes: \"/path\"
        href = href.strip().strip("\\\"'").strip()
        if not href:
            continue
        full = urljoin(doc_base, href)
        if pattern and not pattern.search(full):
            continue
        if items and full not in meta:   # first occurrence wins; don't re-read a dupe
            item = _owning_item(a, items)
            if item is not None:
                found = listing_meta(item, listing, date_languages)
                if found:
                    meta[full] = found
        if full not in seen:
            seen.add(full)
            out.append(full)
    return out


def _with_query_param(url: str, param: str, value) -> str:
    parts = urlparse(url)
    query = parse_qs(parts.query)
    query[param] = [str(value)]
    return urlunparse(parts._replace(query=urlencode(query, doseq=True)))


# Why pagination stopped. `stopped_early=True` means the crawl was cut short by something
# that is probably a bug (a broken pager, an unreachable listing page) rather than by
# actually reaching the end -- so the harvest is likely INCOMPLETE even though nothing
# raised. Without this, "the archive is 10 items" and "we silently lost 99% of it" produce
# byte-identical output (see issue #53 / Austria).
NORMAL_STOPS = {"empty_page", "no_next_button", "no_next_link", "cyclic_pager",
                "max_pages", "max_links", "single_page"}
EARLY_STOPS = {"next_click_failed", "listing_fetch_failed", "no_new_links"}


def _note(stats: dict | None, reason: str, early: bool = False) -> None:
    """Record how pagination ended. `stats` is an optional caller-supplied dict (run.py
    surfaces it in the run summary; probe prints it). `stopped_early` is sticky across
    start_urls -- one truncated chain taints the harvest -- while `stop_reason` reports
    the last chain's."""
    if stats is None:
        return
    stats["stop_reason"] = reason
    if early:
        stats["stopped_early"] = True
    stats.setdefault("stopped_early", False)


def harvest_links(recipe: Recipe, fetcher, max_pages=None, max_links=None,
                  stats: dict | None = None, meta: dict | None = None) -> list[str]:
    """Every speech-page URL this source paginates to, de-duplicated.

    `stats` (how pagination ended) and `meta` (per-link listing metadata, issue #55) are
    optional caller-supplied dicts, mutated in place. `meta` is only ever filled by the
    branches that actually parse listing HTML: `url_list` is handed speech URLs directly
    and `sitemap` reads a list of bare <loc> URLs, so neither has any markup to read
    metadata from and both leave `meta` untouched.
    """
    pg = recipe.pagination

    if pg.type == PaginationType.url_list:
        # These are speech URLs, not listings: hand them back as the scrape targets.
        _note(stats, "single_page")
        return list(pg.url_list or [])
    if pg.type == PaginationType.sitemap:
        _note(stats, "single_page")
        return _harvest_sitemap(recipe, fetcher, max_links)
    if pg.type == PaginationType.click:
        return _harvest_click(recipe, fetcher, max_pages, max_links, stats, meta)
    if pg.type == PaginationType.next_link:
        return _harvest_next_link(recipe, fetcher, max_pages, max_links, stats, meta)

    collected, seen = [], set()

    def add(links):
        gained = 0
        for link in links:
            if link not in seen:
                seen.add(link)
                collected.append(link)
                gained += 1
        return gained

    hard_cap = max_pages if max_pages is not None else (pg.max_pages or 200)

    for start_url in recipe.start_urls:
        if pg.type == PaginationType.none:
            try:
                add(extract_links(fetcher.get(start_url), start_url, recipe.listing,
                                  meta, recipe.date_languages))
                _note(stats, "single_page")
            except Exception as e:
                log.warning("listing fetch failed: %s :: %s", start_url, e)
                _note(stats, "listing_fetch_failed", early=True)
            continue

        for page_idx in range(hard_cap):
            value = pg.start + page_idx * pg.step
            if pg.type == PaginationType.query_param:
                page_url = _with_query_param(start_url, pg.param, value)
            else:  # path
                # Unset path_format falls back to bare-number paths like /discursos/2.
                suffix = pg.path_format.format(n=value) if pg.path_format else str(value)
                page_url = start_url.rstrip("/") + "/" + suffix
            try:
                html = fetcher.get(page_url)
            except Exception as e:
                # one bad listing page shouldn't kill the whole crawl
                log.warning("listing page failed, stopping pagination here: %s :: %s", page_url, e)
                _note(stats, "listing_fetch_failed", early=True)
                break
            page_links = extract_links(html, page_url, recipe.listing,
                                       meta, recipe.date_languages)
            gained = add(page_links)
            if gained == 0:
                # Two very different endings that used to look identical: a page with no
                # links at all (we ran past the last page -- correct, stop), versus a page
                # that served links we have ALL seen before (the site is probably ignoring
                # the page parameter and re-serving page 1, so we're about to truncate the
                # archive to a single page and call it a success).
                if page_links:
                    log.warning(
                        "listing page %d served %d link(s) but NONE were new — the site may be "
                        "ignoring the '%s' pager and re-serving the same page. Pagination stopped "
                        "EARLY: this harvest is probably incomplete. Open %s in a browser and "
                        "check that the page parameter really advances.",
                        page_idx + 1, len(page_links),
                        pg.param if pg.type == PaginationType.query_param else "path", page_url)
                    _note(stats, "no_new_links", early=True)
                else:
                    log.info("listing page %d served no links — treating as the end of the "
                             "results (%d link(s) harvested)", page_idx + 1, len(collected))
                    _note(stats, "empty_page")
                break
            if (page_idx + 1) % 25 == 0:  # so a long harvest isn't a silent gap
                log.info("harvesting... %d listing pages, %d links so far",
                         page_idx + 1, len(collected))
            if max_links and len(collected) >= max_links:
                _note(stats, "max_links")
                break
        else:
            _note(stats, "max_pages")
        if max_links and len(collected) >= max_links:
            break

    return collected[:max_links] if max_links else collected


_GZIP_MAGIC = b"\x1f\x8b"


def _fetch_sitemap_xml(fetcher, sm_url: str) -> str:
    """Fetch one sitemap and return its XML as text, transparently gunzipping a gzipped
    sitemap.

    Many government sitemaps are served as ``*.xml.gz`` with ``Content-Type:
    application/gzip`` (NOT ``Content-Encoding: gzip``), so httpx does not decompress
    them: ``fetcher.get`` would hand back ~800 KB of raw gzip bytes decoded as a mangled
    string, and BeautifulSoup would find 0 ``<loc>`` (issue #63). We fetch RAW BYTES and
    gunzip whenever the URL ends in ``.gz`` or the payload starts with the gzip magic
    (``0x1f 0x8b``), then decode UTF-8 (the sitemaps.org-mandated encoding). Plain
    (non-gzipped) sitemaps are unaffected — they just skip the decompress branch.
    """
    data = fetcher.get_bytes(sm_url)[1]
    if sm_url.lower().endswith(".gz") or data[:2] == _GZIP_MAGIC:
        data = gzip.decompress(data)
    return data.decode("utf-8", "replace")


def _harvest_sitemap(recipe: Recipe, fetcher, max_links) -> list[str]:
    """Enumerate speech URLs from the site's sitemap(s).

    Sitemaps are the canonical "every URL" list — far more complete than paging a
    listing that only shows recent items. A sitemap *index* is followed into its
    child sitemaps. URLs are kept if they match listing.link_pattern. Gzipped sitemaps
    (``*.xml.gz``) are decompressed transparently (issue #63).
    """
    pattern = re.compile(recipe.listing.link_pattern) if recipe.listing.link_pattern else None
    collected, seen = [], set()
    queue = list(recipe.pagination.sitemap_urls or [])
    fetched = 0
    while queue and fetched < 200:  # cap how many sitemap files we'll open
        sm_url = queue.pop(0)
        fetched += 1
        try:
            soup = BeautifulSoup(_fetch_sitemap_xml(fetcher, sm_url), "xml")
        except Exception as e:
            log.warning("sitemap fetch failed: %s :: %s", sm_url, e)
            continue
        is_index = soup.find("sitemapindex") is not None
        for loc in soup.find_all("loc"):
            url = loc.get_text().strip()
            if is_index:
                queue.append(url)  # a child sitemap to open
            elif (pattern is None or pattern.search(url)) and url not in seen:
                seen.add(url)
                collected.append(url)
                if max_links and len(collected) >= max_links:
                    return collected
    return collected


def _next_href(html: str, base_url: str, selector: str) -> str | None:
    """Resolve the 'next' link's href from a listing page.

    `selector` may point at the <a> itself or at a wrapper (e.g. `li.next`); in the
    latter case the first descendant <a href> wins.

    Honours `<base href>` for the same reason `extract_links` does (issue #56) — a pager
    that resolves against the wrong base walks the crawl straight off the site after page 1.
    """
    soup = BeautifulSoup(html, "lxml")
    el = soup.select_one(selector)
    if el is None:
        return None
    href = el.get("href")
    if not href:
        inner = el.find("a", href=True)
        href = inner.get("href") if inner else None
    if not href:
        return None
    href = href.strip().strip("\\\"'").strip()
    return urljoin(_doc_base(soup, base_url), href) if href else None


def _harvest_next_link(recipe: Recipe, fetcher, max_pages, max_links, stats=None,
                       meta=None) -> list[str]:
    """Static pagination: follow the listing's own "next" link, page to page.

    For sites whose page URL cannot be *synthesised* — the pager carries a signed or
    opaque token (TYPO3's `cHash`, a session id, a cursor) so incrementing a query
    param just 404s — but whose "next" control is a real <a href> present in the
    server-rendered HTML. `click` can't help there: it needs `renderer: js`, and a site
    may hide the pager once its JS runs (making the element unclickable). This walks the
    chain over plain HTTP instead.

    Stops on: no next link, a next link already visited (loop guard), max_pages, or
    max_links. Unlike query_param/path it does NOT stop when a page yields no *new*
    links — an interior page of dupes shouldn't truncate the crawl; the absence of a
    next link is the real terminator.
    """
    pg = recipe.pagination
    hard_cap = max_pages if max_pages is not None else (pg.max_pages or 200)
    collected, seen = [], set()

    for start_url in recipe.start_urls:
        url, visited = start_url, set()
        for page_idx in range(hard_cap):
            if url in visited:  # cyclic pager
                _note(stats, "cyclic_pager")
                break
            visited.add(url)
            try:
                html = fetcher.get(url)
            except Exception as e:
                log.warning("listing page failed, stopping pagination here: %s :: %s", url, e)
                _note(stats, "listing_fetch_failed", early=True)
                break
            for link in extract_links(html, url, recipe.listing, meta, recipe.date_languages):
                if link not in seen:
                    seen.add(link)
                    collected.append(link)
            if max_links and len(collected) >= max_links:
                _note(stats, "max_links")
                break
            if (page_idx + 1) % 25 == 0:  # so a long harvest isn't a silent gap
                log.info("harvesting... %d listing pages, %d links so far",
                         page_idx + 1, len(collected))
            nxt = _next_href(html, url, pg.next_selector)
            if not nxt or nxt in visited:
                log.info("next_link pagination: no further 'next' link after %d page(s) "
                         "— end of the chain (%d link(s) harvested)",
                         page_idx + 1, len(collected))
                _note(stats, "cyclic_pager" if nxt else "no_next_link")
                break
            url = nxt
        else:
            _note(stats, "max_pages")
        if max_links and len(collected) >= max_links:
            break

    return collected[:max_links] if max_links else collected


def _harvest_click(recipe: Recipe, fetcher, max_pages, max_links, stats=None,
                   meta=None) -> list[str]:
    """JS pagination: load the listing, repeatedly click the 'next' button.

    The two ways this ends are deliberately kept apart (see issue #53). No element
    matching `next_selector` = the pager is gone = the last page, which is normal and
    logged at INFO. An element that matches but whose `.click()` raises is NOT normal: the
    usual cause is a site whose JS hides the pager (Playwright refuses to click a
    non-visible element) or swaps it for infinite scroll, and the crawl then returns page
    1 only while every other signal still says "success". That case is a WARNING and sets
    `stopped_early`.
    """
    page = fetcher.page
    pg = recipe.pagination
    hard_cap = max_pages if max_pages is not None else (pg.max_pages or 200)
    collected, seen = [], set()

    for start_url in recipe.start_urls:
        page.goto(start_url, wait_until="networkidle")
        for page_idx in range(hard_cap):
            for link in extract_links(page.content(), page.url, recipe.listing,
                                      meta, recipe.date_languages):
                if link not in seen:
                    seen.add(link)
                    collected.append(link)
            if max_links and len(collected) >= max_links:
                _note(stats, "max_links")
                break
            try:
                button = page.query_selector(pg.next_selector)
            except Exception as e:
                log.warning("click pagination: next_selector %r could not be evaluated after "
                            "%d page(s) (%s: %s) — pagination stopped EARLY, so this harvest "
                            "is probably incomplete.",
                            pg.next_selector, page_idx + 1, type(e).__name__, e)
                _note(stats, "next_click_failed", early=True)
                break
            if not button:
                log.info("click pagination: nothing matched next_selector %r after %d page(s) "
                         "— treating as the last page (%d link(s) harvested)",
                         pg.next_selector, page_idx + 1, len(collected))
                _note(stats, "no_next_button")
                break
            try:
                button.click()
                page.wait_for_load_state("networkidle")
                time.sleep(1.0)  # let new items render
            except Exception as e:
                log.warning(
                    "click pagination: next_selector %r MATCHED an element but clicking it "
                    "FAILED after %d page(s) (%s: %s) — pagination stopped EARLY, so this "
                    "harvest (%d link(s)) is probably a small fraction of the archive. A pager "
                    "that exists but will not click is usually hidden by the site's own JS "
                    "(Playwright refuses non-visible elements). If the pager is a real "
                    "<a href> in the HTML, use `pagination: next_link` instead of `click`.",
                    pg.next_selector, page_idx + 1, type(e).__name__, e, len(collected))
                _note(stats, "next_click_failed", early=True)
                break
        else:
            _note(stats, "max_pages")
        if max_links and len(collected) >= max_links:
            break

    return collected[:max_links] if max_links else collected
