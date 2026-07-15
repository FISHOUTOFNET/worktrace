"""The single, read-only canonical report projection query."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from ..constants import DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS
from ..db import get_connection
from . import report_session_operation_engine as engine
from . import report_session_operation_service
from .report_fact_query_service import (
    boundary_times_for_rows,
    get_uncategorized_project_id,
    load_report_activity_rows,
    session_sort_key,
)
from .report_projection_identity import stable_json_hash
from .report_projection_model import (
    OperationDiagnostic,
    ProjectState,
    ReportProjectionSnapshot,
    project_state_from_row,
)
from .report_session_builder import build_report_sessions
from .report_session_projection_service import (
    build_base_projection,
    display_safe_contribution,
)
from .report_status_policy import STANDALONE_STATUS, SUPPRESSED, decide_report_status
from .settings_service import get_int_setting

_REQUEST_SNAPSHOT_CACHE: ContextVar[
    dict[tuple[str, str], ReportProjectionSnapshot] | None
] = ContextVar("worktrace_report_snapshot_cache", default=None)


@contextmanager
def snapshot_read_scope() -> Iterator[None]:
    """Reuse canonical snapshots only inside one explicit API request."""
    existing = _REQUEST_SNAPSHOT_CACHE.get()
    if existing is not None:
        yield
        return
    token = _REQUEST_SNAPSHOT_CACHE.set({})
    try:
        yield
    finally:
        _REQUEST_SNAPSHOT_CACHE.reset(token)


def build_visible_snapshot(
    start_date: str,
    end_date: str,
    *,
    conn=None,
) -> ReportProjectionSnapshot:
    """Build a deterministic snapshot without modifying persistent state."""
    if conn is not None:
        return _build_snapshot(conn, start_date, end_date)
    cache = _REQUEST_SNAPSHOT_CACHE.get()
    key = (str(start_date), str(end_date))
    if cache is not None and key in cache:
        return cache[key]
    with get_connection() as read_conn:
        read_conn.execute("BEGIN")
        try:
            result = _build_snapshot(read_conn, start_date, end_date)
            read_conn.commit()
        except Exception:
            read_conn.rollback()
            raise
    if cache is not None:
        cache[key] = result
    return result


def _build_snapshot(conn, start_date: str, end_date: str) -> ReportProjectionSnapshot:
    uncategorized_id = get_uncategorized_project_id(conn)
    project_states = _load_project_states(conn, uncategorized_id)
    rows = load_report_activity_rows(
        start_date,
        end_date,
        conn=conn,
    )

    # Visibility is applied after continuity is established. A soft-deleted
    # project remains a real interval in the fact layer and must split the
    # visible sessions on either side even though its own row is suppressed.
    deleted_rows = [
        row
        for row in rows
        if bool(
            row.get("effective_project_is_deleted")
            or row.get("report_project_is_deleted")
        )
    ]
    reportable_rows = [row for row in rows if row not in deleted_rows]
    boundary_values = list(boundary_times_for_rows(rows, conn=conn))
    for row in deleted_rows:
        for value in (row.get("start_time"), row.get("end_time")):
            if value:
                boundary_values.append(str(value))
    boundaries = sorted(set(boundary_values))

    gap_threshold = max(
        60,
        get_int_setting(
            "unrecorded_gap_boundary_seconds",
            DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
            conn=conn,
        ),
    )
    base_sessions = build_report_sessions(
        reportable_rows,
        uncategorized_id,
        boundary_times=boundaries,
        unrecorded_gap_boundary_seconds=gap_threshold,
    )
    base_projection = build_base_projection(
        base_sessions,
        reportable_rows,
        uncategorized_id,
    )
    base_sessions = list(base_projection.sessions)

    dates = {
        str(session.get("report_date") or "")
        for session in base_sessions
        if start_date <= str(session.get("report_date") or "") <= end_date
    }
    dates.update(
        str(row["report_date"])
        for row in conn.execute(
            "SELECT DISTINCT report_date FROM report_session_operation "
            "WHERE report_date BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchall()
    )

    final_sessions: list[dict[str, Any]] = []
    final_contributions: list[dict[str, Any]] = []
    diagnostics: list[OperationDiagnostic] = []
    for report_date in sorted(dates):
        date_base = [
            item
            for item in base_sessions
            if str(item.get("report_date") or "") == report_date
        ]
        replay = engine.replay_operations(
            date_base,
            report_session_operation_service.load_operations(
                report_date,
                conn=conn,
            ),
            project_states,
        )
        final_sessions.extend(
            dict(item)
            for item in replay.final_entries
            if not bool(item.get("project_is_deleted"))
        )
        final_contributions.extend(
            dict(item)
            for item in replay.final_contributions
            if not bool(item.get("project_is_deleted"))
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
        contribution = display_safe_contribution(row)
        contribution.update(
            {
                "app_name": "已排除",
                "process_name": "",
                "activity_display_name": "已排除",
                "activity_identity_key": (
                    f"excluded:{contribution['activity_id']}"
                ),
                "resource_identity_key": "",
                "resource_display_name": "",
                "privacy_redacted": True,
            }
        )
        key = (
            f"status:{contribution['report_date']}:"
            f"{contribution['activity_id']}:"
            f"{contribution['slice_start_time']}"
        )
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
                "closed_duration_seconds": (
                    0
                    if contribution["is_in_progress"]
                    else contribution["duration_seconds"]
                ),
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

    final_sessions = sorted(final_sessions, key=session_sort_key)
    standalone_entries = sorted(
        standalone_entries,
        key=lambda item: (
            str(item.get("start_time") or ""),
            str(item.get("projection_instance_key") or ""),
        ),
    )
    final_entries = sorted(
        [*final_sessions, *standalone_entries],
        key=lambda item: (
            str(item.get("start_time") or ""),
            str(item.get("projection_instance_key") or ""),
        ),
    )
    revision = stable_json_hash(
        {
            "range": [start_date, end_date],
            "projects": [
                state.to_dict()
                for state in sorted(
                    project_states,
                    key=lambda item: item.project_id,
                )
            ],
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
                    "member": [
                        item.get("report_date"),
                        item.get("activity_id"),
                        item.get("slice_start_time"),
                    ],
                    "duration": item.get("duration_seconds"),
                    "status": item.get("status"),
                    "project_id": item.get("project_id"),
                }
                for item in final_contributions
            ],
            "diagnostics": [item.to_dict() for item in diagnostics],
        }
    )
    return ReportProjectionSnapshot(
        start_date=start_date,
        end_date=end_date,
        base_sessions=tuple(base_sessions),
        final_entries=tuple(final_entries),
        final_sessions=tuple(final_sessions),
        standalone_status_entries=tuple(standalone_entries),
        final_contributions=tuple(final_contributions),
        operation_diagnostics=tuple(diagnostics),
        snapshot_revision=revision,
    )


def _load_project_states(conn, uncategorized_id: int) -> list[ProjectState]:
    return [
        project_state_from_row(
            dict(row),
            uncategorized_id=uncategorized_id,
        )
        for row in conn.execute("SELECT * FROM project ORDER BY id").fetchall()
    ]


__all__ = [
    "ReportProjectionSnapshot",
    "build_visible_snapshot",
    "snapshot_read_scope",
]
