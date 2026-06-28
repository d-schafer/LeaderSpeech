"""The stop -> identify -> fix -> resume workflow, exercised without network by
faking the link harvester and the fetcher."""

import json

from leaderspeech.text_scraper import run

RECIPE_YAML = """
source_id: test_src
country: Argentina
source_language: Spanish
start_urls: ["http://x/list"]
listing: { link_selector: "a" }
title: { selectors: ["h1"] }
text: { selectors: ["div.body"] }
date: { selectors: [".date"] }
"""

WAYBACK_RECIPE_YAML = """
source_id: test_wayback
country: Argentina
source_language: Spanish
start_urls: ["casarosada.gob.ar/informacion/discursos"]
listing: { link_selector: "a", link_pattern: '/discursos/\\d+$' }
pagination: { type: wayback, wayback_to: "20151210" }
title: { selectors: ["h1"] }
text: { selectors: [".body"] }
date: { selectors: ["time"] }
date_languages: ["es"]
"""

GOOD_HTML = (
    "<html><h1>Titulo</h1><span class='date'>1 de enero de 2020</span>"
    "<div class='body'>Hola mundo, esto es un discurso de prueba.</div></html>"
)

WAYBACK_HTML = (
    "<html><h1>Discurso de prueba</h1><time>1 de enero de 2008</time>"
    "<div class='body'>Texto archivado.</div></html>"
)


class FakeFetcher:
    behavior: dict = {}  # url -> "boom" to simulate a failure; otherwise serves GOOD_HTML

    def __init__(self, **kwargs):
        pass

    def get(self, url):
        if FakeFetcher.behavior.get(url) == "boom":
            raise RuntimeError("simulated network failure")
        return GOOD_HTML

    def close(self):
        pass


def _recipe(tmp_path):
    p = tmp_path / "test_src.yml"
    p.write_text(RECIPE_YAML, encoding="utf-8")
    return str(p)


def _wayback_recipe(tmp_path):
    p = tmp_path / "test_wayback.yml"
    p.write_text(WAYBACK_RECIPE_YAML, encoding="utf-8")
    return str(p)


def test_failure_is_logged_then_fixable_and_resumable(tmp_path, monkeypatch):
    urls = ["http://x/a-good", "http://x/b-boom"]
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: list(urls))
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)
    FakeFetcher.behavior = {"http://x/b-boom": "boom"}

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    recipe = _recipe(tmp_path)

    # 1) first run: one scrapes, one fails (and is recorded, not lost)
    res = run.scrape_recipe(recipe, out_root=str(out), state_root=str(state_dir))
    assert res["scraped_this_run"] == 1
    assert res["failed_this_run"] == 1
    assert res["failed_pending_retry"] == 1

    state = json.loads((state_dir / "Argentina.json").read_text(encoding="utf-8"))
    assert "http://x/a-good" in state["seen_urls"]
    assert "http://x/b-boom" in state["failed_urls"]      # failed, NOT marked done

    errors = (out / "Argentina" / "test_src_errors.csv").read_text(encoding="utf-8")
    assert "b-boom" in errors and "simulated network failure" in errors

    # 2) a plain re-run skips the known failure (and the already-done URL)
    assert run.scrape_recipe(recipe, out_root=str(out), state_root=str(state_dir))[
        "scraped_this_run"] == 0

    # 3) "fix" the source, then retry ONLY the failures
    FakeFetcher.behavior = {}
    res3 = run.scrape_recipe(recipe, out_root=str(out), state_root=str(state_dir),
                             retry_failed=True)
    assert res3["scraped_this_run"] == 1
    assert res3["failed_pending_retry"] == 0

    state = json.loads((state_dir / "Argentina.json").read_text(encoding="utf-8"))
    assert "http://x/b-boom" in state["seen_urls"]
    assert state["failed_urls"] == []

    # doc_ids stayed unique and contiguous across runs (ARG0001 then ARG0002)
    assert state["last_doc_num"] == 2


def test_circuit_breaker_aborts_on_consecutive_failures(tmp_path, monkeypatch):
    urls = [f"http://x/{i}-boom" for i in range(20)]
    monkeypatch.setattr(run, "harvest_links", lambda *a, **k: list(urls))
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)
    FakeFetcher.behavior = {u: "boom" for u in urls}

    res = run.scrape_recipe(
        _recipe(tmp_path), out_root=str(tmp_path / "s"), state_root=str(tmp_path / "st"),
        max_consecutive_failures=5,
    )
    assert res["aborted_early"] is True
    assert res["scraped_this_run"] == 0
    assert res["failed_this_run"] == 5  # stopped right after the 5th, didn't grind through 20


def test_wayback_recipe_scrapes_archived_snapshots(tmp_path, monkeypatch):
    entries = [
        {"timestamp": "20080100", "original": "https://www.casarosada.gob.ar/informacion/discursos"},
        {"timestamp": "20080100", "original": "https://www.casarosada.gob.ar/informacion/discursos?start=40"},
        {"timestamp": "20080101", "original": "https://www.casarosada.gob.ar/informacion/discursos/1"},
        {"timestamp": "20080101", "original": "https://www.casarosada.gob.ar/informacion/discursos/18-nuestro-pais/galeria-de-presidentes/1"},
        {"timestamp": "20080102", "original": "https://www.casarosada.gob.ar/informacion/discursos/2"},
    ]
    monkeypatch.setattr(run.wayback, "list_snapshots_for_queries", lambda *a, **k: list(entries))
    monkeypatch.setattr(run.wayback, "fetch_snapshot", lambda entry, delay=3.0, timeout=60.0: WAYBACK_HTML)
    monkeypatch.setattr(run, "Fetcher", FakeFetcher)

    out, state_dir = tmp_path / "scraped", tmp_path / "state"
    res = run.scrape_recipe(_wayback_recipe(tmp_path), out_root=str(out), state_root=str(state_dir))

    assert res["scraped_this_run"] == 2
    assert res["failed_this_run"] == 0
    assert res["links_found"] == 2

    state = json.loads((state_dir / "Argentina.json").read_text(encoding="utf-8"))
    assert state["seen_urls"] == [entries[2]["original"], entries[4]["original"]]

    csv = (out / "Argentina" / "test_wayback.csv").read_text(encoding="utf-8")
    assert "Discurso de prueba" in csv
    assert "2008-01-01" in csv
