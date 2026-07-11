from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..db import get_connection
from . import report_session_operation_engine, report_session_operation_service, timeline_service
from .project_service import get_or_create_uncategorized_project
from .report_projection_identity import stable_json_hash


@dataclass(frozen=True)
class ReportProjectionSnapshot:
    start_date: str
    end_date: str
    visible_activity_rows: list[dict[str, Any]]
    status_rows: list[dict[str, Any]]
    base_sessions: list[dict[str, Any]]
    commands: list[dict[str, Any]]
    final_sessions: list[dict[str, Any]]
    final_contributions: list[dict[str, Any]]
    snapshot_revision: str


def build_visible_snapshot(
    start_date: str,
    end_date: str,
    *,
    ensure_context: bool = True,
    conn=None,
) -> ReportProjectionSnapshot:
    if ensure_context:
        timeline_service._ensure_context_for_report_range(start_date, end_date)
    if conn is None:
        with get_connection() as own_conn:
            own_conn.execute("BEGIN")
            return build_visible_snapshot(start_date, end_date, ensure_context=False, conn=own_conn)

    uncategorized_id = get_or_create_uncategorized_project(conn=conn)
    rows = timeline_service.get_report_activity_rows(
        start_date,
        end_date,
        include_hidden=False,
        ensure_context=False,
        conn=conn,
    )
    base_sessions = timeline_service._build_sessions_from_rows(
        rows,
        uncategorized_id,
        timeline_service._boundary_times_for_rows(rows, conn=conn),
    )
    from . import report_session_projection_service
    from .activity_continuity_service import is_normal_project_status

    for session in base_sessions:
        report_session_projection_service._attach_session_identity(session)
        report_session_projection_service._attach_raw_final_defaults(session, uncategorized_id)
        report_session_projection_service._finalize_session(session, uncategorized_id)
        report_session_projection_service._attach_projection_defaults(session)
    report_session_projection_service._attach_contributions(base_sessions, rows)

    final_sessions: list[dict[str, Any]] = []
    commands: list[dict[str, Any]] = []
    by_date: dict[str, list[dict[str, Any]]] = {}
    for session in base_sessions:
        by_date.setdefault(str(session.get("report_date") or ""), []).append(session)
    for report_date, sessions in by_date.items():
        operations = report_session_operation_service.load_operations(report_date, conn=conn)
        commands.extend(operations)
        ordered = sorted(sessions, key=timeline_service._session_sort_key, reverse=True)
        final_sessions.extend(report_session_operation_engine.apply_operations(ordered, operations))
    final_sessions = [
        session
        for session in final_sessions
        if report_session_projection_service.project_lifecycle_policy.final_session_is_reportable(session)
    ]

    final_contributions = report_session_operation_engine.build_projected_activity_contributions(final_sessions)
    status_rows = [dict(row) for row in rows if not is_normal_project_status(str(row.get("status") or ""))]
    for row in status_rows:
        item = report_session_projection_service._display_safe_contribution(row)
        item["projection_instance_key"] = f"status:{item['report_date']}:{item['activity_id']}:{item['slice_start_time']}"
        item["projection_kind"] = "status"
        final_contributions.append(item)

    revision = stable_json_hash(
        {
            "start_date": start_date,
            "end_date": end_date,
            "sessions": [
                {
                    "key": session.get("projection_instance_key"),
                    "revision": session.get("projection_revision"),
                    "duration": session.get("duration_seconds"),
                }
                for session in final_sessions
            ],
            "commands": [(command.get("id"), command.get("replay_order"), command.get("match_state")) for command in commands],
        }
    )
    return ReportProjectionSnapshot(
        start_date=start_date,
        end_date=end_date,
        visible_activity_rows=rows,
        status_rows=status_rows,
        base_sessions=base_sessions,
        commands=commands,
        final_sessions=sorted(final_sessions, key=timeline_service._session_sort_key, reverse=True),
        final_contributions=final_contributions,
        snapshot_revision=revision,
    )


__all__ = ["ReportProjectionSnapshot", "build_visible_snapshot"]
