"""Single public owner of the report projection business computation.

This module is the sole owner of projection business logic: fact query,
session build, operation replay, standalone status, sorting, and content
hash. It produces a :class:`ProjectionComputation` holding raw mutable
record lists — neither frozen nor deduplicated.

Both materializers consume the same :class:`ProjectionComputation`:

* :mod:`report_projection_snapshot_service` freezes every collection
  (including ``base_sessions`` and the mutually-exclusive subsets) into a
  full :class:`ReportProjectionSnapshot` for mutation, export, and debug.
* :mod:`report_projection_provider` freezes only ``final_entries`` and
  ``final_contributions`` into a compact :class:`DayProjection` for
  page-read paths.

Neither materializer duplicates business rules. Production services must
not share implementation through cross-module private symbols; both
materializers depend on this public builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constants import DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS
from . import report_operation_repository
from . import report_session_operation_engine as engine
from .projection_performance import record_counts, stage
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
    project_state_from_row,
)
from .report_session_builder import build_report_sessions
from .report_session_projection_service import (
    build_base_projection,
    display_safe_contribution,
)
from .report_status_policy import STANDALONE_STATUS, SUPPRESSED, decide_report_status
from .settings_service import get_int_setting


@dataclass
class ProjectionComputation:
    """Raw mutable result of the single projection computation path.

    Holds mutable lists (not yet frozen). Materializers freeze the
    appropriate subsets for their target representation (compact
    ``DayProjection`` vs. full ``ReportProjectionSnapshot``). This type
    is the public contract between the builder and its materializers.
    """

    start_date: str
    end_date: str
    base_sessions: list[dict[str, Any]]
    final_entries: list[dict[str, Any]]
    final_sessions: list[dict[str, Any]]
    standalone_status_entries: list[dict[str, Any]]
    final_contributions: list[dict[str, Any]]
    operation_diagnostics: list[OperationDiagnostic]
    snapshot_revision: str
    activity_count: int


def compute_projection(
    conn,
    start_date: str,
    end_date: str,
) -> ProjectionComputation:
    """Run the single projection computation path and return raw results.

    This is the sole owner of projection business logic (fact query, session
    build, operation replay, standalone status, sorting, content hash). Both
    the full :class:`ReportProjectionSnapshot` materializer and the compact
    :class:`DayProjection` materializer consume this result — neither
    duplicates business rules.
    """
    uncategorized_id = get_uncategorized_project_id(conn)
    project_states = _load_project_states(conn, uncategorized_id)
    with stage("fact_query"):
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
    with stage("session_build"):
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

    with stage("operation_load"):
        operations_by_date = report_operation_repository.load_operations_by_date(
            conn,
            start_date,
            end_date,
        )
    dates = {
        str(session.get("report_date") or "")
        for session in base_sessions
        if start_date <= str(session.get("report_date") or "") <= end_date
    }
    dates.update(operations_by_date)

    final_sessions: list[dict[str, Any]] = []
    final_contributions: list[dict[str, Any]] = []
    diagnostics: list[OperationDiagnostic] = []
    with stage("operation_replay"):
        for report_date in sorted(dates):
            date_base = [
                item
                for item in base_sessions
                if str(item.get("report_date") or "") == report_date
            ]
            replay = engine.replay_operations(
                date_base,
                operations_by_date.get(report_date, []),
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

    with stage("snapshot_finalize"):
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
    with stage("snapshot_hash"):
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
    record_counts(
        activity_count=len(rows),
        entry_count=len(final_entries),
        contribution_count=len(final_contributions),
    )
    return ProjectionComputation(
        start_date=start_date,
        end_date=end_date,
        base_sessions=base_sessions,
        final_entries=final_entries,
        final_sessions=final_sessions,
        standalone_status_entries=standalone_entries,
        final_contributions=final_contributions,
        operation_diagnostics=diagnostics,
        snapshot_revision=revision,
        activity_count=len(rows),
    )


def _load_project_states(conn, uncategorized_id: int) -> list[ProjectState]:
    return [
        project_state_from_row(
            dict(row),
            uncategorized_id=uncategorized_id,
        )
        for row in conn.execute("SELECT * FROM project ORDER BY id").fetchall()
    ]


__all__ = ["ProjectionComputation", "compute_projection"]
