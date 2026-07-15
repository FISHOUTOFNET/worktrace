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
                sessions.append(
                    _finalize_session_semantics(
                        _build_session(current, uncategorized_id),
                        current,
                    )
                )
                current = []
            continue
        if not current:
            current = [row]
            continue
        if _can_merge(current[-1], row, boundary_times, threshold):
            current.append(row)
        else:
            sessions.append(
                _finalize_session_semantics(
                    _build_session(current, uncategorized_id),
                    current,
                )
            )
            current = [row]
    if current:
        sessions.append(
            _finalize_session_semantics(
                _build_session(current, uncategorized_id),
                current,
            )
        )
    return sessions


def _finalize_session_semantics(session: dict, rows: Sequence[Mapping]) -> dict:
    """Derive session-level project semantics from all contributions.

    `_build_session` historically copied these fields from the first row. That
    made a session beginning with attributed idle/excluded time appear derived
    even when it also contained an official direct contribution. Aggregation is
    deterministic and independent from contribution order.
    """
    keys = {str(row.get("report_project_key") or "") for row in rows}
    if len(keys) != 1:
        raise ValueError("report_session_project_key_mismatch")

    official_rows = [row for row in rows if bool(row.get("is_official_project"))]
    representative = min(
        official_rows or list(rows),
        key=lambda row: (
            str(row.get("start_time") or ""),
            int(row.get("id") or row.get("activity_id") or 0),
        ),
    )
    kinds = {
        str(row.get("report_attribution_kind") or "none")
        for row in rows
        if str(row.get("report_attribution_kind") or "none") != "none"
    }
    if "official_direct" in kinds:
        attribution_kind = "official_direct"
    elif len(kinds) == 1:
        attribution_kind = next(iter(kinds))
    elif kinds:
        attribution_kind = "report_context_mixed"
    else:
        attribution_kind = "none"

    session.update(
        {
            "project_id": int(
                representative.get("report_project_id")
                or session.get("project_id")
                or 0
            ),
            "project_name": str(
                representative.get("report_project_name")
                or session.get("project_name")
                or ""
            ),
            "project_description": str(
                representative.get("report_project_description")
                or session.get("project_description")
                or ""
            ),
            "project_is_deleted": any(
                bool(row.get("report_project_is_deleted")) for row in rows
            ),
            "project_is_archived": all(
                bool(row.get("report_project_is_archived")) for row in rows
            ),
            "is_official_project": bool(official_rows),
            "report_attribution_kind": attribution_kind,
            "is_report_project": all(
                bool(row.get("is_report_project")) for row in rows
            ),
            "is_report_classified": all(
                bool(row.get("is_report_classified")) for row in rows
            ),
            "is_report_uncategorized": all(
                bool(row.get("is_report_uncategorized")) for row in rows
            ),
        }
    )
    session["is_classified"] = bool(session["is_report_classified"])
    session["is_uncategorized"] = bool(session["is_report_uncategorized"])
    return session


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
    if not (
        _is_session_contribution(previous)
        and _is_session_contribution(current)
    ):
        return False
    if str(previous.get("report_date") or "") != str(
        current.get("report_date") or ""
    ):
        return False
    if _crosses_explicit_boundary(previous, current, boundary_times):
        return False
    if _has_unrecorded_gap(previous, current, gap_threshold_seconds):
        return False
    return str(previous.get("report_project_key") or "") == str(
        current.get("report_project_key") or ""
    )


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


def _has_unrecorded_gap(
    previous: Mapping,
    current: Mapping,
    threshold_seconds: int,
) -> bool:
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
