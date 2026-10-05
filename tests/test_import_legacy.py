"""import_legacy: an earlier project's table written into the corpus as a source, with doc_ids
from the shared country counter and its URLs marked seen so no recipe re-fetches them."""

import json

import pandas as pd
import pytest

from leaderspeech.text_scraper import import_legacy, index
from leaderspeech.text_scraper.run import SCHEMA_COLUMNS, load_state, save_state, select_unscraped

SPEC = """
source_id: mex_test_import
country: Mexico
source_language: Spanish
position: president
input: legacy.csv
columns: {source: list, title: title, text: text, context: context, date: date}
english: {title: title_en, context: context_en}
extra: {text_en_leader_only: text_en}
notes: test import
"""


def _setup(tmp_path, rows, state=None):
    pd.DataFrame(rows).to_csv(tmp_path / "legacy.csv", index=False)
    (tmp_path / "spec.yml").write_text(SPEC, encoding="utf-8")
    out_root, state_root = tmp_path / "scraped", tmp_path / "state"
    if state is not None:
        save_state(state_root / "Mexico.json", state)
    return import_legacy.load_spec(tmp_path / "spec.yml"), str(out_root), str(state_root)


def _row(n, url=None, text="PRESIDENTE: Buenos días.", date="2020-03-0%d"):
    return {"list": url or f"https://www.gob.mx/presidencia/es/articulos/discurso-{n}?idiom=es",
            "title": f"Título {n}", "text": text, "context": f"Contexto {n}",
            "date": date % n if "%d" in date else date,
            "title_en": f"Title {n}", "context_en": f"Context {n}", "text_en": f"Good morning {n}."}


def test_dry_run_writes_nothing(tmp_path):
    spec, out_root, state_root = _setup(tmp_path, [_row(1), _row(2)],
                                        state={"last_doc_num": 140, "seen_urls": []})
    plan = import_legacy.plan_import(spec, out_root, state_root)
    assert [r["doc_id"] for r in plan["rows"]] == ["MEX0141", "MEX0142"]
    assert not (tmp_path / "scraped").exists()
    assert load_state(tmp_path / "state" / "Mexico.json")["last_doc_num"] == 140


def test_apply_writes_schema_rows_state_links_sidecars(tmp_path):
    spec, out_root, state_root = _setup(tmp_path, [_row(1), _row(2)],
                                        state={"last_doc_num": 140, "seen_urls": ["https://x/a"]})
    import_legacy.apply_import(import_legacy.plan_import(spec, out_root, state_root))

    out = tmp_path / "scraped" / "Mexico"
    df = pd.read_csv(out / "mex_test_import.csv", dtype=str, keep_default_na=False)
    assert list(df.columns) == SCHEMA_COLUMNS
    r = df.iloc[0]
    # original language in *_originlanguage; English only where a real translation was mapped
    assert r["text_originlanguage"] == "PRESIDENTE: Buenos días." and r["text"] == ""
    assert r["title_originlanguage"] == "Título 1" and r["title"] == "Title 1"
    assert r["context"] == "Context 1" and r["date"] == "2020-03-01"
    assert r["country"] == "Mexico" and r["ISO3N"] == "484" and r["position"] == "president"

    state = load_state(tmp_path / "state" / "Mexico.json")
    assert state["last_doc_num"] == 142
    assert set(df["source"]) <= set(state["seen_urls"]) and "https://x/a" in state["seen_urls"]
    assert list((tmp_path / "state").glob("Mexico.json.bak-import-*"))

    assert (out / "mex_test_import_links.txt").read_text(encoding="utf-8").split() == list(df["source"])
    extra = pd.read_parquet(out / "mex_test_import_import_extra.parquet")
    assert list(extra["doc_id"]) == ["MEX0141", "MEX0142"]
    assert extra.iloc[1]["text_en_leader_only"] == "Good morning 2."
    side = json.loads((out / "mex_test_import_import.json").read_text(encoding="utf-8"))
    assert side["imports"][0]["doc_ids"] == ["MEX0141", "MEX0142"]


