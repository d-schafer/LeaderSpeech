"""The hard gate: decide whether a cleaned row is kept (`accepted`) or set aside with
a `rejected_*` status + reason.

The project rule: every kept row must have a speaker and must REPRESENT THE LEADER —
i.e. the document conveys the leader's own words or position. That includes delivered
speeches, interviews, and official statements/communiqués issued in the leader's name
(even third-person ones that report the leader's stance) — but NOT pure news reports,
biographies, agendas, or logistical notices. Which `document_type`s count as
"representative" is configurable (`keep_document_types`). Rejected rows are NOT deleted —
they stay in the same per-source Parquet (audited), distinguished by `clean_status`.

Pure function, unit-tested. `decide(meta, config) -> (clean_status, gate_reason)`.
"""

from __future__ import annotations

ACCEPTED = "accepted"
REJECTED_NOT_REPRESENTATIVE = "rejected_not_representative"  # doesn't convey the leader's words/position
REJECTED_NO_SPEAKER = "rejected_no_speaker"
REJECTED_FOREIGN = "rejected_foreign"
REJECTED_NON_LEADER = "rejected_non_leader"

# speaker_type values that fail the "must be a national leader" gate
_NON_LEADER_TYPES = {"other_minister", "other"}

# speaker_type values the model uses for a head of state / government
_LEADER_TYPES = {"head_of_state", "head_of_government", "both"}


def _norm(v) -> str:
    return (v or "").strip().lower() if isinstance(v, str) else ""


def decide(meta: dict, config, tenure_match: str = "") -> tuple[str, str]:
    """Return (clean_status, gate_reason). `meta` is a parsed extraction dict; `tenure_match`
    is the crosscheck verdict ('exact'/'other_country'/'none')."""
    dtype = _norm(meta.get("document_type"))
    speaker = (meta.get("speaker") or "").strip()
    stype = _norm(meta.get("speaker_type"))

    # 1) must represent the leader (a kept document_type)
    keep = {t.lower() for t in config.keep_document_types}
    if dtype not in keep:
        label = dtype or "unknown"
        return REJECTED_NOT_REPRESENTATIVE, f"document_type={label} does not represent the leader"

    # 2) must have a speaker
    if not speaker:
        return REJECTED_NO_SPEAKER, "no speaker could be identified"

    # 3) must be a national leader (configurable). Foreign visitors and clearly non-leader
    #    speakers are set aside; 'unknown'/'head_*'/'both' pass (we don't drop a real leader
    #    just because the type was uncertain). BUT if the tenure crosscheck EXACTLY matched a
    #    leader in office for this country+year, trust that over an uncertain model speaker_type:
    #    a confirmed in-office leader must not be dropped as non-leader/foreign (issue #68).
    if config.require_leader_type and _norm(tenure_match) != "exact":
        if stype == "foreign_visitor":
            return REJECTED_FOREIGN, "speaker is a foreign visitor, not this country's leader"
        if stype in _NON_LEADER_TYPES:
            return REJECTED_NON_LEADER, f"speaker_type={stype} (not a head of state/government)"

    return ACCEPTED, ""


def needs_review(meta: dict, clean_status: str, tenure_match: str) -> bool:
    """Orthogonal to the accept/reject partition: True when a row plausibly represents a
    national leader the tenure key does NOT yet know about — the signal that the key needs
    extending (issue #68). `decide()` stays untouched; this is a separate `speaker_review`
    flag so a genuinely-accepted row is never un-accepted and a silently-dropped real leader
    is surfaced for curation.

    Fires only when:
      * the row already cleared the document_type + speaker gates (status is accepted, or a
        leader-type rejection — never a non-representative / no-speaker row), AND
      * the tenure crosscheck found NOTHING (`none`, not `exact`/`other_country`), AND
      * either the model typed the speaker a head of state/government, OR the document is a
        first-person substantive statement (so a genuine leader mis-typed `other` because the
        prompt named the wrong leader is still caught).
    All inputs are stored columns, so the flag is `--regate`-derivable with no API calls."""
    if clean_status not in (ACCEPTED, REJECTED_NON_LEADER, REJECTED_FOREIGN):
        return False
    if _norm(tenure_match) != "none":
        return False
    if _norm(meta.get("speaker_type")) in _LEADER_TYPES:
        return True
    return _norm(meta.get("is_first_person")) == "yes" and _norm(meta.get("is_substantive")) == "yes"
