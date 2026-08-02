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


# --- the date pre-pass (PASS 1): the date must be settled BEFORE the tenure key is consulted ----

# the real UZB0001 shape: delivered 05.12.2016, crawled 2024-05-27, no site date.
UZB_TEXT = ("05.12.2016\nThe following congratulatory message has come from President of the "
            "Russian Federation, addressed to the President-elect of Uzbekistan:")


def _uzb_env(tmp_path, monkeypatch, *, tenure_years=(2016, 2024)):
    """A one-row source with NO site date and a capture date years later, plus a tenure key that
    names a DIFFERENT leader in the capture year than in the true year -- so a wrong date is
    visible in the speaker attribution, not just the date column."""
    scraped_root = tmp_path / "scraped"
    csv_path = scraped_root / "Uzbek" / "uzb_src.csv"
    csv_path.parent.mkdir(parents=True)
    row = dict(doc_id="UZB0001", country="Uzbek", ISO3N="860", speaker="", position="",
               date="", wayback_capture="2024-05-27", text=UZB_TEXT,
               source="http://president.uz/en/lists/view/10",
               source_language="English", dataset="LeaderSpeech")
    df = pd.DataFrame([row])
    for c in store.SCRAPED_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df[store.SCRAPED_COLUMNS].to_csv(csv_path, index=False)

    tenure_csv = tmp_path / "tenure.csv"
    pd.DataFrame([
        dict(speaker="Old Leader", country="Uzbek", year=tenure_years[0], is_ceremonial=False),
        dict(speaker="New Leader", country="Uzbek", year=tenure_years[1], is_ceremonial=False),
    ]).to_csv(tenure_csv, index=False)

    events = []          # ordered log of what happened, so we can assert on SEQUENCE

    async def fake_extract_date_one(client, config, message, sem):
        events.append(("date_pass", message))
        return dict(date="2016-12-05", date_confidence="high",
                    date_basis="dateline '05.12.2016' on the first line")

    async def fake_extract_one(client, config, message, sem):
        events.append(("full_pass", message))
        return dict(document_type="speech", is_first_person="yes", speaker="Old Leader",
                    speaker_attributed_correct="unsure", speaker_type="head_of_state",
                    position="President", date="2016-12-05", date_matches_metadata="yes",
                    language="en", audience="General Public", speech_type="Other",
                    venue=None, confidence="high", reasoning="congratulatory message")

    monkeypatch.setattr(extract, "extract_date_one", fake_extract_date_one)
    monkeypatch.setattr(extract, "extract_one", fake_extract_one)
    monkeypatch.setattr(llm, "load_api_key", lambda config: "test-key")
    monkeypatch.setattr(llm, "create_async_client", lambda key: object())

    config = CleanConfig(tenure_file=str(tenure_csv), chunk_size=2, batch_size=2)
    return dict(tmp=tmp_path, scraped_root=scraped_root, config=config, events=events)


def _run_uzb(e, **kw):
    return pipeline.clean_source(
        "uzb_src", in_root=str(e["scraped_root"]), out_root=str(e["tmp"] / "cleaned"),
        state_root=str(e["tmp"] / "clean_state"), config=e["config"], country="Uzbek", **kw)


def _uzb_out(e):
    return pd.read_parquet(Path(e["tmp"]) / "cleaned" / "Uzbek" / "uzb_src.parquet")


def test_date_pass_runs_before_the_full_call(tmp_path, monkeypatch):
    """The ordering requirement itself: the date is settled first, so the tenure key is keyed on
    the right year instead of propagating a crawl-date year into speaker attribution."""
    e = _uzb_env(tmp_path, monkeypatch)
    _run_uzb(e)
    kinds = [k for k, _ in e["events"]]
    assert kinds == ["date_pass", "full_pass"]


