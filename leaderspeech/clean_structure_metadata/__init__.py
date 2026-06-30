"""clean_structure_metadata: clean, verify, and enrich scraped speech metadata.

Reads the scraper's per-source CSVs and uses one cheap GPT structured-extraction
pass per speech (plus a deterministic tenure crosscheck and a hard gate) to confirm
the speaker, confirm it is an actual speech, and add position, audience, venue,
language, and a corrected date. Output is a per-source Parquet (the canonical
incremental store); `merge` + `scripts/export_leaderspeech.R` build the final
LeaderSpeech deliverable.

Public entry points:
    - config.load_config(path) -> CleanConfig
    - pipeline.clean_source(source_id, ...) -> summary dict
    - merge.build_dataset(out_root, ...) -> path
"""

from .config import CleanConfig, load_config

__all__ = ["CleanConfig", "load_config", "clean_source", "build_dataset"]


def __getattr__(name):  # PEP 562: lazy so `python -m ...run/merge` doesn't double-import
    if name == "clean_source":
        from .pipeline import clean_source
        return clean_source
    if name == "build_dataset":
        from .merge import build_dataset
        return build_dataset
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
