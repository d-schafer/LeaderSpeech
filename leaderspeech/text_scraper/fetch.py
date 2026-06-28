"""Fetching with manners.

One Fetcher handles either static HTML (httpx) or JavaScript-rendered pages
(Playwright). It centralizes the politeness and robustness patterns that were
scattered and copy-pasted across the old R scrapers: a randomized pause before
every request, a bot-identifying User-Agent, an optional robots.txt check, and
retries with exponential backoff.
"""

from __future__ import annotations

import random
import time
import urllib.robotparser
from typing import Optional
from urllib.parse import urlparse

import httpx

USER_AGENT = (
    "LeaderSpeechBot/0.1 "
    "(+https://github.com/d-schafer/LeaderSpeech; academic research; "
    "contact via GitHub issues)"
)


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
        user_agent: str = USER_AGENT,
    ):
        self.renderer = renderer
        self.delay_range = delay_range
        self.pause_every = pause_every
        self.pause_seconds = pause_seconds
        self.retries = retries
        self.backoff = backoff
        self.timeout = timeout
        self.user_agent = user_agent
        self._count = 0
        self._robots = RobotsCache(user_agent) if respect_robots else None
        self._client: Optional[httpx.Client] = None
        self._pw = None
        self._browser = None
        self._page = None

        if renderer == "static":
            self._client = httpx.Client(
                headers={"User-Agent": user_agent},
                follow_redirects=True,
                timeout=timeout,
            )
        else:
            self._init_browser()

    def _init_browser(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._page = self._browser.new_page(user_agent=self.user_agent)

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
        last_err: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                if self.renderer == "static":
                    resp = self._client.get(url)
                    resp.raise_for_status()
                    return resp.text
                self._page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
                return self._page.content()
            except Exception as e:  # network error, timeout, HTTP error
                last_err = e
                if attempt < self.retries:
                    time.sleep(self.backoff * (2 ** (attempt - 1)))  # exponential backoff
        raise RuntimeError(f"Failed after {self.retries} attempts: {url} :: {last_err}")

    def close(self):
        if self._client:
            self._client.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
