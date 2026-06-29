"""Wayback Machine fallback (Internet Archive CDX API).

When a live source is exhausted, dead, or has restructured, the Internet Archive
often still holds the speeches. This is a thin, polite client over the CDX server
(https://archive.org/help/wayback_api.php and the CDX server docs). The Archive
is a public good maintained on a shoestring -- keep `delay` generous and `limit`
modest.

Typical use:
    snaps = list_snapshots("http://president.gov.example/discursos/*", limit=500)
    for s in snaps:
        html = fetch_snapshot(s)
"""

from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import urlparse
from typing import Iterable, Optional

import httpx

from .fetch import USER_AGENT

log = logging.getLogger(__name__)

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
DEFAULT_FETCH_DELAY = 5.0
DEFAULT_FETCH_RETRIES = 6
DEFAULT_FETCH_BACKOFF = 5.0
MAX_FETCH_BACKOFF = 60.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def list_snapshots(
    url: str,
    from_date: Optional[str] = None,   # "YYYYMMDD"
    to_date: Optional[str] = None,     # "YYYYMMDD"
    limit: Optional[int] = None,
    match_type: Optional[str] = None,  # "exact" | "prefix" | "host" | "domain"
    collapse: str = "digest",          # drop adjacent identical captures
    timeout: float = 60.0,
) -> list[dict]:
    """Query the CDX index. Returns one dict per capture (timestamp, original, ...).

    Use a trailing '*' on the url (or match_type='prefix'/'domain') to list every
    archived page under a site, not just one URL.
    """
    if url.endswith("*"):
        url = url[:-1]
    params = {"url": url, "output": "json", "collapse": collapse}
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    if limit:
        params["limit"] = str(limit)
    if match_type:
        params["matchType"] = match_type

    resp = httpx.get(
        CDX_ENDPOINT, params=params,
        headers={"User-Agent": USER_AGENT}, timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return []
    header, *rows = data
    return [dict(zip(header, row)) for row in rows]


def create_client(timeout: float = 60.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=timeout,
    )


def list_snapshots_for_queries(
    urls: Iterable[str],
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: Optional[int] = None,
    match_type: str = "prefix",
    collapse: str = "urlkey",
    timeout: float = 60.0,
) -> list[dict]:
    """Query CDX for one or more URL prefixes and de-duplicate by original URL.

    If `limit` is set, it caps the total number of returned captures across all
    queries. When multiple URLs are provided, the underlying CDX call is capped
    per query only when there is a single query; otherwise the total cap is
    enforced after de-duplicating the merged results.
    """
    queries = list(urls)
    per_query_limit = limit if len(queries) == 1 else None
    out: list[dict] = []
    seen: set[str] = set()

    for url in queries:
        snaps = list_snapshots(
            url,
            from_date=from_date,
            to_date=to_date,
            limit=per_query_limit,
            match_type=match_type,
            collapse=collapse,
            timeout=timeout,
        )
        for entry in snaps:
            original = entry.get("original")
            if not original or original in seen:
                continue
            seen.add(original)
            out.append(entry)
            if limit is not None and len(out) >= limit:
                return out
    return out


def _url_path(url: str) -> str:
    """Normalized path of a URL, tolerant of a missing scheme or trailing '*'
    (recipe start_urls are CDX prefixes like 'site.gov/discursos' — no scheme)."""
    u = url.strip().rstrip("*").rstrip("/")
    if "://" not in u:
        u = "http://" + u
    return urlparse(u).path.rstrip("/")


def filter_entries_for_recipe(
    entries: Iterable[dict],
    link_pattern: Optional[str] = None,
    start_urls: Iterable[str] = (),
) -> list[dict]:
    """Filter CDX captures down to speech pages — country-agnostic.

    All per-site knowledge comes from the recipe, never from this engine:
      * `link_pattern` (the recipe's `listing.link_pattern`) decides which URLs are
        speeches — keep it tight enough to exclude index / section / bio pages
        (e.g. require a numeric id: ``/discursos/\\d+[^/]*$``).
      * the listing index itself — and its ``?page=`` / ``?start=`` paginated
        variants, which share the index's path — is dropped by matching the
        recipe's own `start_urls` paths. No site-specific paths are hardcoded here;
        a new country needs only a new recipe, not a change to this module.
    """
    pattern = re.compile(link_pattern) if link_pattern else None
    listing_paths = {_url_path(u) for u in start_urls}
    out: list[dict] = []
    seen: set[str] = set()

    for entry in entries:
        original = entry.get("original")
        if not original or original in seen:
            continue
        if _url_path(original) in listing_paths:
            continue
        if pattern and not pattern.search(original):
            continue
        seen.add(original)
        out.append(entry)

    return out


def snapshot_url(entry: dict) -> str:
    """Build the raw-capture URL for a CDX entry (the 'id_' suffix gets the
    original page bytes, not the Archive's reframed viewer)."""
    return f"https://web.archive.org/web/{entry['timestamp']}id_/{entry['original']}"


def _retry_sleep(attempt: int, backoff: float) -> float:
    base = min(backoff * (2 ** attempt), MAX_FETCH_BACKOFF)
    jitter = random.uniform(0.0, min(1.0, base * 0.1))
    return base + jitter


def fetch_snapshot(
    entry: dict,
    delay: float = DEFAULT_FETCH_DELAY,
    timeout: float = 60.0,
    client: Optional[httpx.Client] = None,
    retries: int = DEFAULT_FETCH_RETRIES,
    backoff: float = DEFAULT_FETCH_BACKOFF,
) -> str:
    """Politely fetch one archived capture's HTML, riding out transient Archive
    throttling — connection refusals (`ConnectError`) and 429/5xx — with capped
    exponential backoff. The Archive periodically refuses a burst then recovers
    within a minute or so, so we retry long enough to outlast that window instead
    of surfacing a one-off refusal as a failed speech. Non-retryable statuses
    (e.g. 404) raise immediately."""
    time.sleep(delay)
    close_client = client is None
    client = client or create_client(timeout=timeout)
    url = snapshot_url(entry)
    try:
        for attempt in range(retries):
            try:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.text
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError):
                    status = exc.response.status_code if exc.response is not None else None
                    if status not in RETRYABLE_STATUS_CODES:
                        raise
                if attempt >= retries - 1:
                    raise
                wait = _retry_sleep(attempt, backoff)
                log.info("wayback throttled (%s); retry %d/%d in %.0fs: %s",
                         type(exc).__name__, attempt + 1, retries, wait, url)
                time.sleep(wait)
    finally:
        if close_client:
            client.close()
