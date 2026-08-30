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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..constants import DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS, STATUS_PAUSED
from . import report_operation_repository
from . import report_session_operation_engine as engine
from . import session_boundary_service
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
from .report_session_builder import (
    build_report_sessions,
    merge_short_project_returns,
)
from .report_session_projection_service import (
    build_base_projection,
    display_safe_contribution,
)
from .report_status_policy import STANDALONE_STATUS, SUPPRESSED, decide_report_status
from .session_boundary_policy import ALLOWED_HARD_BOUNDARY_REASONS
from .settings_service import get_int_setting

_SHORT_RETURN_BLOCKING_REASONS = frozenset(
    ALLOWED_HARD_BOUNDARY_REASONS.difference({"sleep_resume", "midnight"})
)


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


@dataclass(frozen=True, slots=True)
class VerifiedOpenProjectionOverride:
    """Verified request-local duration for the single persisted open activity."""

    activity_id: int
    duration_seconds: int

    def __post_init__(self) -> None:
        if int(self.activity_id) <= 0:
            raise ValueError("effective_projection_requires_open_activity")
        if int(self.duration_seconds) < 0:
            raise ValueError("effective_projection_requires_nonnegative_duration")


def compute_projection_snapshot_revision(
    start_date: str,
    end_date: str,
    project_states: Iterable[ProjectState],
    final_entries: Iterable[Mapping[str, Any]],
    final_contributions: Iterable[Mapping[str, Any]],
    operation_diagnostics: Iterable[OperationDiagnostic],
) -> str:
    """Hash a finalized projection without repeating projection computation.

    This pure helper is the single owner of the snapshot content-hash contract.
    Mutation paths may reuse a verified operation replay result and call this
    helper instead of rebuilding facts and sessions only to obtain the same
    revision.
    """

    return stable_json_hash(
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
            "diagnostics": [item.to_dict() for item in operation_diagnostics],
        }
    )


def compute_projection(
    conn,
    start_date: str,
    end_date: str,
) -> ProjectionComputation:
    """Return durable projection semantics; runtime state is never consulted."""
    return _compute_projection(conn, start_date, end_date)


def compute_effective_read_projection(
    conn,
    start_date: str,
    end_date: str,
    verified_open_override: VerifiedOpenProjectionOverride,
) -> ProjectionComputation:
    """Return request-local as-of structure using one verified open duration."""
    return _compute_projection(
        conn,
        start_date,
        end_date,
        verified_open_override=verified_open_override,
    )


def _compute_projection(
    conn,
    start_date: str,
    end_date: str,
    *,
    verified_open_override: VerifiedOpenProjectionOverride | None = None,
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
        duration_overrides = (
            {
                int(verified_open_override.activity_id): int(
                    verified_open_override.duration_seconds
                )
            }
            if verified_open_override is not None
            else None
        )
        rows = load_report_activity_rows(
            start_date,
            end_date,
            conn=conn,
            duration_overrides=duration_overrides,
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
    short_return_boundaries = _short_return_blocking_boundaries(
        rows,
        deleted_rows,
        conn=conn,
    )

    with stage("operation_load"):
        operations_by_date = report_operation_repository.load_operations_by_date(
            conn,
            start_date,
            end_date,
        )
    protected_member_sets = _operation_binding_member_sets(operations_by_date)

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
        base_sessions = merge_short_project_returns(
            base_sessions,
            boundary_times=short_return_boundaries,
            protected_member_sets=protected_member_sets,
            interval_rows=reportable_rows,
            unrecorded_gap_boundary_seconds=gap_threshold,
            effective_open_activity_id=(
                int(verified_open_override.activity_id)
                if verified_open_override is not None
                else 0
            ),
        )
        base_projection = build_base_projection(
            base_sessions,
            reportable_rows,
            uncategorized_id,
        )
        base_sessions = list(base_projection.sessions)
    base_session_member_keys = _session_member_keys(base_sessions)

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
            if _row_member_key(row) in base_session_member_keys:
                continue
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
        revision = compute_projection_snapshot_revision(
            start_date,
            end_date,
            project_states,
            final_entries,
            final_contributions,
            diagnostics,
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


def _short_return_blocking_boundaries(
    rows: list[dict[str, Any]],
    deleted_rows: list[dict[str, Any]],
    *,
    conn,
) -> list[str]:
    values = [
        str(value)
        for row in rows
        for value in (row.get("start_time"), row.get("end_time"))
        if value
    ]
    result: list[str] = []
    if values:
        for boundary in session_boundary_service.list_boundaries(
            min(values),
            max(values),
            conn=conn,
        ):
            if str(boundary.get("reason") or "") in _SHORT_RETURN_BLOCKING_REASONS:
                occurred_at = str(boundary.get("occurred_at") or "")
                if occurred_at:
                    result.append(occurred_at)
    # A persisted paused interval is itself explicit user-pause evidence. Keep
    # it blocking even for repaired/fixture data where the boundary row is absent.
    for row in rows:
        if str(row.get("status") or "") != STATUS_PAUSED:
            continue
        for value in (row.get("start_time"), row.get("end_time")):
            if value:
                result.append(str(value))
    # Hidden/deleted project intervals must not be silently reassigned to a
    # neighbouring visible project by the short-return rule.
    for row in deleted_rows:
        for value in (row.get("start_time"), row.get("end_time")):
            if value:
                result.append(str(value))
    return sorted(set(result))


def _operation_binding_member_sets(
    operations_by_date,
) -> tuple[frozenset[tuple[str, int, str]], ...]:
    """Return source/target member sets that must retain replay identity."""
    result: list[frozenset[tuple[str, int, str]]] = []
    for operations in operations_by_date.values():
        for operation in operations:
            raw_members = (
                operation.get("members", {})
                if isinstance(operation, Mapping)
                else None
            )
            for role in ("source", "target"):
                if isinstance(raw_members, Mapping):
                    members = raw_members.get(role, ())
                else:
                    members = operation.members_for(role)
                if not members:
                    continue
                identities: set[tuple[str, int, str]] = set()
                for member in members:
                    if isinstance(member, Mapping):
                        activity_id = int(
                            member.get("activity_id") or member.get("id") or 0
                        )
                        report_date = str(member.get("report_date") or "")[:10]
                        slice_start = str(
                            member.get("slice_start_time")
                            or member.get("start_time")
                            or ""
                        )
                    else:
                        activity_id = int(member.activity_id or 0)
                        report_date = str(member.report_date or "")[:10]
                        slice_start = str(member.slice_start_time or "")
                    if activity_id > 0:
                        identities.add((report_date, activity_id, slice_start))
                if identities:
                    result.append(frozenset(identities))
    return tuple(result)


def _session_member_keys(
    sessions: Iterable[Mapping[str, Any]],
) -> frozenset[tuple[str, int, str]]:
    return frozenset(
        (
            str(member.get("report_date") or session.get("report_date") or "")[:10],
            int(member.get("activity_id") or member.get("id") or 0),
            str(member.get("slice_start_time") or member.get("start_time") or ""),
        )
        for session in sessions
        for member in session.get("member_slices") or []
        if int(member.get("activity_id") or member.get("id") or 0) > 0
    )


def _row_member_key(row: Mapping[str, Any]) -> tuple[str, int, str]:
    return (
        str(row.get("report_date") or "")[:10],
        int(row.get("id") or row.get("activity_id") or 0),
        str(row.get("start_time") or row.get("slice_start_time") or ""),
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
    "ProjectionComputation",
    "VerifiedOpenProjectionOverride",
    "compute_effective_read_projection",
    "compute_projection",
    "compute_projection_snapshot_revision",
]
