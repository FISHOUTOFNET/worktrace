from __future__ import annotations

from dataclasses import dataclass

from ..constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED

SESSION_CONTRIBUTION = "session_contribution"
STANDALONE_STATUS = "standalone_status"
SUPPRESSED = "suppressed"


@dataclass(frozen=True)
class ReportStatusDecision:
    decision: str
    counts_toward_total: bool
    visible_in_timeline: bool
    visible_in_recent: bool
    exportable: bool
    privacy_redacted: bool
    project_attributable: bool
    hard_boundary: bool


def decide_report_status(status: str, *, has_project_attribution: bool = False) -> ReportStatusDecision:
    value = str(status or "").strip()
    if value == STATUS_NORMAL:
        return ReportStatusDecision(SESSION_CONTRIBUTION, True, True, True, True, False, True, False)
    if value in {STATUS_IDLE, STATUS_ERROR}:
        if has_project_attribution:
            return ReportStatusDecision(SESSION_CONTRIBUTION, True, True, True, True, False, True, False)
        return ReportStatusDecision(SUPPRESSED, False, False, False, False, False, False, False)
    if value == STATUS_EXCLUDED:
        if has_project_attribution:
            return ReportStatusDecision(SESSION_CONTRIBUTION, True, True, False, True, True, True, False)
        return ReportStatusDecision(STANDALONE_STATUS, True, True, False, True, True, False, False)
    if value == STATUS_PAUSED:
        return ReportStatusDecision(SUPPRESSED, False, False, False, False, False, False, True)
    return ReportStatusDecision(SUPPRESSED, False, False, False, False, False, False, False)


__all__ = [
    "ReportStatusDecision",
    "SESSION_CONTRIBUTION",
    "STANDALONE_STATUS",
    "SUPPRESSED",
    "decide_report_status",
]
