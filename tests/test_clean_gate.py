from leaderspeech.clean_structure_metadata import gate
from leaderspeech.clean_structure_metadata.config import CleanConfig


def _meta(**kw):
    base = dict(document_type="speech", speaker="Pat Leader", speaker_type="head_of_state")
    base.update(kw)
    return base


def test_accepts_a_delivered_speech():
    status, reason = gate.decide(_meta(), CleanConfig())
    assert status == gate.ACCEPTED
    assert reason == ""


def test_accepts_an_official_statement():
    # the FRA1837 case: a third-person communiqué that conveys the leader's position
    status, _ = gate.decide(_meta(document_type="official_statement"), CleanConfig())
    assert status == gate.ACCEPTED


def test_accepts_an_interview():
    status, _ = gate.decide(_meta(document_type="interview"), CleanConfig())
    assert status == gate.ACCEPTED


def test_rejects_other_doctype():
    status, _ = gate.decide(_meta(document_type="other"), CleanConfig())
    assert status == gate.REJECTED_NOT_REPRESENTATIVE


def test_rejects_missing_doctype():
    status, _ = gate.decide(_meta(document_type=None), CleanConfig())
    assert status == gate.REJECTED_NOT_REPRESENTATIVE


def test_official_statement_can_be_excluded_by_config():
    cfg = CleanConfig(keep_document_types=["speech", "interview"])
    status, _ = gate.decide(_meta(document_type="official_statement"), cfg)
    assert status == gate.REJECTED_NOT_REPRESENTATIVE


def test_rejects_no_speaker():
    status, _ = gate.decide(_meta(speaker=None), CleanConfig())
    assert status == gate.REJECTED_NO_SPEAKER
    status, _ = gate.decide(_meta(speaker="   "), CleanConfig())
    assert status == gate.REJECTED_NO_SPEAKER


def test_rejects_foreign_visitor():
    status, _ = gate.decide(_meta(speaker_type="foreign_visitor"), CleanConfig())
    assert status == gate.REJECTED_FOREIGN


def test_rejects_non_leader_minister():
    status, _ = gate.decide(_meta(speaker_type="other_minister"), CleanConfig())
    assert status == gate.REJECTED_NON_LEADER


def test_unknown_speaker_type_still_accepted():
    # we don't drop a representative document just because the role was uncertain
    status, _ = gate.decide(_meta(speaker_type="unknown"), CleanConfig())
    assert status == gate.ACCEPTED


def test_leader_type_gate_can_be_disabled():
    cfg = CleanConfig(require_leader_type=False)
    status, _ = gate.decide(_meta(speaker_type="foreign_visitor"), cfg)
    assert status == gate.ACCEPTED
