"""Leader-tenure curation tests with the LLM stubbed: position pre-filter, inventory
aggregation + bucketing, the GPT-classify path (mocked), and the gated merge (dedupe,
year expansion, approval filtering, atomic apply with backup)."""

import pandas as pd
import pytest

from leaderspeech.clean_structure_metadata import tenure
from leaderspeech.leader_tenure import classify, inventory, merge, verify
from leaderspeech.leader_tenure.config import TenureConfig


# --------------------------------------------------------------- position pre-filter
def test_classify_by_position():
    assert classify.classify_by_position("X", "President")[0] is True
    assert classify.classify_by_position("X", "Prime Minister")[0] is True
    assert classify.classify_by_position("X", "Foreign Minister")[0] is False
    assert classify.classify_by_position("X", "Ambassador")[0] is False
    assert classify.classify_by_position("X", "Vice President")[0] is False  # excluded before include
    assert classify.classify_by_position("X", "")[2] == "gpt"               # ambiguous -> model
    assert classify.classify_by_position("X", None)[2] == "gpt"


# --------------------------------------------------------------- inventory + buckets
@pytest.fixture
def tenure_df(tmp_path):
    csv = tmp_path / "tenure.csv"
    pd.DataFrame([
        dict(speaker="Pat Leader", ISO3N=999, country="Testland", year=2019,
             matchDF="leader", COWcode=2, stateabb="TST", ccode=900, is_ceremonial=False),
        dict(speaker="Pat Leader", ISO3N=999, country="Testland", year=2020,
             matchDF="leader", COWcode=2, stateabb="TST", ccode=900, is_ceremonial=False),
        dict(speaker="Otto Abroad", ISO3N=111, country="Otherland", year=2020,
             matchDF="leader", COWcode=3, stateabb="OTH", ccode=800, is_ceremonial=False),
    ]).to_csv(csv, index=False)
    return tenure.load_tenure(csv), csv


def _speeches():
    common = dict(date="2020-01-01")
    return pd.DataFrame([
        dict(speaker="Pat Leader", country="Testland", position="President", **common),
        dict(speaker="Pat Leader", country="Testland", position="President", date="2020-02-01"),
        dict(speaker="Otto Abroad", country="Testland", position="President", **common),   # wrong country
        dict(speaker="Nadia New", country="Testland", position="Prime Minister", date="2021-01-01"),
        dict(speaker="Nadia New", country="Testland", position="Prime Minister", date="2022-01-01"),
        dict(speaker="", country="Testland", position="", **common),                       # dropped
    ])


def test_build_inventory_aggregates():
    inv = inventory.build_inventory(_speeches())
    pat = inv[inv.speaker == "Pat Leader"].iloc[0]
    assert pat["n_speeches"] == 2 and pat["min_year"] == 2020 and pat["position"] == "President"
    assert "" not in set(inv["speaker"])           # blank speaker dropped
    nadia = inv[inv.speaker == "Nadia New"].iloc[0]
    assert nadia["min_year"] == 2021 and nadia["max_year"] == 2022


def test_bucket_inventory(tenure_df):
    tdf, _ = tenure_df
    bucketed = inventory.bucket_inventory(inventory.build_inventory(_speeches()), tdf)
    buckets = inventory.split_buckets(bucketed)
    assert set(buckets["matched"]["speaker"]) == {"Pat Leader"}
    assert set(buckets["wrong_country"]["speaker"]) == {"Otto Abroad"}
    assert set(buckets["unmatched"]["speaker"]) == {"Nadia New"}
    # matched leader carries its tenure year range
    pat = buckets["matched"].iloc[0]
    assert pat["tenure_min_year"] == 2019 and pat["tenure_max_year"] == 2020


# --------------------------------------------------------------- classify (position + mocked GPT)
def test_classify_unmatched_position_only():
    unmatched = pd.DataFrame([
        dict(speaker="Nadia New", country="Testland", position="Prime Minister", n_speeches=2,
             min_year=2021, max_year=2022),
        dict(speaker="Vic Deputy", country="Testland", position="Vice President", n_speeches=1,
             min_year=2021, max_year=2021),
    ])
    out = classify.classify_unmatched(unmatched, TenureConfig(), client=None)   # no GPT
    assert out[out.speaker == "Nadia New"].iloc[0]["is_leader"] is True
    assert out[out.speaker == "Vic Deputy"].iloc[0]["is_leader"] is False


