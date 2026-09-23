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
        self.posts = []  # (url, json_body) per POST, for asserting body-offset paging

    def _next(self):
        return _Resp(self.pages.pop(0) if self.pages else {})

    def get(self, url):
        self.calls.append(url)
        return self._next()

    def post(self, url, json=None):
        self.calls.append(url)
        self.posts.append((url, json))
        return self._next()

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


def test_dig_list_index_and_quoted_keys():
    # list index
    assert api._dig({"a": {"b": [{"c": 1}, {"c": 2}]}}, "a.b[0].c") == 1
    assert api._dig({"a": {"b": [{"c": 1}, {"c": 2}]}}, "a.b[1].c") == 2
    assert api._dig({"a": {"b": [{"c": 1}]}}, "a.b[5].c") is None  # out of range
    assert api._dig({"a": {"b": {"c": 1}}}, "a.b[0]") is None      # not a list
    # quoted key containing a space (the gov.il date path shape)
    doc = {"tags": {"metaData": {"Publish Date": [{"title": "2020-01-01"}]}}}
    assert api._dig(doc, 'tags.metaData."Publish Date"[0].title') == "2020-01-01"
    # plain dotted path is unchanged; a bare numeric segment stays a string KEY
    assert api._dig({"a": {"b": 1}}, "a.b") == 1
    assert api._dig({"a": {"0": 1}}, "a.0") == 1  # ".0" is key "0", not an index


def test_url_base_join():
    page = {"items": [{"link": "/en/pages/speech-1"}, {"link": "/en/pages/speech-2"}]}
    client = FakeClient([page])
    r = _recipe(
        {"results_path": "items", "url_field": "link",
         "url_base": "https://www.gov.il/"},
    )
    # start_urls[0] is the API host (http://x/...); links must join the SITE host instead.
    r.listing.link_pattern = None  # don't filter these non-/prensa/ links out
    entries = api.harvest_entries(r, client=client)
    assert entries[0]["url"] == "https://www.gov.il/en/pages/speech-1"
    assert entries[1]["url"] == "https://www.gov.il/en/pages/speech-2"


def test_post_body_and_body_page_field_pagination():
    page1 = {"items": [{"link": "https://x/prensa/1"}, {"link": "https://x/prensa/2"}]}
    page2 = {"items": [{"link": "https://x/prensa/3"}]}
    page3 = {"items": []}  # empty -> stop
    client = FakeClient([page1, page2, page3])
    r = _recipe(
        {"results_path": "items", "url_field": "link",
         "method": "POST", "body": {"categoryId": 31, "page": 0},
         "body_page_field": "page"},
        start=0, step=50, max_pages=10,
    )
    entries = api.harvest_entries(r, client=client)

    assert [e["url"] for e in entries] == [
        "https://x/prensa/1", "https://x/prensa/2", "https://x/prensa/3"]
    # offset written into the body per page; request URL stays the bare endpoint
    assert [b["page"] for _, b in client.posts] == [0, 50, 100]
    assert all(b["categoryId"] == 31 for _, b in client.posts)  # rest of body preserved
    assert all(u == "http://x/_api/search/query" for u in client.calls)  # no query param
    # the recipe's own body is never mutated across pages
    assert r.pagination.api.body == {"categoryId": 31, "page": 0}


def test_post_paginates_by_query_param_without_body_page_field():
    page1 = {"items": [{"link": "https://x/prensa/1"}]}
    page2 = {"items": []}
    client = FakeClient([page1, page2])
    r = _recipe(
        {"results_path": "items", "url_field": "link",
         "method": "POST", "body": {"q": "discurso"}},
        param="startRow", start=0, step=20, max_pages=10,
    )
    entries = api.harvest_entries(r, client=client)

    assert [e["url"] for e in entries] == ["https://x/prensa/1"]
    assert "startRow=0" in client.calls[0]      # offset in the URL, not the body
    assert client.posts[0][1] == {"q": "discurso"}  # body constant across pages


