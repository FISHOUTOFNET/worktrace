"""The single, read-only canonical report projection query."""

from __future__ import annotations

from typing import Any

from ..db import get_connection
from . import report_session_operation_engine as engine
from . import report_session_operation_service, timeline_service
from .report_projection_identity import stable_json_hash
from .report_projection_model import (
    OperationDiagnostic,
    ProjectState,
    ReportProjectionSnapshot,
    project_state_from_row,
)
from .report_status_policy import STANDALONE_STATUS, SUPPRESSED, decide_report_status


def build_visible_snapshot(start_date: str, end_date: str, *, conn=None) -> ReportProjectionSnapshot:
    """Build a deterministic snapshot without modifying any persistent state.

    An owned connection and a caller-owned transaction use the exact same
    implementation.  The owned path starts a deferred read transaction so all
    tables are observed from one SQLite snapshot.
    """
    if conn is not None:
        return _build_snapshot(conn, start_date, end_date)
    with get_connection() as read_conn:
        read_conn.execute("BEGIN")
        try:
            result = _build_snapshot(read_conn, start_date, end_date)
            read_conn.commit()
            return result
        except Exception:
            read_conn.rollback()
            raise


def _build_snapshot(conn, start_date: str, end_date: str) -> ReportProjectionSnapshot:
    from . import report_session_projection_service as projection

    uncategorized_id = timeline_service._uncategorized_project_id(conn)
    project_states = _load_project_states(conn, uncategorized_id)
    rows = timeline_service.get_report_activity_rows(start_date, end_date, conn=conn)

    # A deleted direct project removes the fact from every report surface; the
    # raw activity and direct assignment remain untouched for audit purposes.
    reportable_rows = [
        row
        for row in rows
        if not bool(row.get("effective_project_is_deleted") or row.get("report_project_is_deleted"))
    ]
    base_sessions = timeline_service._build_sessions_from_rows(
        reportable_rows,
        uncategorized_id,
        timeline_service._boundary_times_for_rows(reportable_rows, conn=conn),
    )
    for session in base_sessions:
        projection._attach_session_identity(session)
        projection._attach_raw_final_defaults(session, uncategorized_id)
        projection._finalize_session(session, uncategorized_id)
        projection._attach_projection_defaults(session)
    projection._attach_contributions(base_sessions, reportable_rows)

    dates = {
        str(session.get("report_date") or "")
        for session in base_sessions
        if start_date <= str(session.get("report_date") or "") <= end_date
    }
    dates.update(
        str(row["report_date"])
        for row in conn.execute(
            "SELECT DISTINCT report_date FROM report_session_operation WHERE report_date BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchall()
    )

    final_sessions: list[dict[str, Any]] = []
    final_contributions: list[dict[str, Any]] = []
    diagnostics: list[OperationDiagnostic] = []
    for report_date in sorted(dates):
        date_base = [item for item in base_sessions if str(item.get("report_date") or "") == report_date]
        replay = engine.replay_operations(
            date_base,
            report_session_operation_service.load_operations(report_date, conn=conn),
            project_states,
        )
        final_sessions.extend(
            item for item in replay.final_entries if not bool(item.get("project_is_deleted"))
        )
        final_contributions.extend(
            item for item in replay.final_contributions if not bool(item.get("project_is_deleted"))
        )
        diagnostics.extend(replay.operation_diagnostics)

    standalone_entries: list[dict[str, Any]] = []
    for row in reportable_rows:
        decision = decide_report_status(
            str(row.get("status") or ""),
            has_project_attribution=bool(row.get("is_report_project")),
        )
        if decision.decision in {SUPPRESSED, "session_contribution"}:
            continue
        if decision.decision != STANDALONE_STATUS:
            continue
        contribution = projection._display_safe_contribution(row)
        contribution.update(
            {
                "app_name": "已排除",
                "process_name": "",
                "activity_display_name": "已排除",
                "activity_identity_key": f"excluded:{contribution['activity_id']}",
                "resource_identity_key": "",
                "resource_display_name": "",
                "privacy_redacted": True,
            }
        )
        key = f"status:{contribution['report_date']}:{contribution['activity_id']}:{contribution['slice_start_time']}"
        contribution["projection_instance_key"] = key
        revision = stable_json_hash(
            {
                "key": key,
                "member": (
                    contribution["report_date"],
                    contribution["activity_id"],
                    contribution["slice_start_time"],
                ),
                "duration": contribution["duration_seconds"],
                "status": contribution["status"],
                "in_progress": contribution["is_in_progress"],
            }
        )
        contribution["projection_revision"] = revision
        final_contributions.append(contribution)
        standalone_entries.append(
            {
                "row_kind": "standalone_status",
                "report_date": contribution["report_date"],
                "projection_instance_key": key,
                "projection_revision": revision,
                "projection_kind": "status",
                "project_id": 0,
                "project_name": "已排除",
                "project_description": "",
                "start_time": contribution["start_time"],
                "end_time": contribution["end_time"],
                "duration_seconds": contribution["duration_seconds"],
                "closed_duration_seconds": 0 if contribution["is_in_progress"] else contribution["duration_seconds"],
                "status": contribution["status"],
                "status_code": contribution["status"],
                "status_summary": contribution["status"],
                "is_in_progress": contribution["is_in_progress"],
                "editable": False,
                "exportable": not contribution["is_in_progress"],
                "privacy_redacted": True,
                "activity_ids": [contribution["activity_id"]],
                "member_slices": [
                    {
                        "report_date": contribution["report_date"],
                        "activity_id": contribution["activity_id"],
                        "slice_start_time": contribution["slice_start_time"],
                    }
                ],
            }
        )

    final_sessions = sorted(final_sessions, key=timeline_service._session_sort_key)
    standalone_entries = sorted(
        standalone_entries,
        key=lambda item: (str(item.get("start_time") or ""), str(item.get("projection_instance_key") or "")),
    )
    final_entries = sorted(
        [*final_sessions, *standalone_entries],
        key=lambda item: (str(item.get("start_time") or ""), str(item.get("projection_instance_key") or "")),
    )
    revision = stable_json_hash(
        {
            "range": [start_date, end_date],
            "projects": [state.to_dict() for state in sorted(project_states, key=lambda item: item.project_id)],
            "entries": [
                {
                    "key": item.get("projection_instance_key"),
                    "revision": item.get("projection_revision"),
                    "duration": item.get("duration_seconds"),
                    "in_progress": item.get("is_in_progress"),
                }
                for item in final_entries
            ],
            "contributions": [
                {
                    "key": item.get("projection_instance_key"),
                    "member": [item.get("report_date"), item.get("activity_id"), item.get("slice_start_time")],
                    "duration": item.get("duration_seconds"),
                    "status": item.get("status"),
                    "project_id": item.get("project_id"),
                }
                for item in final_contributions
            ],
            "diagnostics": [item.to_dict() for item in diagnostics],
        }
    )
    # The domain object is immutable; dictionaries here are internal entry
    # records and are converted by explicit allowlist adapters at API edges.
    return ReportProjectionSnapshot(
        start_date=start_date,
        end_date=end_date,
        base_sessions=tuple(base_sessions),  # type: ignore[arg-type]
        final_entries=tuple(final_entries),  # type: ignore[arg-type]
        final_sessions=tuple(final_sessions),  # type: ignore[arg-type]
        standalone_status_entries=tuple(standalone_entries),  # type: ignore[arg-type]
        final_contributions=tuple(final_contributions),  # type: ignore[arg-type]
        operation_diagnostics=tuple(diagnostics),
        snapshot_revision=revision,
    )


def _load_project_states(conn, uncategorized_id: int) -> list[ProjectState]:
    return [
        project_state_from_row(dict(row), uncategorized_id=uncategorized_id)
        for row in conn.execute("SELECT * FROM project ORDER BY id").fetchall()
    ]


__all__ = ["ReportProjectionSnapshot", "build_visible_snapshot"]
