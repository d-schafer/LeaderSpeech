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


def _norm(v) -> str:
    return (v or "").strip().lower() if isinstance(v, str) else ""


def decide(meta: dict, config) -> tuple[str, str]:
    """Return (clean_status, gate_reason). `meta` is a parsed extraction dict."""
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

    # 3) must be a national leader (configurable). Foreign visitors and clearly
    #    non-leader speakers are set aside; 'unknown'/'head_*'/'both' pass (we don't
    #    drop a real leader just because the type was uncertain).
    if config.require_leader_type:
        if stype == "foreign_visitor":
            return REJECTED_FOREIGN, "speaker is a foreign visitor, not this country's leader"
        if stype in _NON_LEADER_TYPES:
            return REJECTED_NON_LEADER, f"speaker_type={stype} (not a head of state/government)"

    return ACCEPTED, ""
