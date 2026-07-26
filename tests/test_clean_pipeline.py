"""End-to-end pipeline test with the LLM mocked (no network): cleans a tiny source,
checks the gate outcomes + tenure crosscheck, verifies resume skips already-cleaned
rows (no extra model calls), and that the merge is idempotent."""

from pathlib import Path

import pandas as pd
import pytest

from leaderspeech.clean_structure_metadata import extract, llm, merge, pipeline, store
from leaderspeech.clean_structure_metadata.config import CleanConfig


def _scraped_rows():
    common = dict(country="Testland", ISO3N="999", source_language="English", dataset="LeaderSpeech")
    return [
        dict(doc_id="TST0001", speaker="Pat Leader", position="president", date="2020-03-01",
             text="ACCEPT my fellow citizens, today we move forward", source="http://x/1", **common),
        dict(doc_id="TST0002", speaker="", position="", date="2020-04-01",
             text="NOSPEAKER an address delivered at the hall", source="http://x/2", **common),
        dict(doc_id="TST0003", speaker="Pat Leader", position="president", date="2020-05-01",
             text="NOTSPEECH the office announced a schedule", source="http://x/3", **common),
        dict(doc_id="TST0004", speaker="Foreign Guest", position="", date="2020-06-01",
             text="FOREIGN remarks by a visiting head of state", source="http://x/4", **common),
        dict(doc_id="TST0005", speaker="Pat Leader", position="president", date="2020-07-01",
             text="STATEMENT the President expresses condolences and reaffirms policy", source="http://x/5", **common),
    ]


def _meta_for(message):
    if "ACCEPT" in message:
        return dict(document_type="speech", is_first_person="yes", speaker="Pat Leader",
                    speaker_attributed_correct="yes", speaker_type="head_of_state",
                    position="President", date="2020-03-01", date_matches_metadata="yes",
                    language="en", audience="General Public", speech_type="Policy Announcement",
                    venue="Capital City", confidence="high", reasoning="genuine speech")
    if "NOSPEAKER" in message:
        return dict(document_type="speech", is_first_person="yes", speaker=None,
                    speaker_type="unknown", confidence="low", reasoning="no name found")
    if "NOTSPEECH" in message:
        return dict(document_type="other", is_first_person="no", speaker="Pat Leader",
                    speaker_type="head_of_state", confidence="high", reasoning="logistical notice")
    if "FOREIGN" in message:
        return dict(document_type="speech", is_first_person="yes", speaker="Foreign Guest",
                    speaker_type="foreign_visitor", confidence="high", reasoning="a visitor")
    if "STATEMENT" in message:  # third-person communiqué conveying the leader's position -> kept
        return dict(document_type="official_statement", is_first_person="no", speaker="Pat Leader",
                    speaker_type="head_of_state", confidence="high", reasoning="conveys leader's stance")
    if "AFGDATE" in message:  # Emirate-era speech whose page carries a stray old Solar-Hijri date
        return dict(document_type="speech", is_first_person="yes", speaker="Pat Leader",
                    speaker_attributed_correct="yes", speaker_type="head_of_state", position="President",
                    date="2023-01-15", date_matches_metadata="no", language="fa",
                    audience="General Public", speech_type="Policy Announcement", venue="Kabul",
                    confidence="high", reasoning="stray 1351 date on the page; real speech is recent")
    if "AFGGAP" in message:  # a real speech but the model can't pin a date (date=None) -> gap rule alone
        return dict(document_type="speech", is_first_person="yes", speaker="Pat Leader",
                    speaker_attributed_correct="yes", speaker_type="head_of_state", position="President",
                    date=None, date_matches_metadata="unsure", language="fa",
                    audience="General Public", speech_type="Policy Announcement", venue="Kabul",
                    confidence="high", reasoning="date unclear from text")
    return extract.empty_meta()


