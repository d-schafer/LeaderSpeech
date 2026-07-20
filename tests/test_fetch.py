"""Header construction: browser-like defaults that clear WAFs, plus the opt-in
User-Agent override for sites that hard-block the honest bot UA."""

from leaderspeech.text_scraper.fetch import USER_AGENT, build_headers


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
