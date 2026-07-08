"""translate: fill the English `text`/`title`/`context` columns from their
`*_originlanguage` counterparts.

The scraper stores non-English speeches with the original in `text_originlanguage`
(etc.) and the unsuffixed `text` left empty (the project schema convention: unsuffixed
columns hold the ENGLISH version). This tool fills those English columns IN PLACE — no
separate dataframe versions — choosing a translation backend (Google / OpusMT / NLLB)
so a user can test and compare. It works at any stage: a raw scraped CSV, a cleaned
per-source Parquet, or the merged build.

Public entry points:
    - config.load_config(path) -> TranslateConfig
    - pipeline.translate_table(df, translator, config, ...) -> (df, n_translated)
    - backends.get_translator(name, config) -> Translator
"""

from .config import TranslateConfig, load_config

__all__ = ["TranslateConfig", "load_config", "translate_table", "get_translator"]


def __getattr__(name):  # PEP 562: lazy so `python -m ...run/probe` doesn't pull heavy deps
    if name == "translate_table":
        from .pipeline import translate_table
        return translate_table
    if name == "get_translator":
        from .backends import get_translator
        return get_translator
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
