"""Schema validation, plus a guard that every committed recipe loads. CI relies
on this test to reject malformed recipes."""

from pathlib import Path

import pytest

from leaderspeech.text_scraper.recipe import Recipe, load_recipe

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPES = sorted((REPO_ROOT / "recipes").glob("*.yml"))

MINIMAL = dict(
    source_id="x",
    country="Argentina",
    start_urls=["https://example.org/list"],
    listing={"link_selector": "a"},
    title={"selectors": ["h1"]},
    text={"selectors": ["article"]},
    date={"selectors": [".date"]},
)


def test_minimal_recipe_loads_and_autofills_iso3n():
    r = Recipe(**MINIMAL)
    assert r.iso3n == 32  # Argentina, filled from country name
    assert r.dataset == "LeaderSpeech"
    assert r.renderer.value == "static"
    assert r.user_agent is None  # honest bot UA by default


def test_user_agent_override_loads():
    r = Recipe(**{**MINIMAL, "user_agent": "Mozilla/5.0 (compatible)"})
    assert r.user_agent == "Mozilla/5.0 (compatible)"


def test_defaults_for_js_settle_and_cdp_endpoint():
    r = Recipe(**MINIMAL)
    assert r.js_settle == 0.0
    assert r.cdp_endpoint is None


def test_cdp_renderer_and_settle_fields_load():
    r = Recipe(**{**MINIMAL, "renderer": "cdp", "js_settle": 2.5,
                  "cdp_endpoint": "http://localhost:9222"})
    assert r.renderer.value == "cdp"
    assert r.js_settle == 2.5
    assert r.cdp_endpoint == "http://localhost:9222"


def test_missing_required_field_selectors_raises():
    bad = {**MINIMAL, "text": {"selectors": []}}
    with pytest.raises(Exception):
        Recipe(**bad)


def test_listing_requires_a_selector_or_pattern():
    bad = {**MINIMAL, "listing": {}}
    with pytest.raises(Exception):
        Recipe(**bad)


def test_query_param_pagination_requires_param():
    bad = {**MINIMAL, "pagination": {"type": "query_param"}}
    with pytest.raises(Exception):
        Recipe(**bad)


def test_wayback_pagination_loads():
    r = Recipe(**{**MINIMAL, "pagination": {"type": "wayback"}})
    assert r.pagination.type.value == "wayback"
    assert r.pagination.wayback_delay == 5.0


def test_api_pagination_loads_with_block():
    r = Recipe(**{**MINIMAL, "pagination": {
        "type": "api",
        "param": "startRow", "step": 50,
        "api": {"results_path": "d.results", "url_field": "Path",
                "cells_path": "Cells.results", "date_field": "Write"},
    }})
    assert r.pagination.type.value == "api"
    assert r.pagination.api.url_field == "Path"
    assert r.pagination.api.cell_key == "Key"  # default


def test_api_pagination_requires_block_and_fields():
    with pytest.raises(Exception):
        Recipe(**{**MINIMAL, "pagination": {"type": "api"}})  # no api block
    with pytest.raises(Exception):
        Recipe(**{**MINIMAL, "pagination": {"type": "api", "api": {"url_field": "Path"}}})  # no results_path


def test_api_defaults_to_get():
    r = Recipe(**{**MINIMAL, "pagination": {
        "type": "api", "api": {"results_path": "items", "url_field": "link"}}})
    assert r.pagination.api.method == "GET"      # default, unchanged behavior
    assert r.pagination.api.body is None
    assert r.pagination.api.body_page_field is None
    assert r.pagination.api.url_base is None


def test_api_post_recipe_loads():
    r = Recipe(**{**MINIMAL, "pagination": {
        "type": "api", "start": 0, "step": 50,
        "api": {
            "results_path": "data.items", "url_field": "url",
            "date_field": 'tags.metaData."Publish Date"[0].title',
            "method": "POST", "body": {"categoryId": 31, "page": 0},
            "body_page_field": "page", "url_base": "https://www.gov.il/",
        },
    }})
    assert r.pagination.api.method == "POST"
    assert r.pagination.api.body == {"categoryId": 31, "page": 0}
    assert r.pagination.api.body_page_field == "page"
    assert r.pagination.api.url_base == "https://www.gov.il/"


def test_api_rejects_unknown_method():
    with pytest.raises(Exception):
        Recipe(**{**MINIMAL, "pagination": {
            "type": "api",
            "api": {"results_path": "items", "url_field": "link", "method": "PUT"}}})


def test_feed_pagination_loads():
    r = Recipe(**{**MINIMAL, "listing": {"link_pattern": "/x/"},
                  "pagination": {"type": "feed", "feed": {"use_content": False}}})
    assert r.pagination.type.value == "feed"
    assert r.pagination.feed.use_content is False
    assert r.pagination.feed.format == "auto"  # default


