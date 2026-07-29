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
from urllib.parse import parse_qsl, unquote, urlencode, urlparse
from typing import TYPE_CHECKING, Iterable, Optional

import httpx

from .fetch import USER_AGENT

if TYPE_CHECKING:  # annotations only — keeps this module importable on its own
    from .recipe import Recipe, WaybackExtend

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
    filters: Optional[Iterable[str]] = None,  # extra CDX `filter=` exprs (field:regex)
    timeout: float = 60.0,
) -> list[dict]:
    """Query the CDX index. Returns one dict per capture (timestamp, original, ...).

    Use a trailing '*' on the url (or match_type='prefix'/'domain') to list every
    archived page under a site, not just one URL. `filters` are raw CDX filter
    expressions (e.g. "mimetype:application/pdf") ANDed together — handy to keep a
    prefix query to just the PDF (or 200-status) captures.
    """
    if url.endswith("*"):
        url = url[:-1]
    params = {"url": url, "output": "json"}
    if collapse:  # falsy collapse ("" / None) = don't collapse — keep every capture
        params["collapse"] = collapse
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    if limit:
        params["limit"] = str(limit)
    if match_type:
        params["matchType"] = match_type
    query = params
    if filters:
        # CDX allows repeated `filter=` params, so once there are filters the query has
        # to be a list of pairs rather than a dict (which can't hold duplicate keys).
        query = list(params.items()) + [("filter", f) for f in filters]

    resp = httpx.get(
        CDX_ENDPOINT, params=query,
        headers={"User-Agent": USER_AGENT}, timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data:
        return []
    header, *rows = data
    return [dict(zip(header, row)) for row in rows]


def best_capture(url: str, timeout: float = 60.0) -> Optional[dict]:
    """The most complete archived capture of an EXACT url: the largest-`length` HTTP-200
    snapshot, or None if CDX has no 200 capture (or the query errors).

    The Archive sometimes stores a truncated *partial* of a large file (e.g. a PDF cut at
    exactly 1 MB). The capture nearest a given moment can be that partial even when a
    complete capture of the same URL exists at another timestamp — so fetching by
    page-timestamp alone loses the body. Querying the URL's own captures and taking the
    biggest 200 recovers the complete one (issue #70). `collapse` is disabled so a
    differing-length duplicate isn't hidden."""
    try:
        snaps = list_snapshots(
            url, match_type="exact", collapse="", filters=["statuscode:200"], timeout=timeout,
        )
    except Exception as e:  # CDX hiccup shouldn't fail the row — caller falls back
        log.info("cdx best_capture query failed for %s: %s", url, e)
        return None

    def _length(entry: dict) -> int:
        try:
            return int(entry.get("length") or 0)
        except (TypeError, ValueError):
            return 0

    usable = [s for s in snaps if s.get("timestamp") and s.get("original")]
    return max(usable, key=_length) if usable else None


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
    filters: Optional[Iterable[str]] = None,
    timeout: float = 60.0,
) -> list[dict]:
    """Query CDX for one or more URL prefixes and de-duplicate by original URL.

    If `limit` is set, it caps the total number of returned captures across all
    queries. When multiple URLs are provided, the underlying CDX call is capped
    per query only when there is a single query; otherwise the total cap is
    enforced after de-duplicating the merged results.
    """
    filters = list(filters) if filters else None
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
            filters=filters,
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