def test_post_single_request_when_no_paging():
    page = {"items": [{"link": "https://x/prensa/1"}]}
    client = FakeClient([page, {"items": [{"link": "https://x/prensa/2"}]}])
    r = _recipe({"results_path": "items", "url_field": "link",
                 "method": "POST", "body": {"q": "x"}})  # no param, no body_page_field

    entries = api.harvest_entries(r, client=client)
    assert [e["url"] for e in entries] == ["https://x/prensa/1"]  # one POST only
    assert len(client.posts) == 1

# --- root-array responses (WordPress REST and friends) ---------------------------------


def _wp_rows():
    return [
        {"link": "https://www.presidentti.fi/a/", "date": "2026-06-10T19:39:08",
         "title": {"rendered": "Puhe yksi"}},
        {"link": "https://www.presidentti.fi/b/", "date": "2024-03-01T10:00:00",
         "title": {"rendered": "Puhe kaksi"}},
    ]


def _wp_recipe():
    r = _recipe({"results_path": ".", "url_field": "link",
                 "title_field": "title.rendered", "date_field": "date"},
                param="page", start=1, step=1, max_pages=3)
    r.listing.link_pattern = "presidentti.fi/"
    return r


def test_results_path_dot_reads_a_bare_root_array():
    """WordPress answers /wp-json/wp/v2/posts with a JSON list at the ROOT. A dotted path
    cannot address that (it needs at least one key), so `results_path: "."` names the
    response itself. Found while authoring fin_presidentti."""
    client = FakeClient([_wp_rows(), []])
    entries = api.harvest_entries(_wp_recipe(), client=client)

    assert [e["url"] for e in entries] == ["https://www.presidentti.fi/a/",
                                           "https://www.presidentti.fi/b/"]
    assert entries[0]["title"] == "Puhe yksi"
    assert entries[0]["date"] == "2026-06-10"   # ISO parsed; api dates skip date_languages
    assert entries[1]["date"] == "2024-03-01"


def test_root_array_path_ignores_a_non_list_response():
    """'.' means "the response IS the array" — an envelope object is not one and must not
    be mistaken for rows."""
    client = FakeClient([{"code": "rest_post_invalid_page_number"}])
    assert api.harvest_entries(_wp_recipe(), client=client) == []


def test_dotted_results_path_still_works():
    """Backward compatibility: the SharePoint envelope form is untouched."""
    r = _recipe({"results_path": "d.query.PrimaryQueryResult.RelevanceResults.Table.Rows.results",
                 "url_field": "Path", "cells_path": "Cells.results"})
    client = FakeClient([_sp_page([_sp_row("http://x/prensa/1", "T", "2024-01-02T00:00:00Z")]),
                         _sp_page([])])
    assert [e["url"] for e in api.harvest_entries(r, client=client)] == ["http://x/prensa/1"]


# --- api.text_is_html: carried HTML bodies (2026-09-22) -------------------------------
# A dozen WordPress recipes leave `text_field` unset and pay for a page fetch per document
# purely because `clean_text` does not strip tags. `text_is_html` flattens the fragment
# instead — the Colombian SharePoint recipes carry `PublishingPageContent` this way.

def _html_recipe(text_is_html):
    return _recipe({"results_path": ".", "url_field": "link", "title_field": "title",
                    "text_field": "body", "text_is_html": text_is_html})


def test_text_is_html_flattens_a_carried_fragment():
    page = [{"link": "http://x/prensa/1", "title": "T",
             "body": "<p><strong>Bogot\u00e1</strong></p><p>Buenos d\u00edas.</p>"
                     "<script>var a=1;</script>"}]
    entries = api.harvest_entries(_html_recipe(True), client=FakeClient([page, []]))
    assert entries[0]["text"] == "Bogot\u00e1\nBuenos d\u00edas."   # tags gone, blocks split
    assert "var a" not in entries[0]["text"]                        # script dropped


def test_text_is_html_defaults_off_so_existing_recipes_are_unchanged():
    page = [{"link": "http://x/prensa/1", "title": "T", "body": "<p>Hola</p>"}]
    entries = api.harvest_entries(_html_recipe(False), client=FakeClient([page, []]))
    assert entries[0]["text"] == "<p>Hola</p>"


def test_text_is_html_on_empty_text_stays_empty():
    page = [{"link": "http://x/prensa/1", "title": "T", "body": None}]
    entries = api.harvest_entries(_html_recipe(True), client=FakeClient([page, []]))
    assert entries[0]["text"] == ""


