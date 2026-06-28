"""Pagination + link harvesting.

`harvest_links` walks a source's listing pages (however that source paginates)
and returns the de-duplicated list of speech-page URLs to scrape. The five
pagination strategies seen across the old scrapers are unified behind it:
query-param offsets, path segments, JS "next" clicks, an explicit URL list, or a
single page.
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


def harvest_links(recipe: Recipe, fetcher, max_pages=None, max_links=None) -> list[str]:
    pg = recipe.pagination

    if pg.type == PaginationType.url_list:
        return list(pg.url_list or [])
    if pg.type == PaginationType.sitemap:
        return _harvest_sitemap(recipe, fetcher, max_links)
    if pg.type == PaginationType.click:
        return _harvest_click(recipe, fetcher, max_pages, max_links)

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
            except Exception as e:
                log.warning("listing fetch failed: %s :: %s", start_url, e)
            continue

        for page_idx in range(hard_cap):
            value = pg.start + page_idx * pg.step
            if pg.type == PaginationType.query_param:
                page_url = _with_query_param(start_url, pg.param, value)
            else:  # path
                page_url = start_url.rstrip("/") + f"/{value}"
            try:
                html = fetcher.get(page_url)
            except Exception as e:
                # one bad listing page shouldn't kill the whole crawl
                log.warning("listing page failed, stopping pagination here: %s :: %s", page_url, e)
                break
            gained = add(extract_links(html, page_url, recipe.listing))
            if gained == 0:  # ran past the last page of results
                break
            if max_links and len(collected) >= max_links:
                break
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


def _harvest_click(recipe: Recipe, fetcher, max_pages, max_links) -> list[str]:
    """JS pagination: load the listing, repeatedly click the 'next' button."""
    page = fetcher.page
    pg = recipe.pagination
    hard_cap = max_pages if max_pages is not None else (pg.max_pages or 200)
    collected, seen = [], set()

    for start_url in recipe.start_urls:
        page.goto(start_url, wait_until="networkidle")
        for _ in range(hard_cap):
            for link in extract_links(page.content(), page.url, recipe.listing):
                if link not in seen:
                    seen.add(link)
                    collected.append(link)
            if max_links and len(collected) >= max_links:
                break
            try:
                button = page.query_selector(pg.next_selector)
                if not button:
                    break
                button.click()
                page.wait_for_load_state("networkidle")
                time.sleep(1.0)  # let new items render
            except Exception:
                break
        if max_links and len(collected) >= max_links:
            break

    return collected[:max_links] if max_links else collected
