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
