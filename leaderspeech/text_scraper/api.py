"""JSON / search-API source type (pagination.type == 'api').

Some sites — notably SharePoint "search web-part" pages behind a WAF — serve only
page chrome as HTML; the speech list is loaded client-side from a JSON endpoint
(e.g. ``…/_api/search/query``). This module fetches that endpoint, paginates it, and
returns one *entry* per result carrying the speech URL plus whatever metadata the
JSON provides (title / date / text / speaker). The orchestrator then fetches each
speech page as usual, falling back to the carried metadata for any field the page
misses (and skipping the page fetch entirely when the JSON already carries the text).

All per-site variation lives in the recipe's ``pagination.api`` block and the shared
``pagination.param``/``start``/``step``/``max_pages`` paging knobs — nothing here is
site-specific, so a new SharePoint/JSON source needs only a new recipe.
"""

from __future__ import annotations

import logging
import time
from typing import Optional
import re
from urllib.parse import urljoin

import httpx

from .extract import clean_text, parse_date
from .fetch import build_headers
from .paginate import _with_query_param
from .recipe import Recipe

log = logging.getLogger(__name__)

# A generic XHR Accept. SharePoint needs a precise OData Accept (e.g.
# "application/json;odata=nometadata") which the recipe sets via api.headers.
DEFAULT_API_ACCEPT = "application/json, text/javascript, */*; q=0.01"


def _dig(obj, dotted_path: Optional[str]):
    """Descend dict keys along a dotted path (``a.b.c``). Returns None if any
    segment is missing or a value along the way isn't a dict."""
    if not dotted_path:
        return None
    cur = obj
    for seg in dotted_path.split("."):
        if isinstance(cur, dict) and seg in cur:
            cur = cur[seg]
        else:
            return None
    return cur


def _as_str(v) -> Optional[str]:
    if v is None:
        return None
    return v if isinstance(v, str) else str(v)


def _extract_item(row, cfg) -> dict:
    """Pull url/title/date/text/speaker off one result row, in either direct
    dotted-path mode or SharePoint Key/Value cells mode."""
    if cfg.cells_path:
        cells = _dig(row, cfg.cells_path)
        kv = {}
        if isinstance(cells, list):
            for cell in cells:
                if isinstance(cell, dict):
                    kv[cell.get(cfg.cell_key)] = cell.get(cfg.cell_value)
        get = lambda field: kv.get(field) if field else None
    else:
        get = lambda field: _dig(row, field) if field else None
    return {
        "url": get(cfg.url_field),
        "title": get(cfg.title_field),
        "date": get(cfg.date_field),
        "text": get(cfg.text_field),
        "speaker": get(cfg.speaker_field),
    }


def create_client(recipe: Recipe, timeout: float = 60.0) -> httpx.Client:
    extra = {"Accept": DEFAULT_API_ACCEPT}
    extra.update(recipe.pagination.api.headers or {})
    return httpx.Client(
        headers=build_headers(recipe.user_agent, extra=extra),
        follow_redirects=True,
        timeout=timeout,
        verify=recipe.verify_ssl,  # many gov sites have broken cert chains
    )


def harvest_entries(
    recipe: Recipe,
    max_links: Optional[int] = None,
    client: Optional[httpx.Client] = None,
) -> list[dict]:
    """Return one entry per result row: ``{url, title, date, text, speaker}``.

    ``url`` is absolute and (when ``listing.link_pattern`` is set) matches it; ``date``
    is parsed to an ISO string; title / text / speaker are cleaned. Pagination stops
    when a page returns no new qualifying rows, after ``max_pages`` requests, or once
    ``max_links`` entries are collected. A single request is made when no paging
    ``param`` is configured.
    """
    cfg = recipe.pagination.api
    pg = recipe.pagination
    pattern = re.compile(recipe.listing.link_pattern) if recipe.listing.link_pattern else None
    base = recipe.start_urls[0]
    max_pages = pg.max_pages or 200

    close_client = client is None
    client = client or create_client(recipe)
    collected, seen = [], set()
    try:
        for page_idx in range(max_pages):
            if pg.param:
                value = pg.start + page_idx * pg.step
                url = _with_query_param(base, pg.param, value)
            else:
                url = base
            try:
                resp = client.get(url)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                # one bad page shouldn't kill the whole harvest
                log.warning("api page failed, stopping pagination here: %s :: %s", url, e)
                break
            rows = _dig(data, cfg.results_path)
            if not rows:
                break  # past the last page of results
            gained = 0
            for row in rows:
                item = _extract_item(row, cfg)
                link = _as_str(item.get("url"))
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
                    "title": clean_text(_as_str(item.get("title"))),
                    # JSON dates are standardized (ISO/RFC), not free text — let
                    # dateparser autodetect; the recipe's date_languages hint is for
                    # localized prose on the HTML page and would mis-order ISO dates.
                    "date": parse_date(_as_str(item.get("date"))),
                    "text": clean_text(_as_str(item.get("text"))),
                    "speaker": clean_text(_as_str(item.get("speaker"))),
                })
                gained += 1
                if max_links and len(collected) >= max_links:
                    return collected
            if (page_idx + 1) % 25 == 0:  # so a long harvest isn't a silent gap
                log.info("api harvesting... %d pages, %d items so far", page_idx + 1, len(collected))
            if not pg.param:
                break  # no paging param -> single request
            if gained == 0:
                break  # rows present but none new/qualifying — stop
            if cfg.delay:
                time.sleep(cfg.delay)
    finally:
        if close_client:
            client.close()
    return collected