# --- one capture per PAGE (query-noise dedupe) --------------------------------------
# The Archive captures the same article under every tracking/UI query string a referrer
# ever used: ?utm_source=…, ?fbclid=…, ?comment=disable, ?openVideo=true. Each is a
# separate CDX row with its own urlkey, so `collapse=urlkey` does NOT merge them, and the
# scrape loop's URL-keyed `seen_urls` treats them as different documents — paying a full
# Archive fetch, a row, and later a GPT call for a page already collected. On India's
# pmindia.gov.in that is 5,544 of 15,926 harvested links (35%).
#
# Stripping the query ENTIRELY would be a disaster: plenty of older government sites put
# the document id IN the query (president.ie `index.php?section=5&speech=204&lang=eng`,
# pmindia.nic.in `speech-details.php?nodeid=1021`, president.gov.ge `…?p=2186&i=1`), and
# a blanket strip collapses 1,039 distinct speeches to one page. So this is a DENYLIST of
# parameters that provably never change *which* document is served.
NOISE_PARAMS = frozenset({
    # analytics / referral / social click ids
    "fbclid", "gclid", "msclkid", "yclid", "igshid", "mc_cid", "mc_eid",
    "ref", "referrer", "source", "_hsenc", "_hsmi", "env", "rid", "clckid",
    # on-page UI toggles that re-render the same article
    "comment", "replytocom", "openvideo", "openphoto", "opengallery",
    "amp", "output", "print", "sphrase_id",
})
# Prefix families: utm_*, Adobe at_*, Matomo/Piwik pk_*/piwik_*, F5/BIG-IP TSPD_*, __cf*
NOISE_PARAM_PREFIXES = ("utm_", "at_", "pk_", "piwik_", "tspd_", "__cf")


def page_identity(url: str) -> str:
    """A key that is equal for two URLs serving the SAME document.

    Normalizes scheme, `www.`, port and trailing slash, and drops only the query
    parameters in :data:`NOISE_PARAMS` / :data:`NOISE_PARAM_PREFIXES`. Meaningful
    parameters are kept, so query-addressed sites stay fully distinct.
    """
    pr = urlparse(url)
    host = pr.netloc.split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    path = unquote(pr.path).rstrip("/").lower()
    # WordPress paginates a comment thread as a sub-path of the same article
    path = re.sub(r"/comment-page-\d+$", "", path)
    kept = [
        (k, v) for k, v in parse_qsl(pr.query, keep_blank_values=True)
        if k.lower() not in NOISE_PARAMS and not k.lower().startswith(NOISE_PARAM_PREFIXES)
    ]
    return host + path + ("?" + urlencode(sorted(kept)) if kept else "")


