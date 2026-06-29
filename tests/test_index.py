"""The scraped-data index: one row per source CSV, with coverage + provenance for
merging."""

import csv

import pandas as pd

from leaderspeech.text_scraper import index
from leaderspeech.text_scraper.run import SCHEMA_COLUMNS

RECIPE_YAML = r"""
source_id: arg_casarosada
country: Argentina
source_language: Spanish
start_urls: ["https://www.casarosada.gob.ar/discursos"]
listing: { link_selector: "a" }
pagination: { type: query_param, param: page }
title: { selectors: ["h1"] }
text: { selectors: ["article"] }
date: { selectors: [".date"] }
"""


def _write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SCHEMA_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in SCHEMA_COLUMNS})


def test_build_index_summarizes_a_source(tmp_path):
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir()
    (recipes_dir / "arg_casarosada.yml").write_text(RECIPE_YAML, encoding="utf-8")

    out_root = tmp_path / "scraped"
    _write_csv(out_root / "Argentina" / "arg_casarosada.csv", [
        {"doc_id": "ARG0001", "country": "Argentina", "date": "2020-01-01",
         "text": "uno", "source": "https://www.casarosada.gob.ar/discursos/1"},
        {"doc_id": "ARG0002", "country": "Argentina", "date": "2026-06-23",
         "text": "dos", "source": "https://www.casarosada.gob.ar/discursos/2"},
        {"doc_id": "ARG0003", "country": "Argentina", "date": "0001-11-30",  # bad year
         "text": "tres", "source": "https://www.casarosada.gob.ar/discursos/3"},
    ])
    # an _errors.csv sibling must be ignored
    (out_root / "Argentina" / "arg_casarosada_errors.csv").write_text(
        "timestamp,url,error\n", encoding="utf-8")

    path = index.build_index(str(out_root), str(recipes_dir))
    assert path is not None

    df = pd.read_excel(path)
    assert list(df.columns) == index.COLUMNS
    assert len(df) == 1  # the _errors.csv was skipped
    row = df.iloc[0]
    assert row["source_id"] == "arg_casarosada"
    assert row["country"] == "Argentina"
    assert row["main_website"] == "www.casarosada.gob.ar"
    assert row["pagination_type"] == "query_param"
    assert row["n_speeches"] == 3
    assert row["date_min"] == "2020-01-01"          # the 0001 date is clipped out
    assert row["date_max"] == "2026-06-23"
    assert row["n_bad_or_missing_date"] == 1        # the 0001 date flagged
    assert row["doc_id_first"] == "ARG0001"
    assert row["doc_id_last"] == "ARG0003"
    assert row["iso3_prefix"] == "ARG"
    assert row["csv_file"].endswith("Argentina/arg_casarosada.csv")


def test_build_index_no_csvs_returns_none(tmp_path):
    assert index.build_index(str(tmp_path / "scraped"), str(tmp_path / "recipes")) is None
