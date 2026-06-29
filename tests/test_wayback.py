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