def test_date_pass_message_carries_no_leader_roster(tmp_path, monkeypatch):
    """PASS 1 must not see the roster -- the roster is chosen FROM its answer, so including it
    would reintroduce the circularity the pre-pass exists to break."""
    e = _uzb_env(tmp_path, monkeypatch)
    _run_uzb(e)
    date_msg = next(m for k, m in e["events"] if k == "date_pass")
    assert "KNOWN LEADERS IN OFFICE" not in date_msg
    assert "ARCHIVE CAPTURE DATE: 2024-05-27" in date_msg
    assert "CANDIDATE DATE FROM TEXT" in date_msg


def test_capture_date_is_never_presented_as_the_documents_date(tmp_path, monkeypatch):
    """THE regression test for the original bug: the crawl timestamp used to be written straight
    into `DATE:`, which is what made the model echo it 83-99% of the time. It may appear ONLY on
    the labelled ARCHIVE CAPTURE DATE line -- so match the `DATE:` line exactly, not a substring
    (which would also hit "ARCHIVE CAPTURE DATE: ...")."""
    e = _uzb_env(tmp_path, monkeypatch)
    _run_uzb(e)
    for _, msg in e["events"]:
        date_lines = [ln for ln in msg.splitlines() if ln.startswith("DATE:")]
        assert "2024-05-27" not in " ".join(date_lines)
        assert any(ln.startswith("ARCHIVE CAPTURE DATE: 2024-05-27") for ln in msg.splitlines())


def test_confirmed_date_picks_the_leader_roster(tmp_path, monkeypatch):
    e = _uzb_env(tmp_path, monkeypatch)
    _run_uzb(e)
    full_msg = next(m for k, m in e["events"] if k == "full_pass")
    assert "DATE: 2016-12-05" in full_msg
    assert "Old Leader" in full_msg          # the 2016 roster...
    assert "New Leader" not in full_msg      # ...not the 2024 capture-year one


def test_date_pass_result_is_stored_with_its_provenance(tmp_path, monkeypatch):
    e = _uzb_env(tmp_path, monkeypatch)
    _run_uzb(e)
    out = _uzb_out(e).iloc[0]
    assert out["date"] == "2016-12-05"
    assert out["date_precision"] == "model"          # GPT decided it, not the regex or the capture
    assert out["date_regex_recovered"] == "2016-12-05"   # the candidate is kept win or lose
    assert out["date_confidence"] == "high"
    assert bool(out["date_is_fallback"]) is False
    assert out["date_scraped"] == ""                 # the audit copy keeps the original (empty)
    assert out["wayback_capture"] == "2024-05-27"    # the bound is retained
    assert out["tenure_match"] == "exact"            # matched against 2016, not 2024


def test_rows_with_a_site_date_skip_the_date_pass(env):
    """The cost guarantee: the common path still makes exactly ONE call per row."""
    _run(env)
    assert len(env["calls"]) == 5                    # 5 rows, 5 full calls, no pre-pass


def test_date_pass_failure_is_not_fatal(tmp_path, monkeypatch):
    """A dead pre-pass must degrade, not sink the run. With the full pass also offering no date,
    the row falls back to the deterministic head-line candidate -- exactly the behaviour that
    existed before the pre-pass was added."""
    e = _uzb_env(tmp_path, monkeypatch)

    async def boom(client, config, message, sem):
        raise RuntimeError("api down")

    async def no_date(client, config, message, sem):
        return dict(document_type="speech", is_first_person="yes", speaker="Old Leader",
                    speaker_type="head_of_state", date=None, date_matches_metadata="unsure",
                    confidence="high", reasoning="date unclear")

    monkeypatch.setattr(extract, "extract_date_one", boom)
    monkeypatch.setattr(extract, "extract_one", no_date)
    _run_uzb(e)
    out = _uzb_out(e).iloc[0]
    assert out["date"] == "2016-12-05"
    assert out["date_precision"] == "regex_text"


# --- --redate: free retroactive backfill from stored columns ------------------------------------

