import logging

import pandas as pd
import pytest

from leaderspeech.text_scraper import merge as merge_mod
from leaderspeech.text_scraper.index import INDEX_NAME, docid_sort_key


def _write_source(root, country, sid, rows):
    d = root / country
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(d / f"{sid}.csv", index=False)
    return d / f"{sid}.csv"


@pytest.fixture
def scraped(tmp_path):
    root = tmp_path / "data" / "scraped"
    _write_source(root, "Ukraine", "ukr_wayback", [
        {"doc_id": "UKR0001", "country": "Ukraine", "text": "a", "date": "2020-01-01"},
        {"doc_id": "UKR10000", "country": "Ukraine", "text": "b", "date": "2021-01-01"},
        {"doc_id": "UKR9999", "country": "Ukraine", "text": "c", "date": "2022-01-01"},
    ])
    # a second source, with an EXTRA column the first one lacks
    _write_source(root, "Ghana", "gha_wayback", [
        {"doc_id": "GHA0001", "country": "Ghana", "text": "d", "date": "2019-01-01",
         "date_regex_recovered": "2019-01-01"},
    ])
    # sidecars and sample snapshots must never be merged as sources
    (root / "Ukraine" / "ukr_wayback_errors.csv").write_text("url,error\nhttp://x,404\n")
    (root / "Ukraine" / "sample").mkdir()
    (root / "Ukraine" / "sample" / "snap.csv").write_text("doc_id\nXXX0001\n")
    return root


# --- the doc_id ordering bug --------------------------------------------------------

def test_docid_sort_key_orders_numerically_past_9999():
    # The whole point: a plain string sort puts UKR9999 last, so the index reported
    # Ukraine's range as ...->UKR9999 when the real last id was UKR18996.
    ids = ["UKR0001", "UKR9999", "UKR10000", "UKR18996"]
    assert sorted(ids)[-1] == "UKR9999"                      # the old, wrong behaviour
    assert sorted(ids, key=docid_sort_key)[-1] == "UKR18996"  # fixed
    assert sorted(ids, key=docid_sort_key) == ["UKR0001", "UKR9999", "UKR10000", "UKR18996"]


def test_docid_sort_key_separates_country_prefixes():
    ids = ["GHA9999", "UKR0001"]
    assert sorted(ids, key=docid_sort_key) == ["GHA9999", "UKR0001"]


def test_docid_sort_key_tolerates_a_missing_number():
    assert docid_sort_key("NODIGITS") == ("NODIGITS", -1)


def test_index_reports_the_true_last_doc_id(tmp_path):
    from leaderspeech.text_scraper.index import _summarize
    df = pd.DataFrame({"doc_id": ["UKR0001", "UKR9999", "UKR10000", "UKR18996"],
                       "country": ["Ukraine"] * 4, "date": ["2020-01-01"] * 4})
    csv = tmp_path / "ukr.csv"
    df.to_csv(csv, index=False)
    row = _summarize("ukr", csv, df, recipe=None, yml=None)
    assert row["doc_id_first"] == "UKR0001"
    assert row["doc_id_last"] == "UKR18996"
    assert row["iso3_prefix"] == "UKR"


# --- merging ------------------------------------------------------------------------

def test_merge_globs_when_there_is_no_index(scraped, tmp_path):
    out = tmp_path / "out.parquet"
    df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(out))
    assert out.exists()
    assert len(df) == 4
    assert set(df["source_id"]) == {"ukr_wayback", "gha_wayback"}


def test_merge_excludes_sidecars_and_sample_snapshots(scraped, tmp_path):
    df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert "ukr_wayback_errors" not in set(df["source_id"])
    assert "XXX0001" not in set(df["doc_id"])


def test_merge_unions_columns_and_orders_schema_first(scraped, tmp_path):
    df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert list(df.columns)[:3] == ["source_id", "doc_id", "country"]
    # the extra column exists for everyone; rows scraped before it was added are NA
    assert "date_regex_recovered" in df.columns
    assert df.loc[df["source_id"] == "ukr_wayback", "date_regex_recovered"].isna().all()


