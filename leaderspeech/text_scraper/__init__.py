"""text_scraper: a config-driven scraper for leader speeches.

A single engine reads a per-site "recipe" (a YAML file describing how that site
exposes its speeches) and turns it into rows of the standardized LeaderSpeech
schema. Adding a new source means writing a recipe, not new code.

Public entry points:
    - recipe.load_recipe(path) -> Recipe
    - run.scrape_recipe(recipe_path, ...) -> summary dict
"""

from .recipe import Recipe, load_recipe

__all__ = ["Recipe", "load_recipe"]
