"""leader_tenure: curate the authoritative leader-tenure key.

The cleaner cross-checks every speaker against `leader_tenure_final.csv` but never edits
it. This tool closes that loop WITHOUT ever touching the key directly: it inventories the
speakers in the cleaned data, buckets them against the tenure key (matched / wrong-country /
unmatched), classifies and GPT-verifies the genuinely-new heads of state/government, and
PROPOSES them to an outbox the researcher approves by hand. A separate, gated `merge` step
applies approved rows (with a backup) and prints the `fixNames` lines to add.

Public entry points:
    - config.load_config(path) -> TenureConfig
    - inventory.build_inventory(df) / inventory.bucket_inventory(inv, tenure_df)
    - classify.classify_by_position(speaker, position, country)
"""

from .config import TenureConfig, load_config

__all__ = ["TenureConfig", "load_config"]
