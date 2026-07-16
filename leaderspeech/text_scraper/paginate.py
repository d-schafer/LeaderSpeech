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

import logging
import re
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from .recipe import Listing, PaginationType, Recipe

log = logging.getLogger(__name__)


def extract_links(html: str, base_url: str, listing: Listing) -> list[str]:
    """Pull qualifying speech links off one listing page, order-preserving."""
    soup = BeautifulSoup(html, "lxml")
    anchors = soup.select(listing.link_selector) if listing.link_selector else soup.find_all("a")
    pattern = re.compile(listing.link_pattern) if listing.link_pattern else None

    out, seen = [], set()
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
        # some sites (e.g. gob.mx) wrap hrefs in escaped quotes: \"/path\"
        href = href.strip().strip("\\\"'").strip()
        if not href:
            continue
        full = urljoin(base_url, href)
        if pattern and not pattern.search(full):
            continue
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
                  stats: dict | None = None) -> list[str]:
    pg = recipe.pagination

    if pg.type == PaginationType.url_list:
        # These are speech URLs, not listings: hand them back as the scrape targets.
        _note(stats, "single_page")
        return list(pg.url_list or [])
    if pg.type == PaginationType.sitemap:
        _note(stats, "single_page")
        return _harvest_sitemap(recipe, fetcher, max_links)
    if pg.type == PaginationType.click:
        return _harvest_click(recipe, fetcher, max_pages, max_links, stats)
    if pg.type == PaginationType.next_link:
        return _harvest_next_link(recipe, fetcher, max_pages, max_links, stats)

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
                add(extract_links(fetcher.get(start_url), start_url, recipe.listing))
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
            page_links = extract_links(html, page_url, recipe.listing)
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


def _harvest_sitemap(recipe: Recipe, fetcher, max_links) -> list[str]:
    """Enumerate speech URLs from the site's sitemap(s).

    Sitemaps are the canonical "every URL" list — far more complete than paging a
    listing that only shows recent items. A sitemap *index* is followed into its
    child sitemaps. URLs are kept if they match listing.link_pattern.
    """
    pattern = re.compile(recipe.listing.link_pattern) if recipe.listing.link_pattern else None
    collected, seen = [], set()
    queue = list(recipe.pagination.sitemap_urls or [])
    fetched = 0
    while queue and fetched < 200:  # cap how many sitemap files we'll open
        sm_url = queue.pop(0)
        fetched += 1
        try:
            soup = BeautifulSoup(fetcher.get(sm_url), "xml")
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
    """
    el = BeautifulSoup(html, "lxml").select_one(selector)
    if el is None:
        return None
    href = el.get("href")
    if not href:
        inner = el.find("a", href=True)
        href = inner.get("href") if inner else None
    if not href:
        return None
    href = href.strip().strip("\\\"'").strip()
    return urljoin(base_url, href) if href else None


def _harvest_next_link(recipe: Recipe, fetcher, max_pages, max_links, stats=None) -> list[str]:
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
            for link in extract_links(html, url, recipe.listing):
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


def _harvest_click(recipe: Recipe, fetcher, max_pages, max_links, stats=None) -> list[str]:
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
            for link in extract_links(page.content(), page.url, recipe.listing):
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
