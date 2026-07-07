import pandas as pd

from leaderspeech.clean_structure_metadata import store


def _row(doc_id, status="accepted"):
    r = {c: "" for c in store.CLEANED_COLUMNS}
    r["doc_id"] = doc_id
    r["country"] = "Testland"
    r["clean_status"] = status
    return r


def test_read_missing_returns_empty_frame(tmp_path):
    df = store.read_source(tmp_path / "nope.parquet")
    assert df.empty
    assert list(df.columns) == store.CLEANED_COLUMNS


def test_atomic_write_roundtrip_and_unicode(tmp_path):
    p = tmp_path / "Testland" / "src.parquet"
    r = _row("TST0001")
    r["speaker"] = "Sebastián Piñera 习近平"   # non-latin + accents must round-trip exactly
    store.write_source_atomic(pd.DataFrame([r]), p, compression="zstd")
    back = store.read_source(p)
    assert len(back) == 1
    assert back.iloc[0]["speaker"] == "Sebastián Piñera 习近平"


def test_second_write_creates_bak(tmp_path):
    p = tmp_path / "Testland" / "src.parquet"
    store.write_source_atomic(pd.DataFrame([_row("TST0001")]), p)
    store.write_source_atomic(pd.DataFrame([_row("TST0001"), _row("TST0002")]), p)
    assert (p.with_suffix(p.suffix + ".bak")).exists()
    assert len(store.read_source(p)) == 2


def test_done_and_failed_split():
    df = pd.DataFrame([
        _row("TST0001", "accepted"),
        _row("TST0002", "rejected_not_speech"),
        _row("TST0003", "error_api"),
    ])
    done, failed = store.done_and_failed(df)
    assert done == {"TST0001", "TST0002"}
    assert failed == {"TST0003"}