@pytest.fixture
def env(tmp_path, monkeypatch):
    # scraped input
    scraped_root = tmp_path / "scraped"
    csv_path = scraped_root / "Testland" / "test_src.csv"
    csv_path.parent.mkdir(parents=True)
    df = pd.DataFrame(_scraped_rows())
    for c in store.SCRAPED_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df[store.SCRAPED_COLUMNS].to_csv(csv_path, index=False)

    # tiny tenure key
    tenure_csv = tmp_path / "tenure.csv"
    pd.DataFrame([dict(speaker="Pat Leader", country="Testland", year=2020, is_ceremonial=False)]).to_csv(
        tenure_csv, index=False)

    calls = []

    async def fake_extract_one(client, config, message, sem):
        calls.append(message)
        return _meta_for(message)

    monkeypatch.setattr(extract, "extract_one", fake_extract_one)
    monkeypatch.setattr(llm, "load_api_key", lambda config: "test-key")
    monkeypatch.setattr(llm, "create_async_client", lambda key: object())

    config = CleanConfig(tenure_file=str(tenure_csv), chunk_size=2, batch_size=2)
    return dict(tmp=tmp_path, scraped_root=scraped_root, config=config, calls=calls)


def _run(env, **kw):
    return pipeline.clean_source(
        "test_src", in_root=str(env["scraped_root"]),
        out_root=str(env["tmp"] / "cleaned"), state_root=str(env["tmp"] / "clean_state"),
        config=env["config"], country="Testland", **kw,
    )


def test_clean_gate_outcomes_and_tenure(env):
    summary = _run(env)
    assert summary["accepted"] == 2                          # a speech + an official_statement
    assert summary["rejected"] == 3
    assert summary["errors"] == 0

    out = store.read_source(env["tmp"] / "cleaned" / "Testland" / "test_src.parquet")
    assert len(out) == 5
    statuses = set(out["clean_status"])
    assert statuses == {"accepted", "rejected_no_speaker", "rejected_not_representative", "rejected_foreign"}

    accepted = out[out["clean_status"] == "accepted"]
    assert (accepted["speaker"].str.len() > 0).all()        # every kept row has a speaker
    assert set(accepted["document_type"]) == {"speech", "official_statement"}  # statements kept
    row = accepted[accepted["doc_id"] == "TST0001"].iloc[0]
    assert row["tenure_match"] == "exact"
    assert bool(row["speaker_review"]) is False             # a key-confirmed leader isn't flagged (issue #68)
    assert row["is_ceremonial"] in (False, 0)
    assert row["speech_type"] == "Policy Announcement"
    assert row["speaker_scraped"] == "Pat Leader"           # audit copy retained
    # the date-audit columns are populated: a normal consistent row is NOT flagged, and the
    # model's raw suggestion is recorded independently of what won.
    assert bool(row["date_disagreement_flag"]) is False
    assert row["date_model"] == "2020-03-01"                # GPT's suggestion, always recorded
    assert row["date"] == "2020-03-01" and row["date_precision"] == "scraped"


def test_resume_skips_already_cleaned(env):
    _run(env)
    assert len(env["calls"]) == 5
    summary2 = _run(env)                                     # second pass
    assert summary2["to_clean"] == 0
    assert len(env["calls"]) == 5                            # NO new model calls


def test_dry_run_makes_no_calls(env):
    summary = _run(env, dry_run=True)
    assert summary["dry_run"] is True
    assert len(env["calls"]) == 0


