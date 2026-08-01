from __future__ import annotations

import pytest

from tests.support.activity_factory import create_open_activity
from worktrace.api import timeline_api
from worktrace.db import get_connection
from worktrace.services import (
    project_service,
    report_session_operation_service,
    view_model_service,
)
from worktrace.services.report_projection_model import OperationNotAllowedError
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


def test_in_progress_timeline_view_model_disables_every_edit_capability(temp_db):
    project_id = project_service.create_project("Open read only")
    _open_activity(project_id=project_id)

    entry = view_model_service.get_timeline_view_model(DATE)["entries"][0]

    assert entry["is_in_progress"] is True
    assert entry["edit_disabled"] is True
    assert entry["can_edit_project"] is False
    assert entry["can_edit_note"] is False
    assert entry["can_edit_duration"] is False
    assert entry["can_hide"] is False
    assert entry["can_merge_previous"] is False
    assert entry["can_merge_next"] is False
    assert entry["can_split"] is False
    assert entry["can_copy"] is False
    assert entry["can_hide_activity"] is False
    assert entry["disable_reason"] == "进行中时段不可编辑"


@pytest.mark.parametrize(
    ("case_id", "project_change", "duration", "note"),
    [
        ("project", True, None, ""),
        ("description", False, None, "open memo"),
        ("duration", False, 600, ""),
    ],
)
def test_in_progress_edit_session_is_rejected_at_unified_mutation_boundary(
    temp_db,
    case_id,
    project_change,
    duration,
    note,
):
    first_project = project_service.create_project("Open Edit A")
    second_project = project_service.create_project("Open Edit B")
    open_id = _open_activity(project_id=first_project)
    source = build_visible_snapshot(DATE, DATE).final_sessions[0]

    with pytest.raises(OperationNotAllowedError):
        timeline_api.save_timeline_session_edit(
            DATE,
            source["projection_instance_key"],
            source["projection_revision"],
            f"open-{case_id}-rejected",
            second_project if project_change else None,
            duration is not None,
            duration,
            note,
        )

    unchanged = build_visible_snapshot(DATE, DATE).final_sessions[0]
    assert int(unchanged["project_id"]) == first_project
    assert unchanged["session_note"] == ""
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT project_id, source, is_manual "
            "FROM activity_project_assignment WHERE activity_id = ?",
            (open_id,),
        ).fetchone()
        operation_count = conn.execute(
            "SELECT COUNT(*) FROM report_session_operation"
        ).fetchone()[0]
    assert assignment is not None
    assert int(assignment["project_id"]) == first_project
    assert assignment["source"] == "manual"
    assert int(assignment["is_manual"]) == 1
    assert operation_count == 0


def test_open_edit_special_path_symbols_are_removed():
    assert not hasattr(report_session_operation_service, "_persist_open_edit_assignment")
    assert not hasattr(report_session_operation_service, "_find_open_activity_entry")
