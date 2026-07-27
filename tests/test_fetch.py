"""Header construction: browser-like defaults that clear WAFs, plus the opt-in
User-Agent override for sites that hard-block the honest bot UA."""

import pytest

from leaderspeech.text_scraper.fetch import USER_AGENT, Fetcher, build_headers
from leaderspeech.text_scraper.block import BlockPageError
from tests.test_block import CLOUDFLARE_BLOCK, REAL_SPEECH


def test_default_headers_include_accept_and_accept_language():
    h = build_headers()
    assert h["User-Agent"] == USER_AGENT
    assert "Accept" in h and "Accept-Language" in h


def test_none_user_agent_falls_back_to_default():
    assert build_headers(None)["User-Agent"] == USER_AGENT


def test_user_agent_override_and_extra_headers():
    h = build_headers("Mozilla/5.0 (compatible)", extra={"Accept": "application/json"})
    assert h["User-Agent"] == "Mozilla/5.0 (compatible)"
    assert h["Accept"] == "application/json"          # extra overrides the default Accept
    assert h["Accept-Language"]                        # default still present


def test_fetcher_stores_js_settle_and_resolves_cdp_endpoint(monkeypatch):
    """The static Fetcher (no browser launched) still plumbs the new js/cdp knobs:
    js_settle is stored, and cdp_endpoint resolves recipe-value > env var > localhost:9222."""
    from leaderspeech.text_scraper.fetch import Fetcher, _DEFAULT_CDP_ENDPOINT

    monkeypatch.delenv("LEADERSPEECH_CDP_ENDPOINT", raising=False)
    f = Fetcher(renderer="static", js_settle=1.5)
    assert f.js_settle == 1.5
    assert f.cdp_endpoint == _DEFAULT_CDP_ENDPOINT  # default localhost:9222
    f.close()

    monkeypatch.setenv("LEADERSPEECH_CDP_ENDPOINT", "http://envhost:9333")
    f = Fetcher(renderer="static")
    assert f.cdp_endpoint == "http://envhost:9333"  # env var wins over the default
    f.close()

    f = Fetcher(renderer="static", cdp_endpoint="http://explicit:1234")
    assert f.cdp_endpoint == "http://explicit:1234"  # explicit arg wins over env
    f.close()


# --- issue #65: block-page guard in Fetcher.get -----------------------------------------

class _FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeClient:
    """Stands in for the static httpx client: returns a fixed body and counts calls."""

    def __init__(self, text):
        self.text = text
        self.calls = 0

    def get(self, url):
        self.calls += 1
        return _FakeResponse(self.text)

    def close(self):
        pass


def _static_fetcher(text, **kw):
    # retries=2 with backoff=0 so a failure retries (observably) but never sleeps.
    f = Fetcher(renderer="static", retries=2, backoff=0.0, pause_every=0, **kw)
    f._client = _FakeClient(text)
    return f


def test_get_raises_on_block_page_and_retries():
    """A Cloudflare block page served as 200 must become a fetch FAILURE, not a return
    value — and it must exhaust the retry budget (so a transient rate-limit block gets a
    second chance)."""
    f = _static_fetcher(CLOUDFLARE_BLOCK)
    with pytest.raises(RuntimeError) as ei:
        f.get("https://gov.example/speech")
    assert "WAF/block page" in str(ei.value)   # the BlockPageError message is surfaced
    assert f._client.calls == 2                 # retried the full budget
    f.close()


def test_get_returns_a_real_page_untouched():
    f = _static_fetcher(REAL_SPEECH)
    assert f.get("https://gov.example/speech") == REAL_SPEECH
    assert f._client.calls == 1                 # no retry — it succeeded first time
    f.close()


def test_block_guard_can_be_disabled_per_recipe():
    """block_page: false -> the block page is returned verbatim (the escape hatch for a
    site whose legitimate content matches a signature)."""
    f = _static_fetcher(CLOUDFLARE_BLOCK, block_page=False)
    assert f.get("https://gov.example/speech") == CLOUDFLARE_BLOCK
    f.close()


def test_block_guard_raises_block_page_error_directly():
    """The guard helper raises the typed error before the retry wrapper converts it."""
    f = _static_fetcher(CLOUDFLARE_BLOCK)
    with pytest.raises(BlockPageError):
        f._guard_block(CLOUDFLARE_BLOCK, "https://gov.example/speech")
    f.close()


# --- issue #69: browser-context recycling (fake browser; no real Playwright) --------------

class _FakePage:
    def __init__(self, html):
        self.html = html
        self.closed = False

    def goto(self, url, wait_until=None, timeout=None):
        pass

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def title(self):
        return "ok"                       # not a challenge marker -> _settle_challenge returns at once

    def content(self):
        return self.html

    def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self, contexts):
        self._q = list(contexts)
        self.made = []

    def new_context(self, **kw):
        c = self._q.pop(0)
        self.made.append(c)
        return c

    def close(self):
        pass


def _js_fetcher(**kw):
    # build a static Fetcher (no real browser launch), then flip to js mode with fakes injected
    f = Fetcher(renderer="static", retries=3, backoff=0.0, pause_every=0, **kw)
    f.renderer = "js"
    return f


def test_js_block_recycles_context_and_recovers():
    """A CF-1020 block on a reused context is not retried on the SAME context — the Fetcher
    swaps in a fresh context and the retry succeeds (issue #69)."""
    f = _js_fetcher()
    p0, ctx0 = _FakePage(CLOUDFLARE_BLOCK), None
    p1 = _FakePage(REAL_SPEECH)
    ctx0 = _FakeContext(p0)
    ctx1 = _FakeContext(p1)
    f._browser = _FakeBrowser([ctx1])      # the fresh context handed out on recycle
    f._context, f._page = ctx0, p0

    assert f.get("https://gov.example/x") == REAL_SPEECH
    assert ctx0.closed is True             # the flagged context was torn down
    assert f._page is p1                   # now serving from the fresh context
    assert f._browser.made == [ctx1]


def test_js_context_recycle_opens_fresh_context_per_page():
    """js_context_recycle=1 -> a new context for every page after the first (proactive)."""
    f = _js_fetcher(js_context_recycle=1)
    ctxs = [_FakeContext(_FakePage(REAL_SPEECH)) for _ in range(3)]
    f._browser = _FakeBrowser(ctxs[1:])    # contexts 1 and 2 are created on recycle
    f._context, f._page = ctxs[0], ctxs[0].page
    f._ctx_uses = 0

    f.get("https://x/1")                   # uses the initial context (no recycle)
    f.get("https://x/2")                   # recycle -> ctx1
    f.get("https://x/3")                   # recycle -> ctx2
    assert f._browser.made == ctxs[1:]     # exactly two recycles
    assert ctxs[0].closed and ctxs[1].closed and not ctxs[2].closed


def test_recycle_is_noop_without_the_knob_and_for_non_js():
    # default (js_context_recycle=0): no proactive recycling
    f = _js_fetcher()
    ctxs = [_FakeContext(_FakePage(REAL_SPEECH)) for _ in range(2)]
    f._browser = _FakeBrowser(ctxs[1:])
    f._context, f._page = ctxs[0], ctxs[0].page
    f.get("https://x/1"); f.get("https://x/2")
    assert f._browser.made == []           # never recycled
    # _recycle_context only acts for renderer=js with a launched browser
    stat = Fetcher(renderer="static")
    assert stat._recycle_context() is False
    stat.close()