def test_merge_sorts_doc_ids_numerically(scraped, tmp_path):
    df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    ukr = df[df["country"] == "Ukraine"]["doc_id"].tolist()
    assert ukr == ["UKR0001", "UKR9999", "UKR10000"]


def test_merge_keeps_doc_id_as_text(scraped, tmp_path):
    # If doc_id were inferred as an int the alpha prefix would be lost on any all-numeric
    # source, and leading zeros would vanish.
    df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert df["doc_id"].map(type).eq(str).all()


def test_merge_prefers_the_index_csv_file_column(scraped, tmp_path):
    # Index lists ONLY Ghana -> Ukraine must not appear.
    pd.DataFrame({"csv_file": [(scraped / "Ghana" / "gha_wayback.csv").as_posix()]}) \
        .to_excel(scraped / INDEX_NAME, index=False)
    df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert set(df["source_id"]) == {"gha_wayback"}


def test_merge_reads_sheet_0_and_ignores_the_second_sheet(scraped, tmp_path, caplog):
    """The index carries a `harvested_not_scraped` sheet for sources with links but no CSV.
    `pd.read_excel` with no `sheet_name` reads sheet 0, so merge must never see it — a
    blank-`csv_file` row would fire its "listed in the index are missing" warning forever."""
    with pd.ExcelWriter(scraped / INDEX_NAME, engine="openpyxl") as writer:
        pd.DataFrame({"csv_file": [(scraped / "Ghana" / "gha_wayback.csv").as_posix()]}) \
            .to_excel(writer, sheet_name="sources", index=False)
        pd.DataFrame({"source_id": ["zaf_never_scraped"], "n_unique_links": [12372]}) \
            .to_excel(writer, sheet_name="harvested_not_scraped", index=False)

    with caplog.at_level("WARNING"):
        df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert set(df["source_id"]) == {"gha_wayback"}
    assert "are missing" not in caplog.text


def test_merge_falls_back_to_glob_when_index_lacks_csv_file(scraped, tmp_path, caplog):
    pd.DataFrame({"something_else": [1]}).to_excel(scraped / INDEX_NAME, index=False)
    with caplog.at_level(logging.WARNING):
        df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert len(df) == 4
    assert "no usable `csv_file` column" in caplog.text


def test_merge_warns_about_files_the_index_lists_but_that_are_gone(scraped, tmp_path, caplog):
    pd.DataFrame({"csv_file": [(scraped / "Ghana" / "gha_wayback.csv").as_posix(),
                               (scraped / "Ghana" / "vanished.csv").as_posix()]}) \
        .to_excel(scraped / INDEX_NAME, index=False)
    with caplog.at_level(logging.WARNING):
        merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert "listed in the index are missing" in caplog.text


def test_merge_no_index_flag_ignores_the_index(scraped, tmp_path):
    pd.DataFrame({"csv_file": [(scraped / "Ghana" / "gha_wayback.csv").as_posix()]}) \
        .to_excel(scraped / INDEX_NAME, index=False)
    df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"),
                                 use_index=False)
    assert len(df) == 4


def test_merge_flags_duplicate_doc_ids_loudly(scraped, tmp_path, caplog):
    _write_source(scraped, "Ghana", "gha_dup", [
        {"doc_id": "GHA0001", "country": "Ghana", "text": "collides", "date": "2019-01-01"},
    ])
    with caplog.at_level(logging.ERROR):
        merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert "DUPLICATE doc_id" in caplog.text
    assert "gha_dup" in caplog.text


