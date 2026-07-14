"""Pure canonical session aggregation from already projected report rows."""

from __future__ import annotations

from datetime import datetime
from typing import Mapping, Sequence

from ..constants import DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS, TIME_FORMAT
from .report_status_policy import SESSION_CONTRIBUTION, decide_report_status


def build_report_sessions(
    rows: Sequence[dict],
    uncategorized_id: int,
    *,
    boundary_times: Sequence[str] = (),
    unrecorded_gap_boundary_seconds: int = DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
) -> list[dict]:
    """Group report contributions without reading settings or opening a DB.

    The caller owns the SQLite snapshot and supplies both explicit boundaries
    and the already-read unrecorded-gap threshold. This keeps the canonical
    projection a true single-transaction query.
    """
    from .timeline_service import _build_session

    threshold = max(60, int(unrecorded_gap_boundary_seconds))
    sessions: list[dict] = []
    current: list[dict] = []
    for row in rows:
        if not _is_session_contribution(row):
            if current:
                sessions.append(_build_session(current, uncategorized_id))
                current = []
            continue
        if not current:
            current = [row]
            continue
        if _can_merge(current[-1], row, boundary_times, threshold):
            current.append(row)
        else:
            sessions.append(_build_session(current, uncategorized_id))
            current = [row]
    if current:
        sessions.append(_build_session(current, uncategorized_id))
    return sessions


def _is_session_contribution(row: Mapping) -> bool:
    decision = decide_report_status(
        str(row.get("status") or ""),
        has_project_attribution=bool(row.get("is_report_project")),
    )
    return decision.decision == SESSION_CONTRIBUTION


def _can_merge(
    previous: Mapping,
    current: Mapping,
    boundary_times: Sequence[str],
    gap_threshold_seconds: int,
) -> bool:
    if not (_is_session_contribution(previous) and _is_session_contribution(current)):
        return False
    if str(previous.get("report_date") or "") != str(current.get("report_date") or ""):
        return False
    if _crosses_explicit_boundary(previous, current, boundary_times):
        return False
    if _has_unrecorded_gap(previous, current, gap_threshold_seconds):
        return False
    return str(previous.get("report_project_key") or "") == str(current.get("report_project_key") or "")


def _crosses_explicit_boundary(
    previous: Mapping,
    current: Mapping,
    boundary_times: Sequence[str],
) -> bool:
    start = str(previous.get("end_time") or previous.get("start_time") or "")
    end = str(current.get("start_time") or "")
    if not start or not end or start > end:
        return False
    return any(start <= str(boundary) <= end for boundary in boundary_times)


def _has_unrecorded_gap(previous: Mapping, current: Mapping, threshold_seconds: int) -> bool:
    previous_end = _parse(previous.get("end_time"))
    current_start = _parse(current.get("start_time"))
    if previous_end is None or current_start is None:
        return False
    gap_seconds = int((current_start - previous_end).total_seconds())
    return gap_seconds > max(60, int(threshold_seconds))


def _parse(value) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), TIME_FORMAT)
    except (TypeError, ValueError):
        return None


__all__ = ["build_report_sessions"]
