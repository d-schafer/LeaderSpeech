"""RSS / Atom source type (pagination.type == 'feed').

A lighter-weight sibling of the JSON ``api`` type for sources that publish a feed.
``start_urls`` are the feed URL(s); each entry yields the speech URL plus title /
date / (optionally) the body text. Like ``api`` and ``wayback``, this returns
*entries* carrying metadata, which the orchestrator uses to fill any field the
speech page misses — and, when ``feed.use_content`` is on and the feed carries the
full text, to skip the page fetch entirely.

Per-site variation lives in the recipe's ``pagination.feed`` block and the shared
``pagination.param``/``start``/``step``/``max_pages`` paging knobs (for feeds that
paginate, e.g. WordPress ``?paged=N``); a single request per feed URL otherwise.
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .extract import clean_text, parse_date
from .fetch import build_headers
from .paginate import _with_query_param
from .recipe import FeedConfig, Recipe

log = logging.getLogger(__name__)

FEED_ACCEPT = "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"


def create_client(recipe: Recipe, timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(
        headers=build_headers(recipe.user_agent, extra={"Accept": FEED_ACCEPT}),
        follow_redirects=True,
        timeout=timeout,
        verify=recipe.verify_ssl,
    )


def _as_str(v) -> Optional[str]:
    if v is None:
        return None
    return v if isinstance(v, str) else str(v)


def _text(node) -> Optional[str]:
    return node.get_text() if node is not None else None


def _find_first(parent, names):
    """First child element matching any of `names` (local names; tolerates namespaced
    tags like content:encoded, which the xml parser exposes as 'encoded')."""
    for name in names:
        node = parent.find(name)
        if node is not None:
            return node
    return None


def _rss_item(item, use_content: bool):
    url = _text(item.find("link"))
    if not url:  # some RSS items carry only an atom:link with an href
        alt = item.find("link", href=True)
        url = alt.get("href") if alt else None
    title = _text(item.find("title"))
    date = _text(_find_first(item, ["pubDate", "date", "published"]))
    text = ""
    if use_content:
        text = _text(_find_first(item, ["encoded", "content:encoded", "description", "summary"]))
    return url, title, date, text


def _atom_entry(entry, use_content: bool):
    url = None
    links = entry.find_all("link")
    for ln in links:
        if ln.get("href") and ln.get("rel") in (None, "alternate"):
            url = ln.get("href")
            break
    if url is None and links:
        url = links[0].get("href")
    title = _text(entry.find("title"))
    date = _text(_find_first(entry, ["updated", "published", "date"]))
    text = ""
    if use_content:
        text = _text(_find_first(entry, ["content", "summary"]))
    return url, title, date, text


def _parse_feed(xml: str, fmt: str, use_content: bool):
    soup = BeautifulSoup(xml, "xml")
    rss_items = soup.find_all("item")
    if fmt == "rss" or (fmt == "auto" and rss_items):
        return [_rss_item(i, use_content) for i in rss_items]
    return [_atom_entry(e, use_content) for e in soup.find_all("entry")]


def harvest_entries(
    recipe: Recipe,
    max_links: Optional[int] = None,
    client: Optional[httpx.Client] = None,
) -> list[dict]:
    """Return one entry per feed item: ``{url, title, date, text, speaker}``.

    ``url`` is absolute and (when ``listing.link_pattern`` is set) matches it; ``date``
    is parsed to an ISO string; title / text are cleaned. ``text`` is populated from
    the feed body only when ``feed.use_content`` is on. Each feed URL is fetched once,
    or paginated when ``pagination.param`` is set; stops on an empty page.
    """
    pg = recipe.pagination
    cfg = pg.feed or FeedConfig()
    fmt = (cfg.format or "auto").lower()
    pattern = re.compile(recipe.listing.link_pattern) if recipe.listing.link_pattern else None
    max_pages = pg.max_pages or 200

    close_client = client is None
    client = client or create_client(recipe)
    collected, seen = [], set()
    try:
        for base in recipe.start_urls:
            for page_idx in range(max_pages):
                if pg.param:
                    value = pg.start + page_idx * pg.step
                    url = _with_query_param(base, pg.param, value)
                else:
                    url = base
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    xml = resp.text
                except Exception as e:
                    log.warning("feed fetch failed, stopping pagination here: %s :: %s", url, e)
                    break
                raws = _parse_feed(xml, fmt, cfg.use_content)
                if not raws:
                    break
                gained = 0
                for rurl, title, date, text in raws:
                    link = _as_str(rurl)
                    if not link:
                        continue
                    link = urljoin(base, link.strip())
                    if pattern and not pattern.search(link):
                        continue
                    if link in seen:
                        continue
                    seen.add(link)
                    collected.append({
                        "url": link,
                        "title": clean_text(_as_str(title)),
                        # Feed dates are standardized (RFC822 pubDate / RFC3339 updated),
                        # not free text — autodetect; the date_languages hint is for the
                        # HTML page and would mis-order these machine dates.
                        "date": parse_date(_as_str(date)),
                        "text": clean_text(_as_str(text)),
                        "speaker": "",
                    })
                    gained += 1
                    if max_links and len(collected) >= max_links:
                        return collected
                if not pg.param or gained == 0:
                    break  # single request per feed, or past the last page
    finally:
        if close_client:
            client.close()
    return collected
