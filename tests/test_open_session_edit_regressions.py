from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.support.activity_factory import create_open_activity
from worktrace.api import timeline_api
from worktrace.db import get_connection
from worktrace.services import (
    project_service,
    report_session_operation_service,
)
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-15"


def _open_activity(*, project_id: int) -> int:
    return create_open_activity(
        start_time=f"{DATE} 09:00:00",
        app_name="Word",
        process_name="winword.exe",
        window_title="Document.docx - Word",
        project_id=project_id,
        status="normal",
    )


def test_persisted_open_session_allows_project_and_note_but_rejects_duration(temp_db):
    first_project = project_service.create_project("Open Edit A")
    second_project = project_service.create_project("Open Edit B")
    open_id = _open_activity(project_id=first_project)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]

    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "open-project-note-edit",
        second_project,
        None,
        "open memo",
    )

    assert result["ok"] is True
    updated = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert int(updated["project_id"]) == second_project
    assert updated["session_note"] == "open memo"
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id, source, is_manual "
            "FROM activity_project_assignment WHERE activity_id = ?",
            (open_id,),
        ).fetchone()
    assert assignment is not None
    assert int(assignment["project_id"]) == second_project
    assert assignment["source"] == "manual"
    assert int(assignment["is_manual"]) == 1

    with pytest.raises(Exception):
        timeline_api.save_timeline_session_edit(
            DATE,
            updated["projection_instance_key"],
            updated["projection_revision"],
            "open-duration-rejected",
            None,
            600,
            "open memo",
        )


def test_persisted_open_session_project_only_edit_is_effective(temp_db):
    first_project = project_service.create_project("Project Only A")
    second_project = project_service.create_project("Project Only B")
    _open_activity(project_id=first_project)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]

    result = timeline_api.save_timeline_session_edit(
        DATE,
        source["projection_instance_key"],
        source["projection_revision"],
        "open-project-only-edit",
        second_project,
        None,
        "",
    )

    assert result["ok"] is True
    updated = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert int(updated["project_id"]) == second_project


def test_open_session_no_op_rolls_back_manual_assignment(temp_db):
    first_project = project_service.create_project("Rollback A")
    second_project = project_service.create_project("Rollback B")
    open_id = _open_activity(project_id=first_project)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]

    with patch.object(
        report_session_operation_service,
        "_expected_effect",
        return_value=False,
    ):
        result = report_session_operation_service.edit_session(
            DATE,
            source["projection_instance_key"],
            source["projection_revision"],
            "open-project-forced-no-op",
            project_id=second_project,
            adjusted_duration_seconds=None,
            note="forced no-op",
        )

    assert result.outcome_type == "no_op"
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id, source, is_manual "
            "FROM activity_project_assignment WHERE activity_id = ?",
            (open_id,),
        ).fetchone()
    assert assignment is not None
    assert int(assignment["project_id"]) == first_project
    assert assignment["source"] == "manual"
    assert int(assignment["is_manual"]) == 1