def test_regate_reclassifies_without_api_calls(env):
    from leaderspeech.clean_structure_metadata.config import CleanConfig
    _run(env)
    calls_after_clean = len(env["calls"])

    # tighten the gate to drop official_statements, then regate (no model calls)
    strict = CleanConfig(tenure_file=env["config"].tenure_file,
                         keep_document_types=["speech", "interview"])
    summary = pipeline.regate_source("test_src", out_root=str(env["tmp"] / "cleaned"),
                                     config=strict, country="Testland")
    assert len(env["calls"]) == calls_after_clean        # regate made NO model calls
    assert summary["changed"] == 1                        # the official_statement flipped

    out = store.read_source(env["tmp"] / "cleaned" / "Testland" / "test_src.parquet")
    stmt = out[out["document_type"] == "official_statement"].iloc[0]
    assert stmt["clean_status"] == "rejected_not_representative"
    # the delivered speech is still accepted
    assert (out[out["document_type"] == "speech"]["clean_status"] == "accepted").any()


def test_input_mode_mixed_corpus(tmp_path, monkeypatch):
    """--input mode: clean ONE arbitrary table that mixes countries and datasets and carries an
    extra ISI_id column. Proves (1) per-row country drives the tenure crosscheck across a mixed
    table, (2) unknown columns survive cleaning, (3) resume works off the sibling output parquet."""
    calls = []

    async def fake_extract_one(client, config, message, sem):
        calls.append(message)
        return _meta_for(message)

    monkeypatch.setattr(extract, "extract_one", fake_extract_one)
    monkeypatch.setattr(llm, "load_api_key", lambda config: "test-key")
    monkeypatch.setattr(llm, "create_async_client", lambda key: object())

    # combined corpus: two countries, two datasets, a NON-schema column (ISI_id), only a subset
    # of the standardized columns present (read_input + _base_row fill the rest).
    common = dict(ISO3N="", position="", source="http://x", source_language="English")
    rows = [
        dict(doc_id="COR0001", country="Testland", speaker="Pat Leader", date="2020-03-01",
             text="ACCEPT fellow citizens, today we move forward", dataset="DatasetA", ISI_id="ISI-1", **common),
        dict(doc_id="COR0002", country="Otherland", speaker="Sam Chief", date="2021-05-01",
             text="ACCEPT my compatriots, together we rise", dataset="DatasetB", ISI_id="ISI-2", **common),
    ]
    in_path = tmp_path / "corpus.parquet"
    pd.DataFrame(rows).to_parquet(in_path, index=False)

    # tenure key covering BOTH countries
    tenure_csv = tmp_path / "tenure.csv"
    pd.DataFrame([
        dict(speaker="Pat Leader", country="Testland", year=2020, is_ceremonial=False),
        dict(speaker="Sam Chief", country="Otherland", year=2021, is_ceremonial=False),
    ]).to_csv(tenure_csv, index=False)
    config = CleanConfig(tenure_file=str(tenure_csv), chunk_size=2, batch_size=2)

    out_path = tmp_path / "corpus.cleaned.parquet"
    summary = pipeline.clean_file(in_path, out_path, config=config, label="corpus")

    assert summary["accepted"] == 2
    assert Path(summary["output"]) == out_path and out_path.exists()          # sibling, not in place

    out = store.read_source(out_path).set_index("doc_id")
    assert (out["clean_status"] == "accepted").all()
    # per-row country (not a folder name) drove the tenure crosscheck for each row
    assert out.loc["COR0001", "country"] == "Testland" and out.loc["COR0001", "tenure_match"] == "exact"
    assert out.loc["COR0002", "country"] == "Otherland" and out.loc["COR0002", "tenure_match"] == "exact"
    assert out.loc["COR0002", "speaker"] == "Sam Chief"                        # scraped speaker kept per row
    # the non-schema column survived cleaning
    assert set(out["ISI_id"]) == {"ISI-1", "ISI-2"}

    # resume: a second pass reads the sibling parquet and sends nothing new to the model
    calls_after = len(calls)
    summary2 = pipeline.clean_file(in_path, out_path, config=config, label="corpus")
    assert summary2["to_clean"] == 0
    assert len(calls) == calls_after