def test_rerun_imports_nothing_and_input_duplicates_fold(tmp_path):
    dup = _row(1, url="http://gob.mx:80/presidencia/es/articulos/discurso-1?idiom=es")
    spec, out_root, state_root = _setup(tmp_path, [_row(1), dup, _row(2, text="")])
    plan = import_legacy.plan_import(spec, out_root, state_root)
    assert len(plan["rows"]) == 1
    assert plan["skipped"]["duplicate_in_input"] == 1 and plan["skipped"]["no_text"] == 1
    import_legacy.apply_import(plan)
    again = import_legacy.plan_import(spec, out_root, state_root)
    assert again["rows"] == [] and again["skipped"]["already_held"] == 2


def test_spec_identity_knobs_skip_rows_held_under_another_url_form(tmp_path):
    """An earlier Archive run holds the article as http://…/presidencia/articulos/<slug>; the
    legacy table has …/presidencia/es/articulos/<slug>?idiom=es. Same document — skip it."""
    spec, out_root, state_root = _setup(
        tmp_path, [_row(1), _row(2)],
        state={"last_doc_num": 5,
               "seen_urls": ["http://www.gob.mx:80/presidencia/articulos/discurso-1"]})
    assert len(import_legacy.plan_import(spec, out_root, state_root)["rows"]) == 2   # no knobs
    spec["identity_noise_params"] = ["idiom"]
    spec["identity_strip"] = [r"(?<=/presidencia)/es(?=/)"]
    plan = import_legacy.plan_import(spec, out_root, state_root)
    assert [r["source"].rsplit("/", 1)[1] for r in plan["rows"]] == ["discurso-2?idiom=es"]
    assert plan["skipped"]["already_held"] == 1 and plan["rows"][0]["doc_id"] == "MEX0006"


def test_imported_urls_are_skipped_by_a_wayback_harvest(tmp_path):
    """The point of the import: the Archive recipe must not re-fetch these. Its captures come
    back as http://…:80/ forms, without the ?idiom=es UI toggle, and often without the /es
    segment — the recipe's noise param and identity_strip make them the same document."""
    spec, out_root, state_root = _setup(tmp_path, [_row(1)], state={"last_doc_num": 0, "seen_urls": []})
    import_legacy.apply_import(import_legacy.plan_import(spec, out_root, state_root))
    skip = set(load_state(tmp_path / "state" / "Mexico.json")["seen_urls"])
    captures = ["http://www.gob.mx:80/presidencia/articulos/discurso-1",
                "http://www.gob.mx:80/presidencia/es/articulos/discurso-1?idiom=es",
                "http://www.gob.mx:80/presidencia/articulos/discurso-9"]
    kept, already, _ = select_unscraped(captures, lambda u: u, skip, noise_params=["idiom"],
                                        identity_strip=[r"(?<=/presidencia)/es(?=/)"])
    assert kept == ["http://www.gob.mx:80/presidencia/articulos/discurso-9"] and already == 2


def test_index_labels_an_imported_source(tmp_path):
    spec, out_root, state_root = _setup(tmp_path, [_row(1)], state={"last_doc_num": 0, "seen_urls": []})
    import_legacy.apply_import(import_legacy.plan_import(spec, out_root, state_root))
    (tmp_path / "recipes").mkdir()
    path = index.build_index(out_root, str(tmp_path / "recipes"))
    row = pd.read_excel(path, dtype=str).iloc[0]
    assert row["renderer"] == "import" and row["pagination_type"] == "legacy_import"
    assert row["notes"] == "test import"


def test_spec_validation(tmp_path):
    (tmp_path / "bad.yml").write_text("source_id: x\ncountry: Mexico\nsource_language: Spanish\n"
                                      "input: a.csv\ncolumns: {source: list}\n", encoding="utf-8")
    with pytest.raises(import_legacy.ImportSpecError, match="columns.text"):
        import_legacy.load_spec(tmp_path / "bad.yml")
    (tmp_path / "bad2.yml").write_text("source_id: x\ncountry: Mexico\nsource_language: English\n"
                                       "input: a.csv\ncolumns: {source: s, text: t}\n"
                                       "english: {text: t}\n", encoding="utf-8")
    with pytest.raises(import_legacy.ImportSpecError, match="non-English"):
        import_legacy.load_spec(tmp_path / "bad2.yml")
