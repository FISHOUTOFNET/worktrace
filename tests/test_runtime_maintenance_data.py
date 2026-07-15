from __future__ import annotations

import pytest

from tests.support.activity_factory import create_closed_activity
from tests.support.db_helpers import assign_activity_project, fetch_one

from worktrace.platforms.base import ActiveWindow
from worktrace.services import (
    activity_lifecycle_service,
    activity_service,
    folder_index_service,
    folder_rule_service,
    privacy_service,
    project_service,
    timeline_service,
)
from worktrace.services.folder_index_recovery_service import (
    recover_interrupted_indexes,
)
from worktrace.services.privacy_anonymization_service import anonymize_activity
from worktrace.services.privacy_service import PrivacyResolutionPending

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


def test_interrupted_folder_index_returns_to_pending(temp_db):
    project_id = project_service.create_project("Index Project")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"C:\IndexProject",
        project_id,
    )
    from worktrace.db import get_connection

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = 'indexing', refresh_requested = 0,
                error_message = 'crashed'
            WHERE folder_rule_id = ?
            """,
            (rule_id,),
        )

    assert recover_interrupted_indexes() == 1
    row = fetch_one(
        "SELECT * FROM folder_rule_index_state WHERE folder_rule_id = ?",
        (rule_id,),
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["refresh_requested"] == 1
    assert row["error_message"] is None


def test_unresolved_file_path_fails_closed_when_exclusion_folder_exists(
    temp_db,
    monkeypatch,
):
    excluded_id = project_service.set_excluded_project_enabled(True)
    folder_rule_service.create_or_update_folder_rule(
        r"C:\Confidential",
        excluded_id,
    )
    monkeypatch.setattr(
        folder_index_service,
        "resolve_unique_path_from_title",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(PrivacyResolutionPending):
        privacy_service.is_excluded(
            ActiveWindow(
                app_name="Word",
                process_name="winword.exe",
                window_title="Contract.docx",
                file_path_hint=None,
                privacy_path_required=True,
            )
        )


def test_deleted_five_minute_project_still_splits_surrounding_sessions(temp_db):
    project_a = project_service.create_project("Boundary A")
    deleted = project_service.create_project("Boundary Deleted")

    def activity(start: str, end: str, title: str, project_id: int) -> int:
        activity_id = create_closed_activity(
            day="2026-07-15",
            start=start,
            end=end,
            app_name="Word",
            process_name="word.exe",
            window_title=title,
        )
        assign_activity_project(activity_id, project_id, manual=True)
        return activity_id

    first = activity("09:00:00", "09:30:00", "First.docx", project_a)
    hidden = activity("09:30:00", "09:35:00", "Hidden.docx", deleted)
    second = activity("09:35:00", "10:00:00", "Second.docx", project_a)
    project_service.soft_delete_project(deleted)

    sessions = timeline_service.get_project_sessions_by_range(
        "2026-07-15",
        "2026-07-15",
    )

    assert sorted(item["activity_ids"] for item in sessions) == [
        [first],
        [second],
    ]
    assert hidden not in {
        activity_id
        for session in sessions
        for activity_id in session.get("activity_ids", [])
    }


def test_backward_close_time_is_clamped_at_lifecycle_boundary(temp_db):
    activity_id = activity_service.insert_activity_row(
        app_name="Clock",
        process_name="clock.exe",
        window_title="Clock rollback",
        start_time="2026-07-15 10:00:00",
    )

    activity_lifecycle_service.close_activity(
        activity_id,
        "2026-07-15 09:00:00",
    )

    row = fetch_one(
        "SELECT start_time, end_time, duration_seconds FROM activity_log WHERE id = ?",
        (activity_id,),
    )
    assert row is not None
    assert row["end_time"] == row["start_time"]
    assert int(row["duration_seconds"] or 0) == 0


def test_late_privacy_anonymization_removes_real_metadata(temp_db):
    activity_id = create_closed_activity(
        day="2026-07-15",
        start="11:00:00",
        end="11:05:00",
        app_name="Word",
        process_name="word.exe",
        window_title="Sensitive Contract.docx",
        file_path_hint=r"C:\Sensitive\Contract.docx",
    )

    anonymize_activity(activity_id)

    row = fetch_one(
        """
        SELECT app_name, process_name, window_title, file_path_hint, status
        FROM activity_log WHERE id = ?
        """,
        (activity_id,),
    )
    assert row is not None
    assert row["status"] == "excluded"
    assert row["file_path_hint"] is None
    assert "Sensitive" not in repr(row)