def test_date_disagreement_flagged_and_adjudicated_end_to_end(tmp_path, monkeypatch):
    """A wayback row whose Persian body carries a stray Solar-Hijri date (1351/12/22 -> 1973) far
    from its 2023 capture: the parse must NOT silently win. The model adjudicates to a plausible
    recent date, and the row is flagged for review with the raw parse recorded."""
    async def fake_extract_one(client, config, message, sem):
        return _meta_for(message)
    monkeypatch.setattr(extract, "extract_one", fake_extract_one)
    monkeypatch.setattr(llm, "load_api_key", lambda config: "test-key")
    monkeypatch.setattr(llm, "create_async_client", lambda key: object())

    common = dict(ISO3N="", position="", source="http://x", source_language="Dari")
    rows = [dict(doc_id="AFG9001", country="Testland", speaker="", date="",
                 text_originlanguage="AFGDATE ۱۳۵۱/۱۲/۲۲ سخنرانی رهبر امارت اسلامی",
                 wayback_capture="2023-12-04", dataset="LeaderSpeech", **common)]
    in_path = tmp_path / "afg.parquet"
    pd.DataFrame(rows).to_parquet(in_path, index=False)

    tenure_csv = tmp_path / "tenure.csv"
    pd.DataFrame([dict(speaker="Pat Leader", country="Testland", year=2023, is_ceremonial=False)]).to_csv(
        tenure_csv, index=False)
    config = CleanConfig(tenure_file=str(tenure_csv), chunk_size=2, batch_size=2)

    out_path = tmp_path / "afg.cleaned.parquet"
    pipeline.clean_file(in_path, out_path, config=config, label="afg")

    out = store.read_source(out_path).set_index("doc_id")
    r = out.loc["AFG9001"]
    assert bool(r["date_disagreement_flag"]) is True          # not silently trusted
    assert r["date_parsed"] == "1973-03-13"                   # the raw misparse recorded for audit
    assert r["date_model"] == "2023-01-15"                    # GPT's suggestion recorded
    assert r["date"] == "2023-01-15" and r["date_precision"] == "model"   # GPT adjudicated the winner


def test_stricter_date_flag_years_config_is_honored(tmp_path, monkeypatch):
    """A 2016 speech captured 2021 (gap 5) is trusted at the default, but flagged when the
    config tightens date_flag_years to 3 -- proving the knob threads through the pipeline."""
    async def fake_extract_one(client, config, message, sem):
        return _meta_for(message)
    monkeypatch.setattr(extract, "extract_one", fake_extract_one)
    monkeypatch.setattr(llm, "load_api_key", lambda config: "test-key")
    monkeypatch.setattr(llm, "create_async_client", lambda key: object())

    common = dict(ISO3N="", position="", source="http://x", source_language="Dari")
    rows = [dict(doc_id="AFG9002", country="Testland", speaker="", date="",
                 text_originlanguage="AFGGAP ۱۹ حمل ۱۳۹۵ سخنرانی", wayback_capture="2021-08-16",
                 dataset="LeaderSpeech", **common)]
    in_path = tmp_path / "afg2.parquet"
    pd.DataFrame(rows).to_parquet(in_path, index=False)
    tenure_csv = tmp_path / "tenure.csv"
    pd.DataFrame([dict(speaker="Pat Leader", country="Testland", year=2016, is_ceremonial=False)]).to_csv(
        tenure_csv, index=False)

    strict = CleanConfig(tenure_file=str(tenure_csv), chunk_size=2, batch_size=2, date_flag_years=3)
    out_path = tmp_path / "afg2.cleaned.parquet"
    pipeline.clean_file(in_path, out_path, config=strict, label="afg2")
    r = store.read_source(out_path).set_index("doc_id").loc["AFG9002"]
    assert bool(r["date_disagreement_flag"]) is True