def _redate_env(tmp_path, monkeypatch):
    """Reproduce the state every already-cleaned wayback row is in TODAY: no pre-pass, no text
    parser, and a model that supplied no usable date -- so the row landed on the capture date.
    Then --redate repairs it for free."""
    e = _uzb_env(tmp_path, monkeypatch)

    async def no_date(client, config, message, sem):
        e["events"].append(("full_pass", message))
        return dict(document_type="speech", is_first_person="yes", speaker="Old Leader",
                    speaker_type="head_of_state", date=None, date_matches_metadata="unsure",
                    confidence="high", reasoning="date unclear")

    monkeypatch.setattr(extract, "extract_one", no_date)
    e["config"] = e["config"].model_copy(
        update={"date_text_enabled": False, "date_pass_enabled": False})
    _run_uzb(e)
    return e


def test_redate_repairs_a_capture_dated_row_with_no_api_calls(tmp_path, monkeypatch):
    e = _redate_env(tmp_path, monkeypatch)
    before = _uzb_out(e).iloc[0]
    assert before["date_precision"] == "wayback_capture"
    assert bool(before["date_is_fallback"]) is True

    calls_before = len(e["events"])
    cfg = e["config"].model_copy(update={"date_text_enabled": True})
    res = pipeline.regate_source("uzb_src", out_root=str(e["tmp"] / "cleaned"),
                                 config=cfg, country="Uzbek", redate=True)

    assert len(e["events"]) == calls_before          # no API calls at all
    assert res["redated"] == 1
    after = _uzb_out(e).iloc[0]
    assert after["date"] == "2016-12-05"
    assert after["date_precision"] == "regex_text"
    assert bool(after["date_is_fallback"]) is False


def test_redate_is_idempotent(tmp_path, monkeypatch):
    e = _redate_env(tmp_path, monkeypatch)
    cfg = e["config"].model_copy(update={"date_text_enabled": True})
    kw = dict(out_root=str(e["tmp"] / "cleaned"), config=cfg, country="Uzbek", redate=True)
    pipeline.regate_source("uzb_src", **kw)
    first = _uzb_out(e).iloc[0]["date"]
    res2 = pipeline.regate_source("uzb_src", **kw)
    assert res2["redated"] == 0                      # second pass changes nothing
    assert _uzb_out(e).iloc[0]["date"] == first


def test_redate_reads_date_scraped_not_the_resolved_date(tmp_path, monkeypatch):
    """THE trap: `date` in a cleaned Parquet is the RESOLVED value. Feeding it back in would
    re-launder the capture date as a trusted `scraped` date, permanently."""
    e = _redate_env(tmp_path, monkeypatch)
    stored = _uzb_out(e).iloc[0]
    assert stored["date"] == "2024-05-27"            # the resolved value IS the capture date
    assert stored["date_scraped"] == ""              # ...but the site never supplied one

    cfg = e["config"].model_copy(update={"date_text_enabled": True})
    pipeline.regate_source("uzb_src", out_root=str(e["tmp"] / "cleaned"),
                           config=cfg, country="Uzbek", redate=True)
    after = _uzb_out(e).iloc[0]
    assert after["date_precision"] != "scraped"      # must NOT have been laundered
    assert after["date_scraped"] == ""               # and the audit copy is untouched


def test_redate_rekeys_the_tenure_crosscheck_on_the_corrected_year(tmp_path, monkeypatch):
    e = _redate_env(tmp_path, monkeypatch)
    cfg = e["config"].model_copy(update={"date_text_enabled": True})
    pipeline.regate_source("uzb_src", out_root=str(e["tmp"] / "cleaned"),
                           config=cfg, country="Uzbek", redate=True)
    after = _uzb_out(e).iloc[0]
    assert after["date"].startswith("2016")
    assert after["tenure_matched_name"] == "Old Leader"   # the 2016 leader, not the 2024 one


def test_plain_regate_does_not_touch_the_date(tmp_path, monkeypatch):
    e = _redate_env(tmp_path, monkeypatch)
    cfg = e["config"].model_copy(update={"date_text_enabled": True})
    pipeline.regate_source("uzb_src", out_root=str(e["tmp"] / "cleaned"),
                           config=cfg, country="Uzbek")     # redate=False
    assert _uzb_out(e).iloc[0]["date"] == "2024-05-27"