def test_merge_reports_clean_doc_ids_when_there_are_none(scraped, tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert "doc_id OK" in caplog.text
    assert "DUPLICATE" not in caplog.text


def test_merge_flags_blank_doc_ids(scraped, tmp_path, caplog):
    _write_source(scraped, "Ghana", "gha_blank", [
        {"doc_id": "", "country": "Ghana", "text": "x", "date": "2019-01-01"},
    ])
    with caplog.at_level(logging.ERROR):
        merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert "BLANK doc_id" in caplog.text


def test_merge_notes_countries_past_9999(scraped, tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert "past doc_id 9999" in caplog.text
    assert "Ukraine" in caplog.text


def test_merge_writes_csv_gz_when_asked(scraped, tmp_path):
    out = tmp_path / "o.parquet"
    merge_mod.merge_scraped(out_root=str(scraped), out_path=str(out), write_csv=True)
    gz = out.with_suffix("").with_suffix(".csv.gz")
    assert gz.exists()
    assert len(pd.read_csv(gz, dtype=str)) == 4


def test_merge_empty_tree_returns_empty(tmp_path, caplog):
    root = tmp_path / "data" / "scraped"
    root.mkdir(parents=True)
    with caplog.at_level(logging.WARNING):
        df = merge_mod.merge_scraped(out_root=str(root), out_path=str(tmp_path / "o.parquet"))
    assert df.empty
    assert "nothing to merge" in caplog.text


def test_merge_skips_an_unreadable_source(scraped, tmp_path, caplog, monkeypatch):
    real = pd.read_csv

    def boom(path, *a, **kw):
        if "gha_wayback" in str(path):
            raise UnicodeDecodeError("utf-8", b"", 0, 1, "bad")
        return real(path, *a, **kw)

    monkeypatch.setattr(merge_mod.pd, "read_csv", boom)
    with caplog.at_level(logging.WARNING):
        df = merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert set(df["source_id"]) == {"ukr_wayback"}
    assert "skipping unreadable" in caplog.text


def test_main_exit_codes(scraped, tmp_path):
    assert merge_mod.main(["--out-root", str(scraped), "--out", str(tmp_path / "o.parquet")]) == 0
    empty = tmp_path / "empty"
    empty.mkdir()
    assert merge_mod.main(["--out-root", str(empty), "--out", str(tmp_path / "e.parquet")]) == 1


def test_merge_warns_when_the_index_is_stale(scraped, tmp_path, caplog):
    # A stale index lists FEWER sources than the tree holds — the dangerous case, because
    # the merge otherwise looks like it succeeded while quietly dropping a whole country.
    pd.DataFrame({"csv_file": [(scraped / "Ghana" / "gha_wayback.csv").as_posix()]}) \
        .to_excel(scraped / INDEX_NAME, index=False)
    with caplog.at_level(logging.WARNING):
        merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert "NOT in the index" in caplog.text
    assert "ukr_wayback.csv" in caplog.text


def test_merge_no_stale_warning_when_the_index_is_complete(scraped, tmp_path, caplog):
    pd.DataFrame({"csv_file": [(scraped / "Ghana" / "gha_wayback.csv").as_posix(),
                               (scraped / "Ukraine" / "ukr_wayback.csv").as_posix()]}) \
        .to_excel(scraped / INDEX_NAME, index=False)
    with caplog.at_level(logging.WARNING):
        merge_mod.merge_scraped(out_root=str(scraped), out_path=str(tmp_path / "o.parquet"))
    assert "NOT in the index" not in caplog.text


def test_merge_defaults_to_the_scrape_root_beside_the_index(scraped):
    # The merged table belongs next to scraped_progress_log.xlsx: the index says what was
    # scraped, this holds it. Passing --out-root must move both together.
    df = merge_mod.merge_scraped(out_root=str(scraped))
    assert (scraped / merge_mod.MERGED_NAME).exists()
    assert len(df) == 4


def test_merged_output_is_never_picked_up_as_a_source(scraped):
    # It lands INSIDE the tree being globbed, so a second merge must not ingest the first.
    merge_mod.merge_scraped(out_root=str(scraped), write_csv=True)
    again = merge_mod.merge_scraped(out_root=str(scraped), use_index=False)
    assert len(again) == 4
    assert set(again["source_id"]) == {"ukr_wayback", "gha_wayback"}