# --- api.via_browser: which client create_client hands back ---------------------------

def test_create_client_is_httpx_unless_via_browser_is_set():
    import httpx
    r = _recipe({"results_path": ".", "url_field": "link"})
    client = api.create_client(r)
    try:
        assert isinstance(client, httpx.Client)
    finally:
        client.close()


def test_via_browser_selects_the_browser_client(monkeypatch):
    """No browser is launched here — only the dispatch in create_client is asserted."""
    built = {}

    class _Stub:
        def __init__(self, recipe, timeout=120.0, fetcher=None):
            built["recipe"] = recipe
            built["timeout"] = timeout
            built["fetcher"] = fetcher

    monkeypatch.setattr(api, "BrowserApiClient", _Stub)
    r = _recipe({"results_path": ".", "url_field": "link", "via_browser": True})
    sentinel = object()
    client = api.create_client(r, timeout=30.0, fetcher=sentinel)
    assert isinstance(client, _Stub)
    assert built["recipe"] is r
    assert built["timeout"] == 120.0   # floored: a browser round-trip needs longer than 30s
    # probe/run hand over the Fetcher they already built — Playwright's sync API allows
    # only one driver per thread, so a second browser here would raise.
    assert built["fetcher"] is sentinel


def test_borrowed_browser_is_not_closed_by_the_api_client():
    """A borrowed Fetcher belongs to probe/run; closing it would kill their page fetches."""
    class _Ctx:
        pass

    class _Fetcher:
        def __init__(self):
            self._context = _Ctx()
            self.closed = False

        def close(self):
            self.closed = True

    r = _recipe({"results_path": ".", "url_field": "link", "via_browser": True})
    borrowed = _Fetcher()
    client = api.BrowserApiClient.__new__(api.BrowserApiClient)
    client._owns_fetcher = False
    client._fetcher = borrowed
    client.close()
    assert borrowed.closed is False


def test_site_root_defaults_to_the_api_host():
    r = _recipe({"results_path": ".", "url_field": "link", "via_browser": True})
    assert api._site_root(r) == "http://x/"


def test_text_is_html_drops_zero_width_editor_residue():
    """SharePoint opens nearly every body with an empty zero-width paragraph; it is not
    whitespace, so without stripping it every document would start with a stray glyph."""
    page = [{"link": "http://x/prensa/1", "title": "T",
             "body": "<p>​</p><p>Bogotá, 14 de noviembre de 2024</p>"}]
    entries = api.harvest_entries(_html_recipe(True), client=FakeClient([page, []]))
    assert entries[0]["text"] == "Bogotá, 14 de noviembre de 2024"


# --- api.param_template: OData keyset paging (2026-09-22) -----------------------------
# A SharePoint LIST endpoint ignores $skip and returns page 1 forever, so the only way to
# walk it is `$filter=Id gt <last>`. That needs the paging param's VALUE shaped, not just
# the offset written.

def test_param_template_shapes_the_paging_value():
    pages = [{"items": [{"link": "http://x/prensa/a"}]},
             {"items": [{"link": "http://x/prensa/b"}]},
             {"items": []}]
    client = FakeClient(pages)
    r = _recipe({"results_path": "items", "url_field": "link",
                 "param_template": "Id gt {n}"},
                param="$filter", start=0, step=500, max_pages=5)
    entries = api.harvest_entries(r, client=client)
    assert [e["url"] for e in entries] == ["http://x/prensa/a", "http://x/prensa/b"]
    from urllib.parse import parse_qs, urlparse
    sent = [parse_qs(urlparse(u).query)["$filter"][0] for u in client.calls]
    assert sent[:3] == ["Id gt 0", "Id gt 500", "Id gt 1000"]


def test_without_param_template_the_bare_offset_is_still_written():
    """Backward compatibility: every existing api recipe pages by a plain number."""
    client = FakeClient([{"items": [{"link": "http://x/prensa/a"}]}, {"items": []}])
    r = _recipe({"results_path": "items", "url_field": "link"},
                param="startRow", start=0, step=50, max_pages=3)
    api.harvest_entries(r, client=client)
    assert "startRow=0" in client.calls[0]
    assert "startRow=50" in client.calls[1]
