import logging

import httpx

from leaderspeech.text_scraper import wayback


def test_list_snapshots_strips_trailing_star(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [["timestamp", "original"], ["20080101", "https://example.org/a"]]

    def fake_get(url, params, headers, timeout):
        captured["url"] = url
        captured["params"] = params
        return Resp()

    monkeypatch.setattr(wayback.httpx, "get", fake_get)

    snaps = wayback.list_snapshots("casarosada.gob.ar/informacion/discursos/*", match_type="prefix")

    assert snaps == [{"timestamp": "20080101", "original": "https://example.org/a"}]
    assert captured["params"]["url"] == "casarosada.gob.ar/informacion/discursos/"
    assert captured["params"]["matchType"] == "prefix"


def test_best_capture_picks_largest_200(monkeypatch):
    # #70: choose the most complete capture (largest length among 200s), disable collapse,
    # and filter to statuscode:200 — so a truncated 1 MB partial doesn't win.
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return [
                ["timestamp", "original", "statuscode", "length"],
                ["20200101000000", "https://x.gov/a.pdf", "200", "1048576"],   # truncated partial
                ["20200601000000", "https://x.gov/a.pdf", "200", "6000000"],   # complete
                ["20200701000000", "https://x.gov/a.pdf", "404", "512"],       # excluded by filter server-side
            ]

    def fake_get(url, params, headers, timeout):
        captured["params"] = params
        return Resp()

    monkeypatch.setattr(wayback.httpx, "get", fake_get)
    best = wayback.best_capture("https://x.gov/a.pdf")

    assert best["length"] == "6000000"                       # the complete capture
    assert best["timestamp"] == "20200601000000"
    # exact single-URL query, statuscode:200 filter, and NO collapse (would hide the big dup).
    # With filters present, list_snapshots passes a list of (key, value) pairs, not a dict.
    params = captured["params"]
    pairs = list(params.items()) if isinstance(params, dict) else list(params)
    keys = [k for k, _ in pairs]
    assert ("matchType", "exact") in pairs
    assert "collapse" not in keys
    assert ("filter", "statuscode:200") in pairs


def test_best_capture_returns_none_when_no_captures(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return []                                        # CDX has nothing for this URL

    monkeypatch.setattr(wayback.httpx, "get", lambda url, params, headers, timeout: Resp())
    assert wayback.best_capture("https://x.gov/missing.pdf") is None


def test_filter_entries_for_recipe_drops_listing_and_query_pages():
    entries = [
        {"original": "https://www.casarosada.gob.ar/informacion/discursos"},
        {"original": "https://www.casarosada.gob.ar/informacion/discursos?start=40"},
        {"original": "https://www.casarosada.gob.ar/informacion/discursos/18-nuestro-pais/galeria-de-presidentes/1"},
        {"original": "https://www.casarosada.gob.ar/informacion/discursos/16462-blank-35472369"},
        {"original": "https://www.casarosada.gob.ar/informacion/discursos/2"},
    ]

    filtered = wayback.filter_entries_for_recipe(entries, r"/informacion/discursos/\d+[^/]*$")

    assert [entry["original"] for entry in filtered] == [
        "https://www.casarosada.gob.ar/informacion/discursos/16462-blank-35472369",
        "https://www.casarosada.gob.ar/informacion/discursos/2",
    ]


def test_filter_entries_drops_index_from_start_urls_even_with_loose_pattern():
    # The recipe's start_urls (a CDX prefix) define the index path to drop, so the
    # bare index and its ?page=/?start= variants are removed even with a loose
    # link_pattern — and no site-specific paths are hardcoded in the engine.
    entries = [
        {"original": "https://x.gov/discursos"},
        {"original": "https://x.gov/discursos?page=2"},
        {"original": "https://x.gov/discursos?start=40"},
        {"original": "https://x.gov/discursos/5"},
    ]
    filtered = wayback.filter_entries_for_recipe(
        entries, r"/discursos", start_urls=["x.gov/discursos"]
    )
    assert [e["original"] for e in filtered] == ["https://x.gov/discursos/5"]


def test_fetch_snapshot_retries_transient_connect_error(monkeypatch):
    entry = {
        "timestamp": "20080101",
        "original": "https://www.casarosada.gob.ar/informacion/discursos/2",
    }
    request = httpx.Request("GET", wayback.snapshot_url(entry))
    sleeps = []

    class Client:
        def __init__(self):
            self.calls = 0

        def get(self, url):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError("boom", request=request)
            return httpx.Response(200, text="ok", request=request)

        def close(self):
            pass

    client = Client()
    monkeypatch.setattr(wayback.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(wayback.random, "uniform", lambda a, b: 0.0)

    assert wayback.fetch_snapshot(entry, delay=0.0, client=client) == "ok"
    assert client.calls == 2
    assert sleeps == [0.0, 5.0]


def test_retry_log_shows_http_status_for_429(monkeypatch, caplog):
    # The retry log must print the HTTP status (429 = real rate-limiting → raise the
    # delay) rather than the bare exception type, which reads the same for 429 and 5xx
    # (issue #67).
    entry = {"timestamp": "20080101", "original": "https://x.gov/a"}
    request = httpx.Request("GET", wayback.snapshot_url(entry))

    class Client:
        def __init__(self):
            self.calls = 0

        def get(self, url):
            self.calls += 1
            if self.calls == 1:
                return httpx.Response(429, request=request)  # .raise_for_status() -> HTTPStatusError
            return httpx.Response(200, text="ok", request=request)

        def close(self):
            pass

    monkeypatch.setattr(wayback.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(wayback.random, "uniform", lambda a, b: 0.0)

    with caplog.at_level(logging.INFO, logger=wayback.log.name):
        assert wayback.fetch_snapshot(entry, delay=0.0, client=Client()) == "ok"

    throttle_logs = [r.getMessage() for r in caplog.records if "wayback throttled" in r.getMessage()]
    assert throttle_logs and "HTTP 429" in throttle_logs[0]


def test_retry_log_shows_exception_type_for_transport_error(monkeypatch, caplog):
    # Transport errors have no HTTP status, so the log falls back to the exception type.
    entry = {"timestamp": "20080101", "original": "https://x.gov/a"}
    request = httpx.Request("GET", wayback.snapshot_url(entry))

    class Client:
        def __init__(self):
            self.calls = 0

        def get(self, url):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ConnectError("boom", request=request)
            return httpx.Response(200, text="ok", request=request)

        def close(self):
            pass

    monkeypatch.setattr(wayback.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(wayback.random, "uniform", lambda a, b: 0.0)

    with caplog.at_level(logging.INFO, logger=wayback.log.name):
        assert wayback.fetch_snapshot(entry, delay=0.0, client=Client()) == "ok"

    throttle_logs = [r.getMessage() for r in caplog.records if "wayback throttled" in r.getMessage()]
    assert throttle_logs and "ConnectError" in throttle_logs[0]
