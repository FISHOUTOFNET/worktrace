from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..db import get_connection
from . import report_session_operation_engine, report_session_operation_service, timeline_service
from .report_projection_identity import stable_json_hash
from .report_status_policy import STANDALONE_STATUS, SUPPRESSED, decide_report_status


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
    standalone_status_rows: list[dict[str, Any]]
    suppressed_rows: list[dict[str, Any]]
    operation_lifecycle_records: list[dict[str, Any]]
    snapshot_revision: str


def build_visible_snapshot(
    start_date: str,
    end_date: str,
    *,
    ensure_context: bool = False,
    conn=None,
) -> ReportProjectionSnapshot:
    if conn is None:
        with get_connection() as own_conn:
            own_conn.execute("BEGIN")
            return build_visible_snapshot(start_date, end_date, ensure_context=False, conn=own_conn)
    if ensure_context:
        timeline_service._ensure_context_for_report_range_in_transaction(conn, start_date, end_date)

    uncategorized_id = timeline_service._uncategorized_project_id(conn)
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
        lifecycle = report_session_operation_service.load_operation_lifecycle(report_date, conn=conn)
        operations = [item for item in lifecycle if str(item.get("match_state") or "") == "active"]
        commands.extend(lifecycle)
        ordered = sorted(sessions, key=timeline_service._session_sort_key, reverse=True)
        final_sessions.extend(report_session_operation_engine.apply_operations(ordered, operations))
    final_sessions = [
        session
        for session in final_sessions
        if report_session_projection_service.project_lifecycle_policy.final_session_is_reportable(session)
    ]

    final_contributions = report_session_operation_engine.build_projected_activity_contributions(final_sessions)
    status_rows = [
        dict(row)
        for row in rows
        if decide_report_status(
            str(row.get("status") or ""),
            has_project_attribution=bool(row.get("is_report_project")),
        ).decision
        != "session_contribution"
    ]
    standalone_status_rows: list[dict[str, Any]] = []
    suppressed_rows: list[dict[str, Any]] = []
    for row in status_rows:
        decision = decide_report_status(str(row.get("status") or ""), has_project_attribution=bool(row.get("is_report_project")))
        if decision.decision == SUPPRESSED:
            suppressed = dict(row)
            suppressed["status_decision"] = decision.decision
            suppressed_rows.append(suppressed)
            continue
        if decision.decision != STANDALONE_STATUS:
            continue
        item = report_session_projection_service._display_safe_contribution(row)
        item["projection_instance_key"] = f"status:{item['report_date']}:{item['activity_id']}:{item['slice_start_time']}"
        item["projection_kind"] = "status"
        final_contributions.append(item)
        standalone_status_rows.append(item)

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
            "contributions": [
                {
                    "key": row.get("projection_instance_key"),
                    "activity_id": row.get("activity_id"),
                    "report_date": row.get("report_date"),
                    "slice_start_time": row.get("slice_start_time"),
                    "duration": row.get("duration_seconds"),
                    "status": row.get("status"),
                    "project_id": row.get("project_id"),
                }
                for row in final_contributions
            ],
            "status_rows": [
                {
                    "activity_id": row.get("activity_id") or row.get("id"),
                    "status": row.get("status"),
                    "duration": row.get("duration_seconds"),
                    "start_time": row.get("start_time"),
                }
                for row in status_rows
            ],
            "commands": [(command.get("id"), command.get("replay_order"), command.get("match_state")) for command in commands],
            "standalone_status_rows": [
                (row.get("projection_instance_key"), row.get("duration_seconds"), row.get("status"))
                for row in standalone_status_rows
            ],
            "suppressed_rows": [
                (row.get("id") or row.get("activity_id"), row.get("report_date"), row.get("status"))
                for row in suppressed_rows
            ],
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
        standalone_status_rows=standalone_status_rows,
        suppressed_rows=suppressed_rows,
        operation_lifecycle_records=commands,
        snapshot_revision=revision,
    )


__all__ = ["ReportProjectionSnapshot", "build_visible_snapshot"]