@pytest.mark.skipif(not RECIPES, reason="no recipes yet")
@pytest.mark.parametrize("path", RECIPES, ids=[p.stem for p in RECIPES])
def test_committed_recipe_is_valid(path):
    recipe = load_recipe(path)
    assert recipe.source_id
    assert recipe.start_urls


# --- issue #55: listing item-metadata schema --------------------------------------------


def test_listing_item_meta_loads():
    r = Recipe(**{**MINIMAL, "listing": {
        "link_pattern": r"\.pdf",
        "item_selector": "div.row.content-display",
        "item_date": {"selectors": ["div.meta-data p"]},
    }})
    assert r.listing.item_selector == "div.row.content-display"
    assert r.listing.item_date.selectors == ["div.meta-data p"]


def test_item_date_without_item_selector_raises():
    bad = {**MINIMAL, "listing": {"link_selector": "a",
                                  "item_date": {"selectors": [".date"]}}}
    with pytest.raises(Exception, match="item_selector"):
        Recipe(**bad)


def test_item_selector_without_any_item_field_raises():
    bad = {**MINIMAL, "listing": {"link_selector": "a", "item_selector": "div.row"}}
    with pytest.raises(Exception, match="does nothing"):
        Recipe(**bad)


def test_url_regex_on_an_item_field_raises():
    """url_regex reads a URL, but an item field reads a listing block — so it silently does
    nothing. Fail loudly instead."""
    bad = {**MINIMAL, "listing": {"link_selector": "a", "item_selector": "div.row",
                                  "item_date": {"url_regex": r"(\d{4})"}}}
    with pytest.raises(Exception, match="url_regex"):
        Recipe(**bad)


# --- start_urls_file: thousands of LISTING pages, one per line (2026-09-22) ------------
# The sibling of pagination.url_list_file, for a frozen news archive whose only index is a
# page per DAY (col_historico: ~2,900 of them). These stay LISTING pages, so
# listing.link_pattern still applies — that is what distinguishes the two.

def _with_start_urls_file(tmp_path, body, inline=None):
    f = tmp_path / "days.txt"
    f.write_text(body, encoding="utf-8")
    data = dict(MINIMAL, start_urls_file=str(f))
    if inline is not None:
        data["start_urls"] = inline
    else:
        data.pop("start_urls")
    return Recipe(**data)


def test_start_urls_file_is_read_and_skips_blanks_and_comments(tmp_path):
    r = _with_start_urls_file(tmp_path, (
        "# derived from the daily archive calendar\n"
        "https://ex.gov/2010/julio/31/archivo.html\n"
        "\n"
        "   https://ex.gov/2010/julio/30/archivo.html   \n"
    ))
    assert r.start_urls == ["https://ex.gov/2010/julio/31/archivo.html",
                            "https://ex.gov/2010/julio/30/archivo.html"]


def test_start_urls_file_combines_with_inline_start_urls_and_dedupes(tmp_path):
    r = _with_start_urls_file(
        tmp_path,
        "https://ex.gov/a\nhttps://ex.gov/b\n",
        inline=["https://ex.gov/a"],
    )
    assert r.start_urls == ["https://ex.gov/a", "https://ex.gov/b"]  # inline first, once


def test_start_urls_file_missing_raises_rather_than_crawling_nothing(tmp_path):
    with pytest.raises(ValueError, match="start_urls_file"):
        Recipe(**dict(MINIMAL, start_urls_file=str(tmp_path / "nope.txt")))


def test_a_recipe_with_neither_start_urls_nor_a_file_is_rejected():
    data = dict(MINIMAL)
    data.pop("start_urls")
    with pytest.raises(ValueError, match="start_urls"):
        Recipe(**data)


def test_an_empty_start_urls_file_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="start_urls"):
        _with_start_urls_file(tmp_path, "# only a comment\n\n")


def test_load_recipe_resolves_start_urls_file_against_the_recipe_directory(tmp_path):
    import yaml
    (tmp_path / "days.txt").write_text("https://ex.gov/2010/julio/31/archivo.html\n",
                                       encoding="utf-8")
    spec = dict(MINIMAL, start_urls_file="days.txt")   # relative, as a committed recipe writes it
    spec.pop("start_urls")
    p = tmp_path / "r.yml"
    p.write_text(yaml.safe_dump(spec), encoding="utf-8")
    import os
    cwd = os.getcwd()
    os.chdir(tmp_path.parent)          # run from ANOTHER directory: the path must still resolve
    try:
        r = load_recipe(p)
    finally:
        os.chdir(cwd)
    assert r.start_urls == ["https://ex.gov/2010/julio/31/archivo.html"]
