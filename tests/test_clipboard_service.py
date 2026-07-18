import pytest
from unittest.mock import patch

from tests.support import activity_factory as activity_service
from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow
from worktrace.services import (
    clipboard_fact_query_service,
    clipboard_service,
    project_service,
    rule_service,
    settings_service,
)

pytestmark = [pytest.mark.db, pytest.mark.security_privacy]


def _enable_capture() -> None:
    settings_service.set_setting("clipboard_capture_enabled", "true")


def test_clipboard_capture_defaults_to_disabled(temp_db):
    assert clipboard_service.is_capture_enabled() is False


def test_disabled_capture_rejects_late_inflight_event(temp_db):
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)

    event_id = clipboard_service.record_clipboard_event(
        activity,
        "must not persist",
        ActiveWindow("Edge", "msedge.exe", "Research"),
        copied_at="2026-06-18 09:00:05",
        sequence_number=100,
    )

    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_clipboard_event"
        ).fetchone()["c"]
    assert event_id is None
    assert count == 0


def test_clipboard_text_keyword_classifies_source_activity(temp_db):
    _enable_capture()
    project = project_service.create_project("Client")
    rule_service.create_rule("Acme", project)
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)

    event_id = clipboard_service.record_clipboard_event(
        activity,
        "Copied Acme contract clause",
        ActiveWindow("Edge", "msedge.exe", "Research"),
        copied_at="2026-06-18 09:00:05",
        sequence_number=101,
    )

    row = activity_service.get_activity(activity)
    with get_connection() as conn:
        event_count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_clipboard_event"
        ).fetchone()["c"]
        assignment = conn.execute(
            "SELECT source, confidence FROM activity_project_assignment "
            "WHERE activity_id = ?",
            (activity,),
        ).fetchone()
    assert event_id is not None
    assert event_count == 1
    assert row["project_id"] == project
    assert assignment["source"] == "keyword_rule"
    assert assignment["confidence"] == 80


def test_clipboard_event_deduplicates_sequence_number(temp_db):
    _enable_capture()
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)
    window = ActiveWindow("Edge", "msedge.exe", "Research")

    first = clipboard_service.record_clipboard_event(
        activity,
        "same text",
        window,
        copied_at="2026-06-18 09:00:05",
        sequence_number=42,
    )
    second = clipboard_service.record_clipboard_event(
        activity,
        "same text",
        window,
        copied_at="2026-06-18 09:00:06",
        sequence_number=42,
    )

    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_clipboard_event"
        ).fetchone()["c"]
    assert second == first
    assert count == 1


def test_clipboard_fact_and_inference_job_roll_back_together(temp_db):
    _enable_capture()
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)

    with patch(
        "worktrace.services.activity_inference_job_repository.enqueue_closed_activity_ids",
        side_effect=RuntimeError("job enqueue failed"),
    ), pytest.raises(RuntimeError, match="job enqueue failed"):
        clipboard_service.record_clipboard_event(
            activity,
            "transactional text",
            ActiveWindow("Edge", "msedge.exe", "Research"),
            copied_at="2026-06-18 09:00:05",
            sequence_number=202,
        )

    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_clipboard_event"
        ).fetchone()["c"]
        jobs = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_inference_job"
        ).fetchone()["c"]
    assert count == 0
    assert jobs == 0


def test_clipboard_inference_failure_retains_durable_job(temp_db):
    _enable_capture()
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)
    activity_service.close_activity(activity, "2026-06-18 09:00:04")

    with patch(
        "worktrace.services.activity_inference_job_service.process_pending_inference_jobs",
        side_effect=RuntimeError("inference unavailable"),
    ):
        event_id = clipboard_service.record_clipboard_event(
            activity,
            "retry me",
            ActiveWindow("Edge", "msedge.exe", "Research"),
            copied_at="2026-06-18 09:00:05",
            sequence_number=203,
        )

    with get_connection() as conn:
        job = conn.execute(
            "SELECT status, attempt_count FROM activity_inference_job WHERE activity_id = ?",
            (activity,),
        ).fetchone()
    assert event_id is not None
    assert dict(job) == {"status": "pending", "attempt_count": 0}


def test_clipboard_command_does_not_run_retention_maintenance(temp_db):
    _enable_capture()
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)

    with patch.object(
        clipboard_service,
        "prune_old_events",
        side_effect=RuntimeError("maintenance unavailable"),
    ) as prune:
        event_id = clipboard_service.record_clipboard_event(
            activity,
            "main command succeeds",
            ActiveWindow("Edge", "msedge.exe", "Research"),
            copied_at="2026-06-18 09:00:05",
            sequence_number=204,
        )

    assert event_id is not None
    prune.assert_not_called()


def test_clipboard_retention_keeps_only_last_month(temp_db):
    activity = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)
    with get_connection() as conn:
        for copied_at, copied_text in [
            ("2026-05-01 09:00:00", "old"),
            ("2026-06-01 09:00:00", "new"),
        ]:
            conn.execute(
                """
                INSERT INTO activity_clipboard_event(
                    activity_id, copied_at, app_name, process_name,
                    window_title, copied_text, text_hash, text_length,
                    created_at, updated_at
                )
                VALUES (?, ?, 'Edge', 'msedge.exe', 'Research', ?, ?, ?, ?, ?)
                """,
                (
                    activity,
                    copied_at,
                    copied_text,
                    copied_text,
                    len(copied_text),
                    copied_at,
                    copied_at,
                ),
            )

    deleted = clipboard_service.prune_old_events(
        now="2026-06-18 09:00:00"
    )

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT copied_text FROM activity_clipboard_event ORDER BY copied_at"
        ).fetchall()
    assert deleted == 1
    assert [row["copied_text"] for row in rows] == ["new"]


def test_file_text_mappings_include_activity_file_path(temp_db):
    _enable_capture()
    activity = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx - Word",
        file_path_hint="D:\\Client\\Spec.docx",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity)
    clipboard_service.record_clipboard_event(
        activity,
        "useful copied paragraph",
        ActiveWindow(
            "Word",
            "winword.exe",
            "Spec.docx - Word",
            "D:\\Client\\Spec.docx",
        ),
        copied_at="2026-06-18 09:00:05",
    )

    rows = clipboard_fact_query_service.list_file_text_mappings(
        "2026-06-18 00:00:00",
        "2026-06-18 23:59:59",
    )

    assert rows[0]["file_path"] == "D:\\Client\\Spec.docx"
    assert rows[0]["copied_text"] == "useful copied paragraph"
