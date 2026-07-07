"""Translator tests with a STUB backend (no network, no model download): in-place fill of
the English columns, resume/force semantics, only_accepted, chunking, language resolution,
file round-trip, and the derived `is_translated` index column."""

import pandas as pd
import pytest

from leaderspeech.translate import pipeline, store
from leaderspeech.translate.backends import get_translator
from leaderspeech.translate.backends.base import split_into_chunks
from leaderspeech.translate.config import TranslateConfig


class StubTranslator:
    name = "stub"

    def __init__(self):
        self.calls = 0

    def translate(self, text, src_lang=None):
        if not text or not str(text).strip():
            return ""
        self.calls += 1
        return f"[{src_lang or 'auto'}->en] {text}"


def _rows():
    return [
        dict(doc_id="A1", source_language="Spanish", detected_language="es",
             text="", text_originlanguage="Hola mundo",
             title="", title_originlanguage="Discurso",
             context="", context_originlanguage="", clean_status="accepted"),
        dict(doc_id="A2", source_language="English", detected_language="en",
             text="Already English", text_originlanguage="",
             title="T", title_originlanguage="", context="", context_originlanguage="",
             clean_status="accepted"),
        dict(doc_id="A3", source_language="French", detected_language="fr",
             text="", text_originlanguage="Bonjour", title="", title_originlanguage="",
             context="", context_originlanguage="", clean_status="rejected_foreign"),
    ]


def _cfg(**kw):
    base = dict(pause_every=0, checkpoint_every=0)
    base.update(kw)
    return TranslateConfig(**base)


def test_fills_english_in_place_and_records_provenance():
    df = pd.DataFrame(_rows())
    out, n = pipeline.translate_table(df, StubTranslator(), _cfg())
    assert n == 1                                            # only A1 (A2 English, A3 rejected)
    a1 = out[out.doc_id == "A1"].iloc[0]
    assert a1["text"].startswith("[es->en] Hola mundo")
    assert a1["title"].startswith("[es->en] Discurso")
    assert a1["text_translator"] == "stub"
    assert a1["translated_at"]
    # originals are preserved, never overwritten
    assert a1["text_originlanguage"] == "Hola mundo"


def test_english_and_rejected_rows_are_skipped():
    out, _ = pipeline.translate_table(pd.DataFrame(_rows()), StubTranslator(), _cfg())
    assert out[out.doc_id == "A2"].iloc[0]["text"] == "Already English"   # untouched
    assert out[out.doc_id == "A3"].iloc[0]["text"] == ""                  # rejected, skipped


def test_all_rows_flag_translates_rejected():
    out, n = pipeline.translate_table(pd.DataFrame(_rows()), StubTranslator(), _cfg(only_accepted=False))
    assert n == 2                                           # A1 + A3 now
    assert out[out.doc_id == "A3"].iloc[0]["text"].startswith("[fr->en] Bonjour")


def test_resume_skips_already_filled():
    stub = StubTranslator()
    df, n1 = pipeline.translate_table(pd.DataFrame(_rows()), stub, _cfg())
    assert n1 == 1 and stub.calls == 2                      # text + title for A1
    df2, n2 = pipeline.translate_table(df, stub, _cfg())    # second pass
    assert n2 == 0 and stub.calls == 2                      # nothing new translated


def test_force_retranslates():
    df, _ = pipeline.translate_table(pd.DataFrame(_rows()), StubTranslator(), _cfg())
    df2, n = pipeline.translate_table(df, StubTranslator(), _cfg(), force=True)
    assert n == 1                                           # A1 re-translated under --force


def test_limit_caps_rows():
    rows = _rows() + [dict(doc_id="A4", source_language="Spanish", detected_language="es",
                           text="", text_originlanguage="Otra cosa", title="", title_originlanguage="",
                           context="", context_originlanguage="", clean_status="accepted")]
    out, n = pipeline.translate_table(pd.DataFrame(rows), StubTranslator(), _cfg(), limit=1)
    assert n == 1


def test_resolve_src_lang():
    assert pipeline.resolve_src_lang({"detected_language": "es"}) == "es"
    assert pipeline.resolve_src_lang({"source_language": "French"}) == "fr"
    assert pipeline.resolve_src_lang({"source_language": "pt"}) == "pt"   # already a code
    assert pipeline.resolve_src_lang({"source_language": "Klingon"}) is None


def test_split_into_chunks_respects_limit_and_boundaries():
    text = "Sentence one. Sentence two. " * 200
    chunks = split_into_chunks(text, 100)
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == text                          # lossless


def test_translate_file_roundtrip_csv(tmp_path):
    path = tmp_path / "src.csv"
    pd.DataFrame(_rows()).to_csv(path, index=False)
    summary = pipeline.translate_file(path, StubTranslator(), _cfg())
    assert summary["rows_translated"] == 1
    back = store.read_table(path)
    assert back[back.doc_id == "A1"].iloc[0]["text"].startswith("[es->en]")
    assert (tmp_path / "src.csv.bak").exists()              # atomic write kept a backup


def test_factory_unknown_backend_raises():
    with pytest.raises(ValueError):
        get_translator("nope")


def test_index_derives_is_translated(tmp_path):
    from leaderspeech.clean_structure_metadata.merge import build_clean_index

    out_root = tmp_path / "cleaned"
    (out_root / "Argentina").mkdir(parents=True)
    # one fully-translated source, one half-translated
    full = pd.DataFrame([
        dict(doc_id="X1", text="hello", text_originlanguage="hola", clean_status="accepted"),
    ])
    half = pd.DataFrame([
        dict(doc_id="Y1", text="hello", text_originlanguage="hola", clean_status="accepted"),
        dict(doc_id="Y2", text="", text_originlanguage="adios", clean_status="accepted"),
    ])
    full.to_parquet(out_root / "Argentina" / "full.parquet", index=False)
    half.to_parquet(out_root / "Argentina" / "half.parquet", index=False)

    idx_path = build_clean_index(str(out_root))
    idx = pd.read_excel(idx_path).set_index("source_id")
    assert bool(idx.loc["full", "is_translated"]) is True
    assert int(idx.loc["full", "n_translated"]) == 1
    assert bool(idx.loc["half", "is_translated"]) is False
    assert int(idx.loc["half", "n_nonenglish"]) == 2 and int(idx.loc["half", "n_translated"]) == 1
