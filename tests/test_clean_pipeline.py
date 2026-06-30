"""End-to-end pipeline test with the LLM mocked (no network): cleans a tiny source,
checks the gate outcomes + tenure crosscheck, verifies resume skips already-cleaned
rows (no extra model calls), and that the merge is idempotent."""

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
    assert row["is_ceremonial"] in (False, 0)
    assert row["speech_type"] == "Policy Announcement"
    assert row["speaker_scraped"] == "Pat Leader"           # audit copy retained


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


def test_merge_is_idempotent(env):
    _run(env)
    out_root = str(env["tmp"] / "cleaned")
    build_path = str(env["tmp"] / "_build" / "merged.parquet")

    p = merge.build_dataset(out_root, build_path)
    merged = pd.read_parquet(p)
    assert len(merged) == 2                                  # the accepted speech + statement
    assert "clean_status" not in merged.columns             # deliverable drops process columns
    assert "speech_type" in merged.columns                  # keeps curated metadata
    assert "document_type" in merged.columns                 # statement-vs-speech distinction kept

    merge.build_dataset(out_root, build_path)                # re-run
    assert len(pd.read_parquet(p)) == 2                      # unchanged
