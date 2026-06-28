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

import time
from typing import Optional

import httpx

from .fetch import USER_AGENT

CDX_ENDPOINT = "http://web.archive.org/cdx/search/cdx"


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


def snapshot_url(entry: dict) -> str:
    """Build the raw-capture URL for a CDX entry (the 'id_' suffix gets the
    original page bytes, not the Archive's reframed viewer)."""
    return f"http://web.archive.org/web/{entry['timestamp']}id_/{entry['original']}"


def fetch_snapshot(entry: dict, delay: float = 3.0, timeout: float = 60.0) -> str:
    """Politely fetch one archived capture's HTML."""
    time.sleep(delay)
    resp = httpx.get(
        snapshot_url(entry),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text