def test_regate_backfills_speaker_review(tmp_path, monkeypatch):
    """A plausible national leader NOT in the tenure key is accepted (head_of_state passes the
    gate) AND flagged speaker_review=True (tenure_match=none). --regate recomputes the flag from
    stored fields with no API calls and must NOT un-accept the row (issue #68)."""
    calls = []

    async def fake_extract_one(client, config, message, sem):
        calls.append(message)
        return dict(document_type="speech", is_first_person="yes", speaker="Newcomer Chief",
                    speaker_attributed_correct="yes", speaker_type="head_of_state",
                    position="President", date="2022-01-01", date_matches_metadata="yes",
                    language="en", audience="General Public", speech_type="Policy Announcement",
                    venue="Capital", confidence="high", reasoning="genuine speech by an unlisted leader")

    monkeypatch.setattr(extract, "extract_one", fake_extract_one)
    monkeypatch.setattr(llm, "load_api_key", lambda config: "test-key")
    monkeypatch.setattr(llm, "create_async_client", lambda key: object())

    scraped_root = tmp_path / "scraped"
    csv_path = scraped_root / "Testland" / "unlisted.csv"
    csv_path.parent.mkdir(parents=True)
    common = dict(country="Testland", ISO3N="999", source_language="English", dataset="LeaderSpeech")
    df = pd.DataFrame([dict(doc_id="UNL0001", speaker="Newcomer Chief", position="president",
                            date="2022-01-01", text="my fellow citizens, we chart a new course",
                            source="http://x/1", **common)])
    for c in store.SCRAPED_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df[store.SCRAPED_COLUMNS].to_csv(csv_path, index=False)

    # tenure key that does NOT contain "Newcomer Chief"
    tenure_csv = tmp_path / "tenure.csv"
    pd.DataFrame([dict(speaker="Pat Leader", country="Testland", year=2020, is_ceremonial=False)]).to_csv(
        tenure_csv, index=False)
    config = CleanConfig(tenure_file=str(tenure_csv), chunk_size=2, batch_size=2)

    out_root = tmp_path / "cleaned"
    pipeline.clean_source("unlisted", in_root=str(scraped_root), out_root=str(out_root),
                          state_root=str(tmp_path / "clean_state"), config=config, country="Testland")
    r = store.read_source(out_root / "Testland" / "unlisted.parquet").set_index("doc_id").loc["UNL0001"]
    assert r["clean_status"] == "accepted"                   # head_of_state passes the gate
    assert r["tenure_match"] == "none"                       # not in the key
    assert bool(r["speaker_review"]) is True                 # flagged for tenure-key curation

    calls_after = len(calls)
    pipeline.regate_source("unlisted", out_root=str(out_root), config=config, country="Testland")
    assert len(calls) == calls_after                         # regate made NO model calls
    r2 = store.read_source(out_root / "Testland" / "unlisted.parquet").set_index("doc_id").loc["UNL0001"]
    assert bool(r2["speaker_review"]) is True
    assert r2["clean_status"] == "accepted"                  # NOT un-accepted by regate


def test_merge_is_idempotent(env):
    _run(env)
    out_root = str(env["tmp"] / "cleaned")
    build_path = str(env["tmp"] / "_build" / "merged.parquet")

    p = merge.build_dataset(out_root, build_path)            # default keep="speakers"
    merged = pd.read_parquet(p)
    assert len(merged) == 3                                  # 2 accepted + the foreign-visitor speech
    assert "clean_status" in merged.columns                 # carried so users can filter downstream
    assert "is_substantive" in merged.columns               # (and the substantive/courtesy split)
    assert "speech_type" in merged.columns                  # keeps curated metadata
    assert "document_type" in merged.columns                 # statement-vs-speech distinction kept

    merge.build_dataset(out_root, build_path, keep="accepted")  # leader-only reverts to accepted
    assert len(pd.read_parquet(p)) == 2                      # just the accepted speech + statement

    merge.build_dataset(out_root, build_path)                # re-run default -> unchanged (idempotent)
    assert len(pd.read_parquet(p)) == 3
