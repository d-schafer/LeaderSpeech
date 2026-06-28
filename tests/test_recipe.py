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


@pytest.mark.skipif(not RECIPES, reason="no recipes yet")
@pytest.mark.parametrize("path", RECIPES, ids=[p.stem for p in RECIPES])
def test_committed_recipe_is_valid(path):
    recipe = load_recipe(path)
    assert recipe.source_id
    assert recipe.start_urls
