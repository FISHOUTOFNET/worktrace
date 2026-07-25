"""Deterministic benchmark dataset builder for projection performance work.

This fixture is test-only and intentionally avoids production lifecycle
commands. It inserts closed activity facts with attached resources directly
through the activity fact repository, then optionally assigns a sparse set of
context anchors and enqueues a single session operation so the projection
exercises context attribution, operation replay and standalone status rows.

Privacy: facts use synthetic app/window names (``AppN``/``DocN``) and opaque
resource identity keys. No real titles or paths are recorded.
"""

from __future__ import annotations

from typing import Any

from worktrace.constants import SOURCE_AUTO, STATUS_NORMAL, STATUS_PAUSED
from worktrace.db import get_connection, now_str
from worktrace.resources.types import DetectedResource
from worktrace.services import (
    activity_fact_repository,
)
from worktrace.services import report_session_operation_service
from worktrace.services.report_fact_query_service import get_uncategorized_project_id

DEFAULT_REPORT_DATE = "2026-07-15"


def _format_time(day: str, seconds_into_day: int) -> str:
    hours, rem = divmod(seconds_into_day, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{day} {hours:02d}:{minutes:02d}:{secs:02d}"


def _build_resource(index: int) -> DetectedResource:
    return DetectedResource(
        resource_kind="local_file",
        resource_subtype="document",
        display_name=f"Doc{index}",
        identity_key=f"resource:doc:{index}",
        is_anchor=(index % 17 == 0),
        confidence=80,
        source="auto",
        app_name="App",
        process_name="app.exe",
        window_title=f"Doc{index}",
        path_hint=f"D:\\Bench\\Doc{index}.txt",
        path_key=f"path:doc:{index}",
        uri_scheme="",
        uri_host="",
        uri_hint="",
        metadata_json="",
    )


def _prepare_activity(
    *,
    app_name: str,
    process_name: str,
    window_title: str,
    start_time: str,
    status: str,
    source: str,
    project_id: int | None,
    resource: DetectedResource | None,
):
    return activity_fact_repository.prepare_activity(
        start_time=start_time,
        source=source,
        payload={
            "app_name": app_name,
            "process_name": process_name,
            "window_title": window_title,
            "status": status,
            "project_id": project_id,
            "file_path_hint": None,
            "resource": resource,
        },
    )


def build_benchmark_dataset(
    *,
    activity_count: int,
    report_date: str = DEFAULT_REPORT_DATE,
    seed_session_operation: bool = False,
    seed_in_progress: bool = False,
) -> dict[str, Any]:
    """Insert ``activity_count`` synthetic facts on ``report_date``.

    The distribution covers:
      * continuous uncategorized normal activities (the majority);
      * multi-project alternation via sparse manual anchors;
      * short sessions (10s) interleaved with longer ones;
      * sparse context anchors so context attribution must walk neighbours;
      * one paused standalone status row;
      * optionally one session operation (copy) on the first anchor session;
      * optionally one open in-progress activity at the end of the day.
    """

    if activity_count < 1:
        raise ValueError("activity_count must be >= 1")

    projects = _ensure_benchmark_projects()
    anchor_project = projects["anchor"]
    other_project = projects["other"]

    day_start_seconds = 9 * 3600  # 09:00:00
    span_seconds = 13 * 3600  # 09:00:00 -> 22:00:00
    step = max(5, span_seconds // max(activity_count, 1))

    activity_ids: list[int] = []
    anchor_activity_ids: list[int] = []

    with get_connection() as conn:
        uncategorized_id = get_uncategorized_project_id(conn)

    for index in range(activity_count):
        start_offset = day_start_seconds + index * step
        if start_offset >= day_start_seconds + span_seconds:
            start_offset = day_start_seconds + span_seconds - step
        # Short sessions every 5th entry; otherwise vary duration.
        if index % 5 == 0:
            duration = 10
        else:
            duration = max(5, step - (index % 7))
        end_offset = start_offset + duration
        start_time = _format_time(report_date, start_offset)
        end_time = _format_time(report_date, end_offset)

        status = STATUS_NORMAL
        project_id: int | None = None
        if index % 23 == 5 and index != 0:
            # Sparse anchor: a manually assigned normal activity that lends
            # its project to nearby uncategorized rows via context carry.
            status = STATUS_NORMAL
            project_id = anchor_project
        elif index % 31 == 0 and index != 0:
            project_id = other_project
        elif index == max(0, activity_count - 1) and not seed_in_progress:
            # Paused standalone status row. Only seeded when no in-progress
            # activity is requested, because the database enforces a single
            # open activity and the in-progress row must be the open one.
            status = STATUS_PAUSED
            project_id = None

        resource = _build_resource(index)
        prepared = _prepare_activity(
            app_name=f"App{index % 4}",
            process_name="app.exe",
            window_title=f"Doc{index}",
            start_time=start_time,
            status=status,
            source=SOURCE_AUTO,
            project_id=project_id,
            resource=resource,
        )
        with get_connection() as conn:
            activity_id = activity_fact_repository.insert_open_activity(
                conn, prepared
            )
            if status != STATUS_PAUSED:
                activity_fact_repository.close_activity(conn, activity_id, end_time)
        activity_ids.append(activity_id)
        if project_id == anchor_project:
            anchor_activity_ids.append(activity_id)

    # Anchor assignments are already durable via prepare_activity (manual
    # source). Non-anchor activities intentionally have no assignment row so
    # context attribution must walk neighbours to lend the anchor project.

    operation_id: int | None = None
    if seed_session_operation and anchor_activity_ids:
        first_anchor = anchor_activity_ids[0]
        snapshot = _build_snapshot_for_operation(report_date)
        source_session = _find_session_by_activity(snapshot, first_anchor)
        if source_session is not None:
            key = str(source_session.get("projection_instance_key") or "")
            revision = str(source_session.get("projection_revision") or "")
            if key and revision:
                result = report_session_operation_service.copy_session(
                    report_date=report_date,
                    projection_instance_key=key,
                    expected_projection_revision=revision,
                    request_id=f"bench-copy-{first_anchor}-{now_str()}",
                )
                operation_id = result.operation_id

    open_activity_id: int | None = None
    if seed_in_progress:
        # Append a single open activity at the very end of the day so the
        # projection must overlay live runtime state on a closed-history day.
        open_start = _format_time(report_date, day_start_seconds + span_seconds)
        resource = _build_resource(activity_count)
        prepared = _prepare_activity(
            app_name="AppOpen",
            process_name="app.exe",
            window_title="DocOpen",
            start_time=open_start,
            status=STATUS_NORMAL,
            source=SOURCE_AUTO,
            project_id=None,
            resource=resource,
        )
        with get_connection() as conn:
            open_activity_id = activity_fact_repository.insert_open_activity(
                conn, prepared
            )

    return {
        "report_date": report_date,
        "activity_count": activity_count,
        "activity_ids": activity_ids,
        "anchor_project_id": anchor_project,
        "other_project_id": other_project,
        "uncategorized_project_id": uncategorized_id,
        "operation_id": operation_id,
        "open_activity_id": open_activity_id,
    }


def _ensure_benchmark_projects() -> dict[str, int]:
    from tests.support import project_factory

    return {
        "anchor": project_factory.create_project("BenchAnchor"),
        "other": project_factory.create_project("BenchOther"),
    }


def _build_snapshot_for_operation(report_date: str):
    from worktrace.services.report_projection_snapshot_service import (
        build_visible_snapshot,
    )

    return build_visible_snapshot(report_date, report_date)


def _find_session_by_activity(snapshot, activity_id: int):
    for session in snapshot.final_sessions:
        ids = {int(value) for value in session.get("activity_ids") or []}
        if int(activity_id) in ids:
            return session
    return None


def build_concentrated_contributions_dataset(
    *,
    contribution_count: int,
    report_date: str = DEFAULT_REPORT_DATE,
) -> dict[str, Any]:
    """Insert ``contribution_count`` contiguous activities forming one session.

    All activities are back-to-back (5s each, no gaps) in the uncategorized
    project, so the session builder merges them into a single session with
    ``contribution_count`` member contributions.  This stresses the O(N)
    contribution index build and the single-session contribution lookup.

    Privacy: synthetic ``AppN``/``DocN`` names, opaque resource keys.
    """

    if contribution_count < 1:
        raise ValueError("contribution_count must be >= 1")

    projects = _ensure_benchmark_projects()
    day_start_seconds = 9 * 3600  # 09:00:00
    duration = 5

    activity_ids: list[int] = []
    with get_connection() as conn:
        uncategorized_id = get_uncategorized_project_id(conn)

    for index in range(contribution_count):
        start_offset = day_start_seconds + index * duration
        end_offset = start_offset + duration
        start_time = _format_time(report_date, start_offset)
        end_time = _format_time(report_date, end_offset)

        resource = _build_resource(index)
        prepared = _prepare_activity(
            app_name=f"App{index % 4}",
            process_name="app.exe",
            window_title=f"Doc{index}",
            start_time=start_time,
            status=STATUS_NORMAL,
            source=SOURCE_AUTO,
            project_id=None,
            resource=resource,
        )
        with get_connection() as conn:
            activity_id = activity_fact_repository.insert_open_activity(
                conn, prepared
            )
            activity_fact_repository.close_activity(conn, activity_id, end_time)
        activity_ids.append(activity_id)

    return {
        "report_date": report_date,
        "contribution_count": contribution_count,
        "activity_ids": activity_ids,
        "anchor_project_id": projects["anchor"],
        "other_project_id": projects["other"],
        "uncategorized_project_id": uncategorized_id,
    }


__all__ = [
    "DEFAULT_REPORT_DATE",
    "build_benchmark_dataset",
    "build_concentrated_contributions_dataset",
]