def test_classify_unmatched_uses_gpt_for_ambiguous(monkeypatch):
    async def fake_classify_one(client, model, config, row, sem):
        return {"is_leader": True, "role": "President", "reasoning": "mocked"}
    monkeypatch.setattr(classify, "classify_one", fake_classify_one)

    unmatched = pd.DataFrame([
        dict(speaker="Amb Iguous", country="Testland", position="", n_speeches=3, min_year=2019, max_year=2019),
    ])
    out = classify.classify_unmatched(unmatched, TenureConfig(), client=object())
    assert out.iloc[0]["classification_method"] == "gpt"
    assert out.iloc[0]["is_leader"] is True and out.iloc[0]["role"] == "President"


def test_verify_proposals_mocked(monkeypatch):
    async def fake_verify_one(client, model, config, row, sem):
        return {"gpt_is_leader": True, "gpt_actual_role": "President", "is_ceremonial": False,
                "gpt_confidence": "high", "gpt_reasoning": "mocked", "wikipedia_extract": ""}
    monkeypatch.setattr(verify, "verify_one", fake_verify_one)

    proposed = pd.DataFrame([dict(speaker="Nadia New", country="Testland", role="Prime Minister",
                                  min_year=2021, max_year=2022, n_speeches=2)])
    out = verify.verify_proposals(proposed, TenureConfig(), client=object())
    assert out.iloc[0]["gpt_is_leader"] is True and out.iloc[0]["gpt_confidence"] == "high"


# --------------------------------------------------------------- merge (gated apply)
def _outbox(tmp_path):
    path = tmp_path / "outbox.xlsx"
    pd.DataFrame([
        dict(approved="yes", speaker="Manual Yes", country="Testland", min_year=2015, max_year=2016,
             gpt_is_leader=False, gpt_confidence="low", gpt_actual_role="President", is_ceremonial=False),
        dict(approved="", speaker="Nadia New", country="Testland", min_year=2021, max_year=2022,
             gpt_is_leader=True, gpt_confidence="high", gpt_actual_role="Prime Minister", is_ceremonial=False),
        dict(approved="no", speaker="Rejected One", country="Testland", min_year=2021, max_year=2021,
             gpt_is_leader=True, gpt_confidence="high", gpt_actual_role="President", is_ceremonial=False),
        dict(approved="", speaker="Low Conf", country="Testland", min_year=2021, max_year=2021,
             gpt_is_leader=True, gpt_confidence="low", gpt_actual_role="President", is_ceremonial=False),
    ]).to_excel(path, index=False)
    return path


def test_load_approved_applies_rules(tmp_path):
    approved = merge.load_approved(_outbox(tmp_path), ["high", "medium"])
    names = set(approved["speaker"])
    assert names == {"Manual Yes", "Nadia New"}          # explicit-yes + blank/high; no + low excluded


def test_expand_and_dedupe(tenure_df):
    tdf, _ = tenure_df
    approved = pd.DataFrame([
        dict(speaker="Nadia New", country="Testland", min_year=2021, max_year=2022,
             gpt_actual_role="Prime Minister", is_ceremonial=False),
        dict(speaker="Nadia New", country="Testland", min_year=2020, max_year=2020,   # dup, widens span
             gpt_actual_role="Prime Minister", is_ceremonial=False),
    ])
    deduped = merge.dedupe(approved)
    assert len(deduped) == 1 and deduped.iloc[0]["min_year"] == 2020 and deduped.iloc[0]["max_year"] == 2022
    new_rows, missing = merge.expand_to_leader_years(deduped, tdf)
    # 2020 already exists for... no (that's Pat Leader); Nadia New 2020-2022 -> 3 rows, codes filled
    assert len(new_rows) == 3 and not missing
    assert set(new_rows["stateabb"]) == {"TST"} and set(new_rows["matchDF"]) == {"speechOnly"}


def test_apply_additions_writes_backup_and_keeps_rows(tenure_df):
    tdf, csv = tenure_df
    before = pd.read_csv(csv)
    new_rows, _ = merge.expand_to_leader_years(
        pd.DataFrame([dict(speaker="Nadia New", country="Testland", min_year=2021, max_year=2021,
                           is_ceremonial=False)]), tdf)
    bak = merge.apply_additions(str(csv), new_rows)
    after = pd.read_csv(csv)
    assert len(after) == len(before) + 1                 # one row appended, none dropped
    assert pd.read_csv(bak).equals(before)               # backup is the pre-write file
    assert "Nadia New" in set(after["speaker"])
