"""Fetching with manners.

One Fetcher handles either static HTML (httpx) or JavaScript-rendered pages
(Playwright). It centralizes the politeness and robustness patterns that were
scattered and copy-pasted across the old R scrapers: a randomized pause before
every request, a bot-identifying User-Agent, an optional robots.txt check, and
retries with exponential backoff.
"""

from __future__ import annotations

import os
import random
import re
import time
import urllib.robotparser
from typing import Optional
from urllib.parse import urlparse

import httpx

from .block import BlockPageError, looks_like_block_page

# `charset=` inside a <meta> in the first few KB of an HTML document. Covers both spellings:
#   <meta charset="windows-1250">
#   <meta http-equiv="Content-Type" content="text/html; charset=windows-1250">
_META_CHARSET = re.compile(rb"""charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)


def decode_html(resp: httpx.Response) -> str:
    """Decode an HTML response the way a browser does, not the way httpx does.

    httpx takes `.encoding` from the Content-Type HEADER and falls back to UTF-8; it never
    reads the document's own `<meta charset>`. Legacy government sites and site mirrors
    routinely serve `Content-Type: text/html` with NO charset and non-UTF-8 bytes, and the
    result is silent mojibake — not an error, just a body full of U+FFFD that flows all the way
    into the corpus and out through the translation stage.

    Worked example (issue found 2026-08-14): archiv.prezident.sk is an HTTrack mirror of the
    pre-2019 Slovak presidency site. Its pages are windows-1250 and declare it twice in
    <meta http-equiv>, but the header says only `text/html`, so a speech title came back as
    'Pr�hovor prezidenta SR Ivana Ga�parovi�a'.

    Precedence is deliberate and matches the browser: an explicit HEADER charset wins (the
    server is authoritative about its own bytes), and the <meta> is consulted only when the
    header is silent.
    """
    # getattr, not attribute access: the test-suite (and any caller with a stub client) hands in
    # a minimal response object that only has `.text`. A charset sniff is an enhancement, so a
    # response that cannot answer simply gets httpx's own decoding.
    if getattr(resp, "charset_encoding", None):   # the header named a charset — trust it
        return resp.text
    raw = getattr(resp, "content", b"")
    m = _META_CHARSET.search(raw[:4096]) if isinstance(raw, (bytes, bytearray)) else None
    if m:
        enc = m.group(1).decode("ascii", "ignore")
        try:
            return raw.decode(enc, errors="replace")
        except LookupError:              # a charset Python does not know; fall through
            pass
    return resp.text

# After DOM-ready, how long to let the network settle so SPA/AJAX content can paint. Bounded so a
# CF challenge / analytics polling (which never reach networkidle) can't hang the fetch.
_NETWORKIDLE_BONUS_MS = 10000

# Title/markers of a Cloudflare (or similar) JS interstitial that SELF-CLEARS a few seconds after
# the page first reaches networkidle. We poll for these to disappear so a `js`/`cdp` fetch returns
# the real page, not the challenge shell (issue #61). NOT included: "attention required" / "sorry,
# you have been blocked" (CF-1020) — those are hard denials that never clear by waiting, so we don't
# burn time polling them (they need renderer: cdp / a real browser session instead — issue #62).
_CHALLENGE_MARKERS = (
    "just a moment",
    "checking your browser",
    "verifying you are human",
    "verify you are human",
    "un momento",
)
_CHALLENGE_MAX_WAIT = 15.0   # seconds to let an interstitial self-clear before giving up
_DEFAULT_CDP_ENDPOINT = "http://localhost:9222"

USER_AGENT = (
    "LeaderSpeechBot/0.1 "
    "(+https://github.com/d-schafer/LeaderSpeech; academic research; "
    "contact via GitHub issues)"
)

# Browser-like default headers. A bare User-Agent is enough for most sites, but
# some government CDNs/WAFs (e.g. the SharePoint sites behind the `TS…` anti-bot
# cookie family) return empty page-chrome unless the request also carries Accept /
# Accept-Language — so we send them by default. The api/feed harvesters reuse these.
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def build_headers(user_agent: Optional[str] = None, extra: Optional[dict] = None) -> dict:
    """The default browser-like headers, with `user_agent` substituted (None => the
    default bot UA) and any `extra` overrides merged on top. Shared by the static
    fetcher and the api/feed JSON/XML clients so they all clear the same WAFs."""
    headers = {**DEFAULT_HEADERS, "User-Agent": user_agent or USER_AGENT}
    if extra:
        headers.update(extra)
    return headers


# Where to ask "what IP do my requests come from?". Two providers so one being down
# doesn't cost us the answer; both return the bare address as plain text.
_EGRESS_IP_SERVICES = ("https://api.ipify.org", "https://checkip.amazonaws.com")


def egress_ip(timeout: float = 8.0) -> Optional[str]:
    """The public IP address this process's requests appear to come from, or None.

    Worth logging at the start of a run because the Internet Archive throttles per
    IP: when a campaign is split across several machines to keep each stream polite,
    this is what PROVES the streams are actually on different addresses — and if a
    tunnel or proxy silently drops mid-run, it shows up here instead of surfacing
    six hours later as unexplained throttling.

    Uses a plain httpx.get, so it honors the same HTTPS_PROXY / ALL_PROXY env vars
    every other client in this package honors (httpx defaults to trust_env=True) and
    therefore reports the address the remote host actually sees. Best-effort: it
    never raises and never blocks a scrape on a slow or missing lookup.
    """
    for url in _EGRESS_IP_SERVICES:
        try:
            resp = httpx.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            ip = resp.text.strip()
            if ip:
                return ip
        except Exception:
            continue
    return None


class RobotsCache:
    """Per-host robots.txt lookups. Fails open: if robots can't be read, allow.

    We fetch robots.txt with our own httpx client and User-Agent rather than
    urllib's RobotFileParser.read(): many CDNs 403 urllib's default UA, and a 403
    on robots.txt makes urllib assume "disallow everything" — which would false-block
    sites that are actually fully open (e.g. elysee.fr).
    """

    def __init__(self, user_agent: str = USER_AGENT):
        self.user_agent = user_agent
        self._parsers: dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._parsers:
            rp = None
            try:
                resp = httpx.get(
                    host + "/robots.txt",
                    headers={"User-Agent": self.user_agent},
                    follow_redirects=True,
                    timeout=15.0,
                )
                if resp.status_code == 200 and resp.text.strip():
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(resp.text.splitlines())
                # any non-200 (missing, 403, etc.) -> fail open (rp stays None)
            except Exception:
                rp = None
            self._parsers[host] = rp
        rp = self._parsers[host]
        if rp is None:
            return True
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            return True


class Fetcher:
    def __init__(
        self,
        renderer: str = "static",
        delay_range: tuple[float, float] = (0.0, 0.0),
        pause_every: int = 50,
        pause_seconds: float = 5.0,
        retries: int = 3,
        backoff: float = 5.0,
        timeout: float = 30.0,
        respect_robots: bool = False,
        verify_ssl: bool = True,
        user_agent: Optional[str] = None,
        js_settle: float = 0.0,
        js_context_recycle: int = 0,
        cdp_endpoint: Optional[str] = None,
        block_page: bool = True,
        block_page_patterns: Optional[list[str]] = None,
    ):
        self.renderer = renderer
        self.delay_range = delay_range
        self.pause_every = pause_every
        self.pause_seconds = pause_seconds
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        # Detect WAF/block pages served with HTTP 200 and treat them as fetch failures
        # (issue #65). On by default; a recipe may disable it (block_page: false) or add
        # signatures (block_page_patterns) for a site whose real content matches.
        self.block_page = block_page
        self.block_page_patterns = block_page_patterns or None
        # Extra fixed wait after a js/cdp page load (rarely needed; the challenge auto-wait is
        # separate and always on).
        self.js_settle = js_settle
        # Recycle the headless browser CONTEXT every N page fetches (0 = never). Some WAFs
        # (gov.il's Cloudflare) flag a context with a CF-1020 'you have been blocked' after the
        # first request, cascading to block every later fetch on that context — but a fresh
        # context (cheap; same browser) clears it. `1` = a new context per page (issue #69).
        self.js_context_recycle = js_context_recycle
        self._ctx_uses = 0
        self._context = None
        # renderer: cdp -> the DevTools endpoint of a user-launched Chrome. Recipe field wins,
        # else the env var, else localhost:9222.
        self.cdp_endpoint = cdp_endpoint or os.environ.get(
            "LEADERSPEECH_CDP_ENDPOINT", _DEFAULT_CDP_ENDPOINT
        )
        # None => the honest default bot UA; a recipe may override it to clear a WAF
        # that hard-blocks the bot UA (e.g. some gov SharePoint sites).
        self.user_agent = user_agent or USER_AGENT
        self._count = 0
        self._robots = RobotsCache(self.user_agent) if respect_robots else None
        self._client: Optional[httpx.Client] = None
        # A plain httpx client for raw-byte fetches (PDFs), built lazily. In 'js' mode the
        # main client is Playwright, which can't cleanly download a binary — so PDF bytes
        # always go over httpx, even under a js recipe.
        self._bytes_client: Optional[httpx.Client] = None
        self._pw = None
        self._browser = None
        self._page = None

        if renderer == "static":
            self._client = httpx.Client(
                headers=build_headers(self.user_agent),
                follow_redirects=True,
                timeout=timeout,
                verify=verify_ssl,  # many gov sites have broken cert chains
            )
        else:
            self._init_browser()

    def _init_browser(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        if self.renderer == "cdp":
            # Attach to a Chrome the user launched with --remote-debugging-port. That real browser
            # (real fingerprint, no --enable-automation, navigator.webdriver=false, plus any CF
            # clearance the user already earned) passes CF bot checks that headless/headful
            # Playwright-launched Chromium cannot (issue #62). Reuse its existing context so we
            # inherit its cookies; don't override the UA (Chrome's own UA is what CF trusts).
            self._browser = self._pw.chromium.connect_over_cdp(self.cdp_endpoint)
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else self._browser.new_context()
            )
            self._page = self._context.new_page()
            return
        self._browser = self._pw.chromium.launch(headless=True)
        self._new_context_page()

    def _new_context_page(self):
        """Open a fresh headless browser context + page. Isolating requests in a new context
        clears a CF-1020 that flags one session (issue #69) — see :attr:`js_context_recycle`."""
        self._context = self._browser.new_context(
            user_agent=self.user_agent,
            ignore_https_errors=not self.verify_ssl,
            # chromium sets its own Accept/UA; nudge Accept-Language so WAFs that key
            # on it (the same ones the static path's DEFAULT_HEADERS placate) behave.
            extra_http_headers={"Accept-Language": DEFAULT_HEADERS["Accept-Language"]},
        )
        self._page = self._context.new_page()

    def _recycle_context(self) -> bool:
        """Close the current headless context+page and open a fresh one. Only for `renderer: js`
        (a launched browser) — `cdp` reuses the user's real, CF-cleared context, which must not be
        torn down. Returns True if it recycled. Resets the per-context fetch counter."""
        if self.renderer != "js" or self._browser is None:
            return False
        for obj in (self._page, self._context):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        self._new_context_page()
        self._ctx_uses = 0
        return True

    def _maybe_recycle_context(self):
        """Proactively recycle the context every `js_context_recycle` fetches, so a long-lived
        context never accumulates enough requests to trip a CF-1020 in the first place."""
        if not (self.js_context_recycle and self.renderer == "js" and self._browser is not None):
            return
        if self._ctx_uses >= self.js_context_recycle:
            self._recycle_context()
        self._ctx_uses += 1

    def _settle_challenge(self):
        """After a js/cdp navigation, give a self-clearing CF 'Just a moment' interstitial time to
        redirect to the real page, and honor any fixed js_settle wait. Cheap when there's no
        challenge: one title read, then return. Only an actual interstitial incurs the poll (issue
        #61). Hard denials (CF-1020 'Attention Required') are not polled — they never clear by
        waiting; use renderer: cdp for those."""
        if self.js_settle > 0:
            self._page.wait_for_timeout(int(self.js_settle * 1000))
        deadline = time.monotonic() + _CHALLENGE_MAX_WAIT
        while time.monotonic() < deadline:
            try:
                title = (self._page.title() or "").lower()
            except Exception:
                return
            if not any(m in title for m in _CHALLENGE_MARKERS):
                return
            self._page.wait_for_timeout(1000)

    @property
    def page(self):
        """The Playwright page (only in 'js' mode), for click-pagination."""
        return self._page

    def _pace(self):
        """Pacing, once per URL: a short breather every `pause_every` requests, plus an
        optional small per-request jitter. Light by default — bump the knobs for a
        server that pushes back."""
        self._count += 1
        if self.pause_every and self._count % self.pause_every == 0:
            time.sleep(self.pause_seconds)
        lo, hi = self.delay_range
        if hi > 0:
            time.sleep(random.uniform(lo, hi))

    def get(self, url: str) -> str:
        """Fetch one URL, returning HTML. Raises after exhausting retries."""
        if self._robots is not None and not self._robots.allowed(url):
            raise PermissionError(f"Blocked by robots.txt: {url}")

        self._pace()
        self._maybe_recycle_context()  # proactive per-URL context recycle (js) — issue #69
        last_err: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                if self.renderer == "static":
                    resp = self._client.get(url)
                    resp.raise_for_status()
                    return self._guard_block(decode_html(resp), url)
                # js / cdp: load the DOM first (fires even on CF interstitials and sites with
                # persistent polling), then give the network a SHORT window to settle so SPA/AJAX
                # content can paint — but never hang on it, because CF challenges/analytics never
                # reach networkidle (that hang made gg.govt.nz time out 3x -> 0 links). Finally let
                # any CF "Just a moment" interstitial self-clear (issue #61) before reading the DOM.
                self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                try:
                    self._page.wait_for_load_state("networkidle", timeout=_NETWORKIDLE_BONUS_MS)
                except Exception:
                    pass
                self._settle_challenge()
                return self._guard_block(self._page.content(), url)
            except BlockPageError as e:
                # A CF-1020 ("you have been blocked") that flagged this context won't clear by
                # retrying the SAME context — swap in a fresh one and retry at once (the recycle
                # is the remedy, not a wait). Static/cdp can't recycle -> fall through to backoff.
                last_err = e
                if self._recycle_context():
                    continue
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** (attempt - 1)))
            except Exception as e:  # network error, timeout, HTTP error
                last_err = e
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** (attempt - 1)))  # exponential backoff
        # `from last_err` keeps the ORIGINAL exception reachable as __cause__. The message is
        # unchanged, but callers can now ask *why* it failed instead of regexing the string —
        # paginate.py uses it to tell "the pager ran off the end" (404) from "the listing is
        # broken" (timeout/5xx), which used to look identical. See paginate._http_status.
        raise RuntimeError(f"Failed after {self.retries} attempts: {url} :: {last_err}") from last_err

    def _guard_block(self, html: str, url: str) -> str:
        """Raise BlockPageError if `html` is a WAF/block/challenge page served with HTTP
        200 (issue #65). Raised INSIDE get()'s retry loop, so retries/backoff fire (which
        clears a transient rate-limit block) and, once exhausted, the URL surfaces as an
        ordinary fetch failure — logged in _errors.csv and retryable via --retry-failed —
        instead of being written as a ~460-char junk 'speech'."""
        if self.block_page and looks_like_block_page(html, self.block_page_patterns):
            raise BlockPageError(f"WAF/block page served with HTTP 200: {url}")
        return html

    def _byte_client(self) -> httpx.Client:
        """The httpx client used for raw-byte fetches: the static client if we have one,
        else a lazily-built plain client (js mode / no static client)."""
        if self._client is not None:
            return self._client
        if self._bytes_client is None:
            self._bytes_client = httpx.Client(
                headers=build_headers(self.user_agent),
                follow_redirects=True,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
        return self._bytes_client

    def get_bytes(self, url: str) -> tuple[str, bytes]:
        """Fetch one URL as raw bytes, returning (content_type, content). Used for PDFs
        and any non-HTML payload. Mirrors get()'s robots check, pacing, and retry/backoff,
        but always goes over HTTP (httpx) so it works even in 'js' mode."""
        if self._robots is not None and not self._robots.allowed(url):
            raise PermissionError(f"Blocked by robots.txt: {url}")

        self._pace()
        client = self._byte_client()
        last_err: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = client.get(url)
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                return ctype, resp.content
            except Exception as e:
                last_err = e
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** (attempt - 1)))
        raise RuntimeError(f"Failed after {self.retries} attempts: {url} :: {last_err}") from last_err

    def close(self):
        if self._client:
            self._client.close()
        if self._bytes_client:
            self._bytes_client.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
