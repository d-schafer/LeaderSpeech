import logging

import httpx
import pytest

from leaderspeech.text_scraper import wayback


class _Stream:
    """Stands in for `httpx.Client.stream()` — a context manager yielding the response
    (or raising, for the transport-error fakes). Bodies are read via `iter_bytes()`,
    which pre-built `httpx.Response` objects support."""

    def __init__(self, result):
        self._result = result

    def __enter__(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    def __exit__(self, *exc_info):
        return False


class _FakeResp:
    """Duck-typed stand-in for an UNREAD streaming response.

    `httpx.Response` can't be subclassed for this: its constructor calls `.read()`,
    which drains `iter_bytes()` eagerly — so an override modelling an endless body
    hangs at construction rather than in the code under test. Only the attributes
    `_read_capped`/`_rebuild_response` actually touch are provided."""

    def __init__(self, chunks, headers=None, status_code=200, request=None):
        self._chunks = chunks          # iterable (may be an endless generator)
        self.headers = httpx.Headers(headers or {})
        self.status_code = status_code
        self.request = request

    def raise_for_status(self):
        return self

    def iter_bytes(self, chunk_size=None):
        return iter(self._chunks)


def test_rebuild_response_survives_a_non_ascii_header_value():
    """A capture whose response headers carry a raw non-ASCII byte must still yield its body.

    Real case (hun_keh_wayback, 2026-08): keh.hu set a cookie named after the article slug, so
    the Archive echoed `x-archive-orig-set-cookie: kehStat1662-..._lelkiismerete_<en-dash>_...`.
    Rebuilding from `.multi_items()` handed httpx a `str`, which it re-encodes as ASCII ->
    UnicodeEncodeError, and three speeches were recorded as failures instead of scraped."""
    body = "<html><body>beszéd</body></html>".encode("utf-8")
    headers = [
        (b"content-type", b"text/html; charset=utf-8"),
        (b"x-archive-orig-set-cookie", "kehStat_lelkiismerete_–_Mindszenty".encode("utf-8")),
        (b"content-length", b"999"),          # must still be dropped
        (b"content-encoding", b"gzip"),       # must still be dropped
    ]
    resp = _FakeResp([body], headers=headers, request=httpx.Request("GET", "https://x.test/a"))

    out = wayback._rebuild_response(resp, body)

    assert out.status_code == 200
    assert out.text == "<html><body>beszéd</body></html>"      # charset handling preserved
    # the denylist drops the STALE values; httpx then recomputes content-length from the
    # real body, which is the whole reason they are stripped
    assert out.headers["content-length"] == str(len(body)) != "999"
    assert "content-encoding" not in out.headers
    assert out.headers.raw[1][1] == "kehStat_lelkiismerete_–_Mindszenty".encode("utf-8")


def test_rebuild_response_keeps_a_legacy_charset_for_text():
    """The Content-Type must survive verbatim so a legacy-encoded capture still decodes right
    (the .raw copy must not normalize it)."""
    body = "Ő<b>x</b>".encode("iso-8859-2")
    resp = _FakeResp(
        [body],
        headers=[(b"content-type", b"text/html; charset=iso-8859-2")],
        request=httpx.Request("GET", "https://x.test/a"),
    )
    out = wayback._rebuild_response(resp, body)
    assert out.text == "Ő<b>x</b>"


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


def test_root_addressed_articles_are_dropped_by_default():
    # presidencia.gob.hn 2014–16: WordPress addressed at the ROOT (/?p=N) under a bare-host
    # start_url. Every article's path is "" — the start_url's own — so the default listing
    # drop removes them all. That is the historical behaviour and stays the default.
    entries = [{"original": "http://www.presidencia.gob.hn/?p=1520"},
               {"original": "http://www.presidencia.gob.hn/?cat=109&paged=10"}]
    assert wayback.filter_entries_for_recipe(
        entries, r"/\?p=\d+$", start_urls=["presidencia.gob.hn/"]) == []


def test_keep_listing_paths_lets_link_pattern_decide():
    entries = [{"original": "http://www.presidencia.gob.hn/?p=1520"},
               {"original": "http://www.presidencia.gob.hn:80/?p=1520"},       # same page
               {"original": "http://www.presidencia.gob.hn/?cat=109&paged=10"},  # a listing
               {"original": "http://www.presidencia.gob.hn/"}]                   # the home page
    kept = wayback.filter_entries_for_recipe(
        entries, r"/\?p=\d+$", start_urls=["presidencia.gob.hn/"], keep_listing_paths=True)
    assert [e["original"] for e in kept] == ["http://www.presidencia.gob.hn/?p=1520"]


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

        def stream(self, method, url):
            self.calls += 1
            if self.calls == 1:
                return _Stream(httpx.ConnectError("boom", request=request))
            return _Stream(httpx.Response(200, text="ok", request=request))

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

        def stream(self, method, url):
            self.calls += 1
            if self.calls == 1:
                # .raise_for_status() -> HTTPStatusError
                return _Stream(httpx.Response(429, request=request))
            return _Stream(httpx.Response(200, text="ok", request=request))

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

        def stream(self, method, url):
            self.calls += 1
            if self.calls == 1:
                return _Stream(httpx.ConnectError("boom", request=request))
            return _Stream(httpx.Response(200, text="ok", request=request))

        def close(self):
            pass

    monkeypatch.setattr(wayback.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(wayback.random, "uniform", lambda a, b: 0.0)

    with caplog.at_level(logging.INFO, logger=wayback.log.name):
        assert wayback.fetch_snapshot(entry, delay=0.0, client=Client()) == "ok"

    throttle_logs = [r.getMessage() for r in caplog.records if "wayback throttled" in r.getMessage()]
    assert throttle_logs and "ConnectError" in throttle_logs[0]


# --- runaway-body guards --------------------------------------------------------------
# Real case: several english.khamenei.ir speech captures are stored as a redirect chain
# ending at a 1,783,951,360-byte .mp4 on the site's CDN, so following redirects starts
# downloading a 1.78 GB video at Archive speeds. An httpx timeout only bounds the wait for
# the NEXT chunk, so it never fires; one such capture stalled an Iran run for ~3 hours and
# grew the process to 7 GB. Both guards must abort WITHOUT retrying — the redirect target
# is a fixed property of the capture, so retrying just burns the budget six more times.

def _entry():
    return {"timestamp": "20250823", "original": "https://english.khamenei.ir/news/11867/x"}


def test_absurd_content_length_is_refused_before_reading_the_body(monkeypatch):
    entry = _entry()
    request = httpx.Request("GET", wayback.snapshot_url(entry))
    read = []

    def body():
        read.append(1)              # must never run — the header check comes first
        yield b"x"

    class Client:
        def __init__(self): self.calls = 0
        def stream(self, method, url):
            self.calls += 1
            return _Stream(_FakeResp(body(), headers={"content-length": "1783951360"},
                                     request=request))
        def close(self): pass

    monkeypatch.setattr(wayback.time, "sleep", lambda s: None)
    client = Client()

    with pytest.raises(wayback.SnapshotTooLarge) as exc:
        wayback.fetch_snapshot(entry, delay=0.0, client=client)

    assert "1783951360" in str(exc.value)
    assert not read, "body was streamed despite an over-cap Content-Length"
    assert client.calls == 1, "an over-cap capture must not be retried"


def test_body_over_cap_aborts_mid_stream(monkeypatch):
    entry = _entry()
    request = httpx.Request("GET", wayback.snapshot_url(entry))
    yielded = []

    def body():
        # no content-length header, so the cap has to bite while streaming
        while True:
            yielded.append(1)
            yield b"x" * 1024

    class Client:
        def __init__(self): self.calls = 0
        def stream(self, method, url):
            self.calls += 1
            return _Stream(_FakeResp(body(), request=request))
        def close(self): pass

    monkeypatch.setattr(wayback.time, "sleep", lambda s: None)
    client = Client()

    with pytest.raises(wayback.SnapshotTooLarge):
        wayback.fetch_snapshot(entry, delay=0.0, client=client, max_bytes=4096)

    assert len(yielded) == 5, "streaming should stop as soon as the cap is passed"
    assert client.calls == 1


def test_slow_trickle_aborts_on_the_body_deadline(monkeypatch):
    # The real failure mode: bytes keep arriving, so no read timeout ever fires.
    entry = _entry()
    request = httpx.Request("GET", wayback.snapshot_url(entry))
    clock = {"t": 0.0}

    def body():
        while True:
            clock["t"] += 10.0      # 10s per chunk, forever
            yield b"x"

    class Client:
        def __init__(self): self.calls = 0
        def stream(self, method, url):
            self.calls += 1
            return _Stream(_FakeResp(body(), request=request))
        def close(self): pass

    monkeypatch.setattr(wayback.time, "sleep", lambda s: None)
    monkeypatch.setattr(wayback.time, "monotonic", lambda: clock["t"])
    client = Client()

    with pytest.raises(wayback.SnapshotReadTimeout) as exc:
        wayback.fetch_snapshot(entry, delay=0.0, client=client, body_timeout=60.0)

    assert "budget 60s" in str(exc.value)
    assert client.calls == 1, "a stalled capture must not be retried"


def test_rejections_share_a_base_so_run_records_them_as_failures():
    # run.py catches bare Exception, but a caller wanting to single these out should be
    # able to; they must NOT be httpx.TransportError or the retry loop would swallow them.
    for cls in (wayback.SnapshotTooLarge, wayback.SnapshotReadTimeout):
        assert issubclass(cls, wayback.SnapshotRejected)
        assert not issubclass(cls, httpx.TransportError)


def test_decoded_body_is_rewrapped_without_stale_encoding_headers(monkeypatch):
    # httpx hands back DECODED bytes, so replaying content-encoding onto the rebuilt
    # response makes it try to gunzip plain text a second time (DecodingError).
    entry = _entry()
    request = httpx.Request("GET", wayback.snapshot_url(entry))
    body = "سلام".encode("windows-1256")

    class Client:
        def stream(self, method, url):
            # headers advertise gzip (as the wire response did); iter_bytes yields the
            # bytes httpx has ALREADY decoded — exactly what the real streaming API gives
            return _Stream(_FakeResp(
                [body],
                headers={"content-type": "text/html; charset=windows-1256",
                         "content-encoding": "gzip", "content-length": "999999"},
                request=request,
            ))
        def close(self): pass

    monkeypatch.setattr(wayback.time, "sleep", lambda s: None)

    # charset from the header still drives decoding, and no re-gunzip is attempted
    assert wayback.fetch_snapshot(entry, delay=0.0, client=Client()) == "سلام"


# --- adaptive pacer ------------------------------------------------------------------

def test_adaptive_pacer_raises_on_throttle_bounded_by_ceiling():
    p = wayback.AdaptivePacer(base=5.0, ceiling=12.0, step_up=1.5)
    assert p.value == 5.0
    p.on_throttle(); assert p.value == 6.5
    p.on_throttle(); assert p.value == 8.0
    for _ in range(10):
        p.on_throttle()
    assert p.value == 12.0            # never exceeds the ceiling
    assert p.throttle_events == 12


def test_adaptive_pacer_eases_down_after_clean_streak_floored_at_base():
    p = wayback.AdaptivePacer(base=5.0, ceiling=12.0, step_up=2.0, ease_after=3, ease_step=1.0)
    p.on_throttle(); p.on_throttle()          # -> 9.0
    assert p.value == 9.0
    p.on_clean(); p.on_clean()                 # streak not yet reached
    assert p.value == 9.0
    p.on_clean()                               # 3 clean -> ease down one step
    assert p.value == 8.0
    for _ in range(30):                        # a long clean streak eases to the base and stops
        p.on_clean()
    assert p.value == 5.0


def test_fetch_snapshot_pacer_paces_and_records(monkeypatch):
    entry = {"timestamp": "20080101", "original": "https://x.gov/a"}
    request = httpx.Request("GET", wayback.snapshot_url(entry))
    sleeps = []
    monkeypatch.setattr(wayback.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(wayback.random, "uniform", lambda a, b: 0.0)

    class Clean:
        def stream(self, method, url):
            return _Stream(httpx.Response(200, text="ok", request=request))
        def close(self): pass

    class ThrottleOnce:
        def __init__(self): self.calls = 0
        def stream(self, method, url):
            self.calls += 1
            if self.calls == 1:
                return _Stream(httpx.ConnectError("boom", request=request))
            return _Stream(httpx.Response(200, text="ok", request=request))
        def close(self): pass

    p = wayback.AdaptivePacer(base=5.0, ceiling=12.0, step_up=1.5)
    # a clean fetch: pre-fetch pause is the pacer's value (5.0), and it counts as clean (no bump)
    assert wayback.fetch_snapshot(entry, delay=0.0, client=Clean(), pacer=p) == "ok"
    assert sleeps[0] == 5.0
    assert p.value == 5.0 and p.throttle_events == 0
    # a throttled-then-success fetch bumps the pacer exactly once (not once per retry)
    sleeps.clear()
    assert wayback.fetch_snapshot(entry, delay=0.0, client=ThrottleOnce(), pacer=p) == "ok"
    assert p.value == 6.5 and p.throttle_events == 1


# --- query-noise dedupe: one Archive fetch per PAGE ------------------------------------
# The Archive keeps a separate capture for every tracking/UI query string a referrer used.
# collapse=urlkey does NOT merge them, so without this the scraper pays a fetch (and later a
# GPT call) per variant. See wayback.NOISE_PARAMS.


def _e(url):
    return {"original": url, "timestamp": "20200101000000"}


def test_dedupe_collapses_tracking_and_ui_query_variants():
    base = "https://www.pmindia.gov.in/en/news_updates/pm-addresses-the-nation/"
    entries = [
        _e(base),
        _e(base + "?comment=disable"),
        _e(base + "?tag_term=pmspeech&comment=disable"),
        _e(base + "?utm_source=twitter&utm_medium=social"),
        _e(base + "?fbclid=IwAR123"),
        _e("https://www.pmindia.gov.in/en/news_updates/pm-meets-the-president/"),
    ]
    kept = wayback.filter_entries_for_recipe(entries, r"/en/news_updates/[a-z0-9][a-z0-9-]+")
    urls = [k["original"] for k in kept]
    # ?tag_term= identifies nothing about WHICH article is served, but it is not on the
    # denylist, so it stays a distinct page: 3 kept = bare, tag_term variant, second article.
    assert base in urls
    assert "https://www.pmindia.gov.in/en/news_updates/pm-meets-the-president/" in urls
    assert not any("utm_source" in u or "fbclid" in u or u.endswith("?comment=disable") for u in urls)


def test_dedupe_keeps_the_first_capture_and_can_be_disabled():
    base = "https://x.gov/en/news/speech-123"
    entries = [_e(base + "?utm_source=a"), _e(base), _e(base + "?fbclid=b")]

    kept = wayback.filter_entries_for_recipe(entries, r"/en/news/")
    assert [k["original"] for k in kept] == [base + "?utm_source=a"]   # first wins

    every = wayback.filter_entries_for_recipe(entries, r"/en/news/", dedupe_noise_params=False)
    assert len(every) == 3                                            # opt out => old behaviour


def test_dedupe_prefers_a_twin_with_a_known_cdx_length():
    """presidencia.gov.ec 2011: the Joomla print view sorts first in CDX order, has length
    "-", and answers 404 at replay; the plain address of the same article is a real 5.7 KB
    capture. The fold must hand the run the one with a known length (2026-09-30)."""
    pv = ("http://www.presidencia.gov.ec/index.php?view=article&id=1031%3Ax"
          "&tmpl=component&print=1&option=com_content&Itemid=98")
    plain = "http://www.presidencia.gov.ec/index.php?option=com_content&view=article&id=1031:x"
    strip = [r"index\.php\?[^#]*?(?<=[?&])id=(?=\d)", r"(?<=\d)(?:%3A|:)[^&#]*.*$"]
    entries = [{**_e(pv), "length": "-"}, {**_e(plain), "length": "5680"}]
    kept = wayback.filter_entries_for_recipe(entries, r"index\.php\?", identity_strip=strip)
    assert [k["original"] for k in kept] == [plain]

    # a known-length first capture is never displaced, and neither is an unknown one by
    # another unknown one (first still wins)
    kept = wayback.filter_entries_for_recipe(list(reversed(entries)), r"index\.php\?",
                                             identity_strip=strip)
    assert [k["original"] for k in kept] == [plain]
    both_unknown = [{**_e(pv), "length": "-"}, {**_e(plain), "length": "-"}]
    kept = wayback.filter_entries_for_recipe(both_unknown, r"index\.php\?", identity_strip=strip)
    assert [k["original"] for k in kept] == [pv]

    # a twin the link_pattern rejects can't take the place of the kept one
    kept = wayback.filter_entries_for_recipe(entries, r"print=1", identity_strip=strip)
    assert [k["original"] for k in kept] == [pv]


def test_identity_fold_merges_reslugged_twins_only_when_asked():
    """presidencia.gob.do moved its 2013 comunicados to /noticias/ with accent-free slugs; the
    Archive holds both. Opt-in fold + an identity_strip of the section names = one document."""
    a = "http://presidencia.gob.do:80/comunicados/presidente-medina-y-esposa-dan-condolencias-al-presidente-de-taiw%C3%A1n"
    b = "http://www.presidencia.gob.do/noticias/presidente-medina-y-esposa-dan-condolencias-al-presidente-de-taiwan"
    c = "http://presidencia.gob.do/comunicados/presidente-medina-pide-licey-retornar-%E2%80%9Ccon-la-bandera%E2%80%9D"
    d = "https://presidencia.gob.do/noticias/presidente-medina-pide-licey-retornar-con-la-bandera"
    strip = [r"(?<=/)(?:noticias|comunicados)/"]
    entries = [_e(a), _e(b), _e(c), _e(d)]
    pat = r"/(?:noticias|comunicados)/"
    assert len(wayback.filter_entries_for_recipe(entries, pat, identity_strip=strip)) == 4
    kept = wayback.filter_entries_for_recipe(entries, pat, identity_strip=strip, fold_slugs=True)
    assert [k["original"] for k in kept] == [a, c]
    # distinct documents stay distinct
    assert (wayback.page_identity("https://x.gob/noticias/ano-2014", fold_slugs=True)
            != wayback.page_identity("https://x.gob/noticias/ano-2015", fold_slugs=True))
    assert wayback.fold_slug("/a/el-“cambio”--ya/") == "/a/el-cambio-ya/"

    # the state-file check folds the same way, so a later run doesn't re-fetch the twin
    from leaderspeech.text_scraper import run
    kept, already, within = run.select_unscraped([b], lambda u: u, {a}, identity_strip=strip,
                                                 fold_slugs=True)
    assert kept == [] and already == 1


def test_dedupe_never_collapses_query_ADDRESSED_pages():
    """president.ie, pmindia.nic.in and president.gov.ge put the document id IN the query.
    Dropping the whole query string would collapse 1,039 distinct speeches into one page —
    this is the regression guard for that."""
    ie = [_e(f"http://www.president.ie/index.php?section=5&speech={i}&lang=eng") for i in (204, 205, 206)]
    assert len(wayback.filter_entries_for_recipe(ie, r"index\.php\?section=")) == 3

    nic = [_e(f"http://pmindia.nic.in/speech-details.php?nodeid={i}") for i in (1021, 1022)]
    assert len(wayback.filter_entries_for_recipe(nic, r"speech-details\.php")) == 2

    ge = [_e(f"http://president.gov.ge/en/PressOffice/News/SpeechesAndStatements?p={i}&i=1")
          for i in (2186, 2187)]
    assert len(wayback.filter_entries_for_recipe(ge, r"SpeechesAndStatements")) == 2


def test_recipe_can_add_its_own_noise_params():
    """`pagination.wayback_noise_params` — for a CMS that invents its own UI toggles.

    La Moncloa's SharePoint serves ONE Council-of-Ministers article as
    `…council.aspx`, `…council.aspx?qfr=130` and `…council.aspx?mode=Dark`. None of those
    names are in the engine's generic denylist, so without this knob the three captures
    become three rows of the same speech — and the recipe cannot simply anchor the pattern
    at `.aspx$` instead, because 97 of that host's articles were archived ONLY in a
    query-carrying form.
    """
    base = "https://www.lamoncloa.gob.es/lang/en/gobierno/councilministers/Paginas/2019/20190823council.aspx"
    entries = [_e(base), _e(base + "?qfr=130"), _e(base + "?mode=Dark")]

    assert len(wayback.filter_entries_for_recipe(entries, r"councilministers")) == 3
    kept = wayback.filter_entries_for_recipe(
        entries, r"councilministers", extra_noise_params=["qfr", "mode"])
    assert [k["original"] for k in kept] == [base]

    # and it must NOT reach across into query-ADDRESSED sites: a name that is not listed
    # still separates two documents.
    ie = [_e(f"http://www.president.ie/index.php?speech={i}") for i in (204, 205)]
    assert len(wayback.filter_entries_for_recipe(
        ie, r"index\.php", extra_noise_params=["qfr", "mode"])) == 2


def test_identity_strip_folds_plone_download_twins():
    """`pagination.wayback_identity_strip` — Plone serves every File object twice, the object
    and its `@@download/file/<name>` twin, and the Archive holds a PDF capture of one, the other
    or both. Each DOCUMENT must be taken once: whichever variant was captured, never both."""
    base = ("http://www.biblioteca.presidencia.gov.br/presidencia/ex-presidentes/"
            "castello-branco/discursos/1965")
    entries = [
        _e(f"{base}/31.pdf"), _e(f"{base}/31.pdf/@@download/file/31.pdf"),   # both captured
        _e(f"{base}/32.pdf/@@download/file/32.pdf"),                         # twin only
        _e(f"{base}/33.pdf"),                                                # object only
    ]
    assert len(wayback.filter_entries_for_recipe(entries, r"/discursos/")) == 4
    kept = wayback.filter_entries_for_recipe(entries, r"/discursos/",
                                             identity_strip=[r"/@@download/.*$"])
    assert [k["original"] for k in kept] == [
        f"{base}/31.pdf", f"{base}/32.pdf/@@download/file/32.pdf", f"{base}/33.pdf"]


def test_page_identity_extra_noise_params_are_case_insensitive():
    a = wayback.page_identity("https://x.gov/a.aspx?Mode=Dark", extra_noise_params=["mode"])
    b = wayback.page_identity("https://x.gov/a.aspx")
    assert a == b


def test_page_identity_normalizes_scheme_www_port_and_trailing_slash():
    a = wayback.page_identity("http://www.president.gov.by:80/en/events/speech-1/")
    b = wayback.page_identity("https://president.gov.by/en/events/speech-1")
    assert a == b
    # a meaningful param still separates two pages
    assert wayback.page_identity("http://x.gov/a?id=1") != wayback.page_identity("http://x.gov/a?id=2")


# --- CDX harvest retry (a refused harvest used to kill a whole source) ------------------

class _CdxResp:
    def __init__(self, payload=None, status_code=200, bad_json=False):
        self._payload = payload if payload is not None else [
            ["timestamp", "original"], ["20080101", "https://example.org/a"],
        ]
        self.status_code = status_code
        self._bad_json = bad_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}", request=None, response=self,
            )

    def json(self):
        if self._bad_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


def _no_sleep(monkeypatch):
    monkeypatch.setattr(wayback.time, "sleep", lambda s: None)


def test_list_snapshots_retries_transient_connect_error(monkeypatch):
    # The real failure: two refusals then success. Before the retry this raised out of
    # run._harvest_wayback_entries and ended the source with scraped=0.
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def fake_get(url, params, headers, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("[WinError 10061] target machine actively refused it")
        return _CdxResp()

    monkeypatch.setattr(wayback.httpx, "get", fake_get)

    assert wayback.list_snapshots("https://example.org/*") == [
        {"timestamp": "20080101", "original": "https://example.org/a"}
    ]
    assert calls["n"] == 3


@pytest.mark.parametrize("status", sorted(wayback.RETRYABLE_STATUS_CODES))
def test_list_snapshots_retries_throttling_statuses(monkeypatch, status):
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def fake_get(url, params, headers, timeout):
        calls["n"] += 1
        return _CdxResp(status_code=status) if calls["n"] == 1 else _CdxResp()

    monkeypatch.setattr(wayback.httpx, "get", fake_get)

    assert len(wayback.list_snapshots("https://example.org/*")) == 1
    assert calls["n"] == 2


def test_list_snapshots_retries_unparseable_body(monkeypatch):
    # CDX answers overload with an HTML error page under a 200 — a decode error, not a status.
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def fake_get(url, params, headers, timeout):
        calls["n"] += 1
        return _CdxResp(bad_json=True) if calls["n"] == 1 else _CdxResp()

    monkeypatch.setattr(wayback.httpx, "get", fake_get)

    assert len(wayback.list_snapshots("https://example.org/*")) == 1
    assert calls["n"] == 2


def test_list_snapshots_does_not_retry_client_error(monkeypatch):
    # A 400 is a malformed query — a recipe bug. Retrying only delays the report.
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def fake_get(url, params, headers, timeout):
        calls["n"] += 1
        return _CdxResp(status_code=400)

    monkeypatch.setattr(wayback.httpx, "get", fake_get)

    with pytest.raises(httpx.HTTPStatusError):
        wayback.list_snapshots("https://example.org/*")
    assert calls["n"] == 1


def test_list_snapshots_gives_up_after_the_retry_budget(monkeypatch):
    # Bounded: a genuinely-down Archive must fail the run, not hang a multi-day queue.
    _no_sleep(monkeypatch)
    calls = {"n": 0}

    def fake_get(url, params, headers, timeout):
        calls["n"] += 1
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(wayback.httpx, "get", fake_get)

    with pytest.raises(httpx.ConnectError):
        wayback.list_snapshots("https://example.org/*")
    assert calls["n"] == wayback.DEFAULT_CDX_RETRIES


def test_cdx_retry_backoff_is_capped_and_increasing():
    waits = [wayback._retry_sleep(i, wayback.DEFAULT_CDX_BACKOFF)
             for i in range(wayback.DEFAULT_CDX_RETRIES)]
    assert waits == sorted(waits)
    assert all(w <= wayback.MAX_FETCH_BACKOFF * 1.1 for w in waits)
    # rides out well over a minute of refusal — the observed blips cleared in seconds
    assert sum(waits[:-1]) > 60.0


# --- documents the Archive holds only part of (2026-10-02) -------------------------------------

def _hang_up(chunks, expected):
    """A body that delivers `chunks`, then the replay hangs up (h11's own error text)."""
    def gen():
        yield from chunks
        received = sum(len(c) for c in chunks)
        raise httpx.RemoteProtocolError(
            f"peer closed connection without sending complete message body "
            f"(received {received} bytes, expected {expected})")
    return gen()


class _ScriptedClient:
    """client.stream() returns the next scripted response (a _FakeResp or an exception)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def stream(self, method, url):
        self.calls += 1
        return _Stream(self.script.pop(0))

    def close(self):
        pass


def _no_sleep(monkeypatch):
    monkeypatch.setattr(wayback.time, "sleep", lambda s: None)
    monkeypatch.setattr(wayback.random, "uniform", lambda a, b: 0.0)


ENTRY = {"timestamp": "20250403131832",
         "original": "http://www.biblioteca.presidencia.gov.br/x/mensagem-1968"}


def test_document_hang_up_at_the_same_point_twice_keeps_the_partial(monkeypatch):
    """Costa e Silva's 1968 message: the replay promises 23.7 MB and hangs up after the stored
    1.4 MB on every attempt. Keep the prefix (its pages are readable) instead of 6 retries and a
    failure; one retry is enough to tell a stored cut from a network blip."""
    _no_sleep(monkeypatch)
    resp = lambda: _FakeResp(_hang_up([b"%PDF-1.4\n", b"x" * 100], 23680765),
                             headers={"content-type": "application/pdf"})
    client = _ScriptedClient([resp(), resp(), resp()])
    ctype, data = wayback.fetch_snapshot_bytes(ENTRY, delay=0.0, client=client)
    assert client.calls == 2
    assert bytes(data) == b"%PDF-1.4\n" + b"x" * 100
    assert isinstance(data, wayback.SnapshotBytes)
    assert data.hung_up is True and data.real_size == 23680765


def test_a_hang_up_followed_by_a_full_body_is_just_a_blip(monkeypatch):
    _no_sleep(monkeypatch)
    client = _ScriptedClient([
        _FakeResp(_hang_up([b"%PDF-1.4\n"], 500)),
        _FakeResp([b"%PDF-1.4\n", b"rest of the file %%EOF"]),
    ])
    _, data = wayback.fetch_snapshot_bytes(ENTRY, delay=0.0, client=client)
    assert bytes(data).endswith(b"%%EOF") and data.hung_up is False


def test_the_longest_partial_wins(monkeypatch):
    _no_sleep(monkeypatch)
    client = _ScriptedClient([
        _FakeResp(_hang_up([b"%PDF-1.4\n"], 900)),
        _FakeResp(_hang_up([b"%PDF-1.4\n", b"more pages"], 900)),
        _FakeResp(_hang_up([b"%PDF-1.4\n", b"more pages"], 900)),
    ])
    _, data = wayback.fetch_snapshot_bytes(ENTRY, delay=0.0, client=client)
    assert bytes(data) == b"%PDF-1.4\nmore pages" and client.calls == 3


def test_html_hang_up_still_raises(monkeypatch):
    """Only documents keep a partial body: half an HTML page is not a speech."""
    _no_sleep(monkeypatch)
    client = _ScriptedClient([_FakeResp(_hang_up([b"<html>"], 900)) for _ in range(2)])
    with pytest.raises(httpx.RemoteProtocolError):
        wayback.fetch_snapshot(ENTRY, delay=0.0, client=client, retries=2)


def test_crawler_header_gives_the_real_size_of_a_stored_cut(monkeypatch):
    """Cut at exactly 1 MiB when crawled: a clean 1 MiB transfer, but the replay keeps the size
    the crawler saw in x-archive-orig-x-crawler-content-length (FHC's 1998 message: 30.5 MB)."""
    _no_sleep(monkeypatch)
    client = _ScriptedClient([_FakeResp([b"%PDF-1.4\n" + b"x" * 50], headers={
        "x-archive-orig-content-length": "1048576",
        "x-archive-orig-x-crawler-content-length": "30462354"})])
    _, data = wayback.fetch_snapshot_bytes(ENTRY, delay=0.0, client=client)
    assert data.real_size == 30462354 and data.hung_up is False
