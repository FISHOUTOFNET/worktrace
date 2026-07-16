from __future__ import annotations

import pytest

from worktrace.db import get_connection
from worktrace.services import (
    activity_lifecycle_service,
    activity_service,
    project_service,
    report_revision_service,
    report_session_edit_service,
    timeline_service,
)
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot
from worktrace.services.report_session_operation_engine import APPLIED

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-16"


def _session_for(activity_id: int) -> dict:
    return next(
        session
        for session in timeline_service.get_project_sessions_by_date(DATE)
        if int(activity_id)
        in {int(value) for value in session.get("activity_ids") or []}
    )


def test_open_edit_replays_after_activity_closes(temp_db):
    original_project = project_service.create_project("Open original")
    target_project = project_service.create_project("Open target")
    activity_id = activity_lifecycle_service.persist_open_activity(
        start_time=f"{DATE} 09:00:00",
        source="auto",
        payload={
            "app_name": "Word",
            "process_name": "winword.exe",
            "window_title": "Open-edit.docx - Word",
            "file_path_hint": "D:\\Work\\Open-edit.docx",
            "status": "normal",
            "project_id": original_project,
        },
    )
    # Canonical reporting intentionally suppresses zero-duration facts. Simulate
    # the first durable Recorder checkpoint before editing the open interval.
    activity_service.set_activity_duration(activity_id, 60)
    session = _session_for(activity_id)
    result = report_session_edit_service.edit_session(
        DATE,
        session["projection_instance_key"],
        session["projection_revision"],
        "open-edit-survives-close",
        project_id=target_project,
        adjusted_duration_seconds=None,
        note="open note",
    )
    assert result.outcome_type == "operation_committed"

    activity_lifecycle_service.close_activity(
        activity_id,
        f"{DATE} 09:10:00",
    )

    closed = _session_for(activity_id)
    assert int(closed["project_id"]) == target_project
    assert closed["session_note"] == "open note"
    snapshot = build_visible_snapshot(DATE, DATE)
    diagnostic = next(
        item
        for item in snapshot.operation_diagnostics
        if item.operation_id == result.operation_id
    )
    assert diagnostic.state == APPLIED
    with get_connection() as conn:
        assignment = conn.execute(
            """
            SELECT project_id, source, is_manual
            FROM activity_project_assignment
            WHERE activity_id = ?
            """,
            (activity_id,),
        ).fetchone()
    assert int(assignment["project_id"]) == target_project
    assert assignment["source"] == "manual"
    assert int(assignment["is_manual"]) == 1


def test_no_effect_edit_writes_receipt_without_structure_change(temp_db):
    project_id = project_service.create_project("No-op project")
    activity_id = activity_service.create_activity(
        "Excel",
        "excel.exe",
        "No-op.xlsx",
        project_id=project_id,
        start_time=f"{DATE} 10:00:00",
    )
    activity_service.close_activity(activity_id, f"{DATE} 10:10:00")
    session = _session_for(activity_id)

    report_revision_service.clear_report_structure_revision_cache()
    before_revision = report_revision_service.get_report_structure_revision(DATE)
    result = report_session_edit_service.edit_session(
        DATE,
        session["projection_instance_key"],
        session["projection_revision"],
        "empty-edit-receipt",
        project_id=None,
        adjusted_duration_seconds=int(session["duration_seconds"]),
        note="",
    )
    after_revision = report_revision_service.get_report_structure_revision(DATE)

    assert result.outcome_type == "no_op"
    assert result.operation_id is None
    assert after_revision == before_revision
    with get_connection() as conn:
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM report_session_operation"
            ).fetchone()[0]
            == 0
        )
        receipt = conn.execute(
            """
            SELECT outcome_type, operation_id
            FROM report_mutation_request
            WHERE request_id = ?
            """,
            ("empty-edit-receipt",),
        ).fetchone()
    assert receipt["outcome_type"] == "no_op"
    assert receipt["operation_id"] is None
