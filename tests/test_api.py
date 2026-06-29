"""JSON / search-API harvesting (pagination.type == 'api'), exercised without
network by passing a fake httpx-like client into api.harvest_entries."""

from leaderspeech.text_scraper import api
from leaderspeech.text_scraper.recipe import Recipe


def _recipe(api_block, **pag):
    base = {
        "source_id": "t",
        "country": "Colombia",
        "source_language": "Spanish",
        "start_urls": ["http://x/_api/search/query"],
        "listing": {"link_pattern": "/prensa/"},
        "title": {"selectors": ["h1"]},
        "text": {"selectors": ["article"]},
        "date": {"selectors": ["time"]},
        "date_languages": ["es"],
        "pagination": {"type": "api", "api": api_block, **pag},
    }
    return Recipe(**base)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class FakeClient:
    """Serves the queued pages in order; an exhausted queue yields {} so the
    harvester sees an empty result set and stops."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return _Resp(self.pages.pop(0) if self.pages else {})

    def close(self):
        pass


def _sp_page(rows):
    return {"d": {"query": {"PrimaryQueryResult": {"RelevanceResults": {
        "Table": {"Rows": {"results": rows}}}}}}}


def _sp_row(path, title, date):
    return {"Cells": {"results": [
        {"Key": "Path", "Value": path},
        {"Key": "Title", "Value": title},
        {"Key": "Write", "Value": date},
    ]}}


def test_dig_descends_and_tolerates_missing():
    assert api._dig({"a": {"b": 1}}, "a.b") == 1
    assert api._dig({"a": {"b": 1}}, "a.c") is None
    assert api._dig({"a": [1, 2]}, "a.b") is None  # list isn't a dict -> None
    assert api._dig(None, "a") is None
    assert api._dig({"a": 1}, None) is None


def test_sharepoint_cells_mode_paginates_and_filters():
    page1 = _sp_page([
        _sp_row("https://x/prensa/1-discurso", "Uno", "2023-01-01T00:00:00Z"),
        _sp_row("https://x/noticias/2", "Skip me", "2023-01-02T00:00:00Z"),  # filtered out
    ])
    page2 = _sp_page([_sp_row("https://x/prensa/3-discurso", "Tres", "2023-02-01T00:00:00Z")])
    page3 = _sp_page([])  # empty -> stop
    client = FakeClient([page1, page2, page3])

    r = _recipe(
        {
            "results_path": "d.query.PrimaryQueryResult.RelevanceResults.Table.Rows.results",
            "cells_path": "Cells.results",
            "url_field": "Path",
            "title_field": "Title",
            "date_field": "Write",
        },
        param="startRow", start=0, step=50, max_pages=10,
    )
    entries = api.harvest_entries(r, client=client)

    assert [e["url"] for e in entries] == [
        "https://x/prensa/1-discurso", "https://x/prensa/3-discurso"]
    assert entries[0]["title"] == "Uno"
    assert entries[0]["date"] == "2023-01-01"          # ISO datetime parsed to a date
    # paginated via the startRow offset param
    assert "startRow=0" in client.calls[0]
    assert "startRow=50" in client.calls[1]


def test_generic_dotted_paths_single_request_when_no_param():
    page = {"items": [
        {"link": "https://x/prensa/a", "name": "A", "ts": "1 de enero de 2020"},
        {"link": "https://x/prensa/b", "name": "B", "ts": "2 de enero de 2020"},
    ]}
    client = FakeClient([page])
    r = _recipe({"results_path": "items", "url_field": "link",
                 "title_field": "name", "date_field": "ts"})

    entries = api.harvest_entries(r, client=client)

    assert [e["url"] for e in entries] == ["https://x/prensa/a", "https://x/prensa/b"]
    assert entries[0]["title"] == "A"
    assert entries[0]["date"] == "2020-01-01"
    assert len(client.calls) == 1  # no paging param -> exactly one request


def test_relative_urls_resolved_and_max_links_caps():
    page = {"items": [
        {"link": "/prensa/x"}, {"link": "/prensa/y"}, {"link": "/prensa/z"},
    ]}
    client = FakeClient([page])
    r = _recipe({"results_path": "items", "url_field": "link"})

    entries = api.harvest_entries(r, max_links=2, client=client)

    assert len(entries) == 2
    assert entries[0]["url"] == "http://x/prensa/x"  # joined against start_urls[0]


def test_text_field_carries_body_when_present():
    page = {"items": [{"link": "https://x/prensa/a", "name": "A",
                       "body": "Texto completo desde el JSON."}]}
    client = FakeClient([page])
    r = _recipe({"results_path": "items", "url_field": "link",
                 "title_field": "name", "text_field": "body"})

    entries = api.harvest_entries(r, client=client)
    assert entries[0]["text"] == "Texto completo desde el JSON."
