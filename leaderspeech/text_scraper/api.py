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

import copy
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


# One path segment is a dict key or a list index. Tokens: a "quoted key" (may hold
# spaces/dots), a [N] list index, or a bare key (any run without . [ ] "). Dots between
# tokens are just separators and fall out. So `a.b.c` -> keys a,b,c (unchanged);
# `a.b[0].c` -> key,key,index0,key; `tags.metaData."Publish Date"[0].title` handles the
# spaced key + index. A bare numeric token like the `.0` in `a.results.0` stays a *key*
# ("0") — an index is ONLY the bracket form `[0]` — so existing recipes are unaffected.
_PATH_TOKEN = re.compile(r'"([^"]*)"|\[(\d+)\]|([^.\[\]"]+)')


def _parse_path(dotted_path: str) -> list[tuple[str, object]]:
    """Split a dotted path into typed segments: ("key", str) or ("index", int)."""
    segs: list[tuple[str, object]] = []
    for m in _PATH_TOKEN.finditer(dotted_path):
        quoted, index, bare = m.group(1), m.group(2), m.group(3)
        if index is not None:
            segs.append(("index", int(index)))
        else:
            segs.append(("key", quoted if quoted is not None else bare))
    return segs


def _dig(obj, dotted_path: Optional[str]):
    """Descend along a dotted path. Keys need a dict that contains them; indices
    (`[i]`) need a list in range. Anything else -> None. `a.b.c` on plain dicts and
    the missing/empty-path cases behave exactly as before."""
    if not dotted_path:
        return None
    cur = obj
    for kind, seg in _parse_path(dotted_path):
        if kind == "key":
            if isinstance(cur, dict) and seg in cur:
                cur = cur[seg]
            else:
                return None
        else:  # index
            if isinstance(cur, list) and -len(cur) <= seg < len(cur):
                cur = cur[seg]
            else:
                return None
    return cur


def _set_dig(obj: dict, dotted_path: str, value) -> None:
    """Write `value` into `obj` at `dotted_path`, creating intermediate dicts for
    missing keys. Used to inject the POST paging offset into a request body."""
    segs = _parse_path(dotted_path)
    cur = obj
    for kind, seg in segs[:-1]:
        if kind == "key":
            nxt = cur.get(seg) if isinstance(cur, dict) else None
            if not isinstance(nxt, (dict, list)):
                nxt = {}
                cur[seg] = nxt
            cur = nxt
        else:  # index into an existing list
            cur = cur[seg]
    kind, seg = segs[-1]
    cur[seg] = value


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


ROOT_PATH = "."


def _rows_of(data, results_path: str):
    """The result rows for one API response.

    Normally `results_path` is a dotted path into an envelope object (SharePoint's
    `d.query.…Table.Rows.results`). But plenty of REST APIs answer with a **bare JSON
    array at the root** — WordPress's `/wp-json/wp/v2/posts` is the common one, and any
    WP-backed government site hits this. A dotted path cannot address a root array
    (`_dig` needs at least one key), so `results_path: "."` names the response itself.
    """
    if results_path.strip() == ROOT_PATH:
        return data if isinstance(data, list) else None
    return _dig(data, results_path)


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
    method = (cfg.method or "GET").upper()
    # A POST that pages by writing the offset into its body still advances even without a
    # query `param`; otherwise "no param" means a single request.
    paginates = bool(pg.param or (method == "POST" and cfg.body_page_field))

    close_client = client is None
    client = client or create_client(recipe)
    collected, seen = [], set()
    try:
        for page_idx in range(max_pages):
            value = pg.start + page_idx * pg.step
            url, body = base, None
            if method == "POST":
                body = copy.deepcopy(cfg.body) if cfg.body is not None else {}
                if cfg.body_page_field:
                    _set_dig(body, cfg.body_page_field, value)  # offset into the body
                elif pg.param:
                    url = _with_query_param(base, pg.param, value)  # POST paged by query
            elif pg.param:  # GET (today's path)
                url = _with_query_param(base, pg.param, value)
            try:
                resp = client.post(url, json=body) if method == "POST" else client.get(url)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                # one bad page shouldn't kill the whole harvest
                log.warning("api page failed, stopping pagination here: %s :: %s", url, e)
                break
            rows = _rows_of(data, cfg.results_path)
            if not rows:
                break  # past the last page of results
            gained = 0
            for row in rows:
                item = _extract_item(row, cfg)
                link = _as_str(item.get("url"))
                if not link:
                    continue
                link = urljoin(cfg.url_base or base, link.strip())
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
            if not paginates:
                break  # no paging param / body offset -> single request
            if gained == 0:
                break  # rows present but none new/qualifying — stop
            if cfg.delay:
                time.sleep(cfg.delay)
    finally:
        if close_client:
            client.close()
    return collected
