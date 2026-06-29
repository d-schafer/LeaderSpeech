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