def filter_entries_for_recipe(
    entries: Iterable[dict],
    link_pattern: Optional[str] = None,
    start_urls: Iterable[str] = (),
    dedupe_noise_params: bool = True,
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
      * `dedupe_noise_params` (on by default) keeps only the FIRST capture of each
        distinct page, ignoring tracking/UI query parameters — see :func:`page_identity`.
        Set it False to fetch every query variant as its own document.
    """
    pattern = re.compile(link_pattern) if link_pattern else None
    listing_paths = {_url_path(u) for u in start_urls}
    out: list[dict] = []
    seen: set[str] = set()
    deduped = 0

    for entry in entries:
        original = entry.get("original")
        if not original:
            continue
        key = page_identity(original) if dedupe_noise_params else original
        if key in seen:
            # A second capture of a page we already have (usually the same article with a
            # ?utm_source= / ?comment= suffix). Count it so the run log can show the saving.
            deduped += 1
            continue
        if _url_path(original) in listing_paths:
            continue
        if pattern and not pattern.search(original):
            continue
        seen.add(key)
        out.append(entry)

    if deduped:
        log.info("wayback: skipped %d duplicate capture(s) of pages already harvested "
                 "(same page, different tracking/UI query string)", deduped)
    return out


# --- wayback_extend: continuing a LIVE recipe into the archive -----------------------
# Shared by `run` (which does the real continuation after a live crawl) and `probe`
# (which samples it, so a recipe's archived-layout selectors can be checked BEFORE
# paying for a full run — issue #54). Both must derive the prefix, link_pattern and
# selector overrides identically, or the probe would validate something the run doesn't do.

EXTEND_OVERRIDE_FIELDS = ("title", "text", "date", "speaker", "context")


def cdx_prefix(url: str) -> str:
    """A CDX prefix (host+path, no scheme, no trailing slash) from a live start_url —
    the default `wayback_extend` prefix. e.g. https://www.casarosada.gob.ar/discursos/
    -> www.casarosada.gob.ar/discursos."""
    u = url.strip()
    if "://" in u:
        u = u.split("://", 1)[1]
    return u.rstrip("/")


def extend_prefix(recipe: "Recipe", ext: "WaybackExtend") -> str:
    return ext.prefix or cdx_prefix(recipe.start_urls[0])


def extend_link_pattern(recipe: "Recipe", ext: "WaybackExtend") -> Optional[str]:
    return ext.link_pattern or recipe.listing.link_pattern


def extend_recipe(recipe: "Recipe", ext: "WaybackExtend") -> "Recipe":
    """The recipe used to extract archived pages: the live recipe, plus any per-field
    selector overrides the `wayback_extend` block sets for the older layout."""
    overrides = {f: getattr(ext, f) for f in EXTEND_OVERRIDE_FIELDS
                 if getattr(ext, f) is not None}
    return recipe.model_copy(update=overrides) if overrides else recipe


def harvest_extend_entries(recipe: "Recipe", ext: "WaybackExtend",
                           to_date: Optional[str]) -> list[dict]:
    """Archive captures for the wayback_extend continuation: the shared CDX client over a
    single derived/overridden prefix, bounded by `to_date` (normally the live floor, so
    live and archive don't overlap)."""
    prefix = extend_prefix(recipe, ext)
    entries = list_snapshots_for_queries(
        [prefix],
        from_date=ext.wayback_from,
        to_date=to_date,
        limit=ext.wayback_limit,
        match_type=ext.wayback_match_type,
        collapse=ext.wayback_collapse,
        filters=ext.wayback_filter,
    )
    return filter_entries_for_recipe(
        entries, extend_link_pattern(recipe, ext), start_urls=[prefix],
        dedupe_noise_params=recipe.pagination.wayback_dedupe_noise_params,
    )


def snapshot_url(entry: dict) -> str:
    """Build the raw-capture URL for a CDX entry (the 'id_' suffix gets the
    original page bytes, not the Archive's reframed viewer)."""
    return f"https://web.archive.org/web/{entry['timestamp']}id_/{entry['original']}"


class AdaptivePacer:
    """Auto-tunes the inter-fetch Internet-Archive delay toward the 'sweet spot' where the Archive
    stops refusing connections — so a long wayback run doesn't waste minutes on retry backoff.

    One pacer is shared across a whole run's wayback phase. Each fetch that hit ANY throttling
    (ConnectError / 429 / 5xx) raises the delay by `step_up` (bounded by `ceiling`); after
    `ease_after` consecutive clean fetches the delay eases back down by `ease_step` (never below
    `base`). It converges to just above the rate the Archive tolerates from your IP right now.
    """

    def __init__(self, base: float, ceiling: float, step_up: float = 1.5,
                 ease_after: int = 20, ease_step: float = 0.5):
        self.base = max(0.0, float(base))
        self.ceiling = max(self.base, float(ceiling))
        self.value = self.base
        self.step_up = float(step_up)
        self.ease_after = int(ease_after)
        self.ease_step = float(ease_step)
        self._clean = 0
        self.throttle_events = 0  # total fetches that hit throttling (for the end-of-run summary)

    def on_throttle(self) -> None:
        """A fetch hit throttling — slow down (once per throttled fetch, not per retry)."""
        self._clean = 0
        self.throttle_events += 1
        if self.value < self.ceiling:
            old = self.value
            self.value = round(min(self.ceiling, self.value + self.step_up), 2)
            log.info("adaptive wayback pacing: %.1fs -> %.1fs (throttled)", old, self.value)

    def on_clean(self) -> None:
        """A fetch succeeded with no throttling — ease back down after a clean streak."""
        self._clean += 1
        if self._clean >= self.ease_after and self.value > self.base:
            old = self.value
            self.value = round(max(self.base, self.value - self.ease_step), 2)
            self._clean = 0
            log.info("adaptive wayback pacing: %.1fs -> %.1fs (%d clean fetches)",
                     old, self.value, self.ease_after)


def _retry_sleep(attempt: int, backoff: float) -> float:
    base = min(backoff * (2 ** attempt), MAX_FETCH_BACKOFF)
    jitter = random.uniform(0.0, min(1.0, base * 0.1))
    return base + jitter


def _fetch_snapshot_resp(
    entry: dict,
    delay: float,
    timeout: float,
    client: Optional[httpx.Client],
    retries: int,
    backoff: float,
    pacer: Optional[AdaptivePacer] = None,
) -> httpx.Response:
    """Politely fetch one archived capture, riding out transient Archive throttling —
    connection refusals (`ConnectError`) and 429/5xx — with capped exponential backoff.
    The Archive periodically refuses a burst then recovers within a minute or so, so we
    retry long enough to outlast that window instead of surfacing a one-off refusal as a
    failed speech. Non-retryable statuses (e.g. 404) raise immediately. Returns the raw
    Response so callers can take `.text` (HTML) or `.content` (PDF).

    If a `pacer` is given, the pre-fetch pause is the pacer's current (auto-tuning) delay
    instead of the fixed `delay`, and the pacer is told whether this fetch was clean or
    throttled so it can converge on the Archive's tolerated rate."""
    time.sleep(pacer.value if pacer is not None else delay)
    close_client = client is None
    client = client or create_client(timeout=timeout)
    url = snapshot_url(entry)
    throttled = False  # did THIS fetch hit any retryable throttling? (drives the pacer, once)
    try:
        for attempt in range(retries):
            try:
                resp = client.get(url)
                resp.raise_for_status()
                resp.read()  # materialize the body before the client may be closed
                if pacer is not None:
                    pacer.on_throttle() if throttled else pacer.on_clean()
                return resp
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError):
                    status = exc.response.status_code if exc.response is not None else None
                    if status not in RETRYABLE_STATUS_CODES:
                        raise  # a real 404/403 etc. — not throttling, don't pace on it
                throttled = True
                if attempt >= retries - 1:
                    if pacer is not None:
                        pacer.on_throttle()  # gave up after full backoff — slow down for the next
                    raise
                wait = _retry_sleep(attempt, backoff)
                # Distinguish real rate-limiting (429 -> raise wayback_delay) from a
                # transient Archive hiccup (5xx, harmless) — the exception type alone
                # ("HTTPStatusError") hides the one number you'd tune pacing on (issue #67).
                if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                    reason = f"HTTP {exc.response.status_code}"
                else:
                    reason = type(exc).__name__
                log.info("wayback throttled (%s); retry %d/%d in %.0fs: %s",
                         reason, attempt + 1, retries, wait, url)
                time.sleep(wait)
    finally:
        if close_client:
            client.close()


def fetch_snapshot(
    entry: dict,
    delay: float = DEFAULT_FETCH_DELAY,
    timeout: float = 60.0,
    client: Optional[httpx.Client] = None,
    retries: int = DEFAULT_FETCH_RETRIES,
    backoff: float = DEFAULT_FETCH_BACKOFF,
    pacer: Optional[AdaptivePacer] = None,
) -> str:
    """Fetch one archived capture's HTML (see :func:`_fetch_snapshot_resp`)."""
    return _fetch_snapshot_resp(entry, delay, timeout, client, retries, backoff, pacer).text


def fetch_snapshot_bytes(
    entry: dict,
    delay: float = DEFAULT_FETCH_DELAY,
    timeout: float = 60.0,
    client: Optional[httpx.Client] = None,
    retries: int = DEFAULT_FETCH_RETRIES,
    backoff: float = DEFAULT_FETCH_BACKOFF,
    pacer: Optional[AdaptivePacer] = None,
) -> tuple[str, bytes]:
    """Fetch one archived capture as raw bytes, returning (content_type, content) — for
    PDF captures, where the archive stored the original binary."""
    resp = _fetch_snapshot_resp(entry, delay, timeout, client, retries, backoff, pacer)
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    return ctype, resp.content
