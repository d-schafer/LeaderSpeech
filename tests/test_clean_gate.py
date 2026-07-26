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


def test_tenure_exact_overrides_uncertain_speaker_type():
    # a tenure-CONFIRMED in-office leader is not dropped even if the model typed the speaker
    # 'other'/'foreign' (issue #68 — trust the crosscheck over an uncertain model type)
    m = _meta(document_type="official_statement", speaker_type="other")
    assert gate.decide(m, CleanConfig())[0] == gate.REJECTED_NON_LEADER
    assert gate.decide(m, CleanConfig(), tenure_match="exact")[0] == gate.ACCEPTED
    # a foreign-typed speaker that exactly matches THIS country's leader is also kept
    mf = _meta(speaker_type="foreign_visitor")
    assert gate.decide(mf, CleanConfig(), tenure_match="exact")[0] == gate.ACCEPTED


def test_tenure_exact_does_not_rescue_a_non_speech_doctype():
    # the exact match only overrides the leader-type check, NOT the document_type gate:
    # third-person NEWS about the leader is still rejected as not-representative
    m = _meta(document_type="other", speaker_type="other")
    assert gate.decide(m, CleanConfig(), tenure_match="exact")[0] == gate.REJECTED_NOT_REPRESENTATIVE


def test_unknown_speaker_type_still_accepted():
    # we don't drop a representative document just because the role was uncertain
    status, _ = gate.decide(_meta(speaker_type="unknown"), CleanConfig())
    assert status == gate.ACCEPTED


def test_leader_type_gate_can_be_disabled():
    cfg = CleanConfig(require_leader_type=False)
    status, _ = gate.decide(_meta(speaker_type="foreign_visitor"), cfg)
    assert status == gate.ACCEPTED


# --- needs_review: surface a plausible leader the tenure key doesn't know (issue #68) ----

def test_review_flags_accepted_leader_when_unmatched():
    # model typed a head of state, but the tenure crosscheck found nothing -> flag for key curation
    m = _meta(speaker_type="head_of_state")
    assert gate.needs_review(m, gate.ACCEPTED, "none") is True
    # a tenure-confirmed leader is NOT flagged (the key already knows them)
    assert gate.needs_review(m, gate.ACCEPTED, "exact") is False


def test_review_rescues_mistyped_first_person_substantive():
    # a genuine leader mis-typed 'other' (wrong leaders_info) but the doc is a first-person
    # substantive statement -> still surfaced despite the rejected_non_leader status
    m = _meta(document_type="official_statement", speaker_type="other",
              is_first_person="yes", is_substantive="yes")
    assert gate.needs_review(m, gate.REJECTED_NON_LEADER, "none") is True


def test_review_not_flagged_for_courtesy_minister():
    # a non-substantive minister is not a plausible national leader -> no flag
    m = _meta(speaker_type="other_minister", is_first_person="no", is_substantive="no")
    assert gate.needs_review(m, gate.REJECTED_NON_LEADER, "none") is False


def test_review_requires_none_not_other_country():
    # an other_country match (a real foreign visitor) must NOT trip the review flag
    m = _meta(speaker_type="head_of_state")
    assert gate.needs_review(m, gate.ACCEPTED, "other_country") is False


def test_review_ignores_non_representative_and_no_speaker():
    # a news item (rejected_not_representative) or a speakerless row is never a leader candidate,
    # even if it looks first-person substantive
    m = _meta(document_type="other", speaker_type="other", is_first_person="yes", is_substantive="yes")
    assert gate.needs_review(m, gate.REJECTED_NOT_REPRESENTATIVE, "none") is False
    assert gate.needs_review(m, gate.REJECTED_NO_SPEAKER, "none") is False
