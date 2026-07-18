from unittest.mock import patch

import pytest

from tests.support import activity_factory as activity_service
from worktrace.db import get_connection
from worktrace.platforms.base import ActiveWindow
from worktrace.services import (
    activity_inference_job_service,
    clipboard_fact_query_service,
    clipboard_service,
    project_inference_service,
    project_service,
    rule_service,
    settings_service,
)

pytestmark = [pytest.mark.db, pytest.mark.security_privacy]


def _enable_capture() -> None:
    settings_service.set_setting("clipboard_capture_enabled", "true")


def _window(path: str | None = None) -> ActiveWindow:
    return ActiveWindow(
        "Word" if path else "Edge",
        "winword.exe" if path else "msedge.exe",
        "Spec.docx - Word" if path else "Research",
        path,
    )


def _job(activity_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_inference_job WHERE activity_id = ?",
            (int(activity_id),),
        ).fetchone()
    return dict(row) if row else None


def test_clipboard_capture_defaults_to_disabled(temp_db):
    assert clipboard_service.is_capture_enabled() is False


def test_disabled_capture_rejects_late_inflight_event(temp_db):
    activity_id = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    assert clipboard_service.record_clipboard_event(
        activity_id,
        "must not persist",
        _window(),
        copied_at="2026-06-18 09:00:05",
        sequence_number=100,
    ) is None
    with get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM activity_clipboard_event"
        ).fetchone()[0] == 0


def test_clipboard_fact_on_open_row_uses_open_sync_without_job(temp_db):
    _enable_capture()
    project_id = project_service.create_project("Client")
    rule_service.create_rule("Acme", project_id)
    activity_id = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )

    event_id = clipboard_service.record_clipboard_event(
        activity_id,
        "Copied Acme contract clause",
        _window(),
        copied_at="2026-06-18 09:00:05",
        sequence_number=101,
    )

    assignment = project_inference_service.get_assignment_for_activity(activity_id)
    assert event_id is not None
    assert int(assignment["project_id"]) == project_id
    assert assignment["source"] == "keyword_rule"
    assert assignment["confidence"] == 80
    assert _job(activity_id) is None


def test_clipboard_fact_on_closed_row_enqueues_without_immediate_assignment(temp_db):
    _enable_capture()
    project_id = project_service.create_project("ClosedClient")
    rule_service.create_rule("ClosedAcme", project_id)
    activity_id = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.close_activity(activity_id, "2026-06-18 09:00:04")

    event_id = clipboard_service.record_clipboard_event(
        activity_id,
        "ClosedAcme contract clause",
        _window(),
        copied_at="2026-06-18 09:00:05",
        sequence_number=102,
    )

    assert event_id is not None
    assert _job(activity_id)["status"] == "pending"
    assert project_inference_service.get_assignment_for_activity(activity_id) == {}
    assert activity_inference_job_service.process_pending_inference_jobs(
        project_inference_service.assign_project_for_activity_in_transaction,
        limit=1,
        activity_ids=[activity_id],
    ) == 1
    assert int(
        project_inference_service.get_assignment_for_activity(activity_id)["project_id"]
    ) == project_id


def test_clipboard_event_deduplicates_sequence_number(temp_db):
    _enable_capture()
    activity_id = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    first = clipboard_service.record_clipboard_event(
        activity_id,
        "same text",
        _window(),
        copied_at="2026-06-18 09:00:05",
        sequence_number=42,
    )
    second = clipboard_service.record_clipboard_event(
        activity_id,
        "same text",
        _window(),
        copied_at="2026-06-18 09:00:06",
        sequence_number=42,
    )
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM activity_clipboard_event"
        ).fetchone()[0]
    assert second == first
    assert count == 1


def test_closed_clipboard_fact_and_job_roll_back_together(temp_db):
    _enable_capture()
    activity_id = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.close_activity(activity_id, "2026-06-18 09:00:04")

    with patch(
        "worktrace.services.activity_inference_job_repository.enqueue_closed_activity_ids",
        side_effect=RuntimeError("job enqueue failed"),
    ), pytest.raises(RuntimeError, match="job enqueue failed"):
        clipboard_service.record_clipboard_event(
            activity_id,
            "transactional text",
            _window(),
            copied_at="2026-06-18 09:00:05",
            sequence_number=202,
        )

    with get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM activity_clipboard_event"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM activity_inference_job"
        ).fetchone()[0] == 0


def test_clipboard_command_does_not_call_consumer_or_retention(temp_db):
    _enable_capture()
    activity_id = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.close_activity(activity_id, "2026-06-18 09:00:04")

    with patch.object(
        activity_inference_job_service,
        "process_pending_inference_jobs",
        side_effect=RuntimeError("consumer must remain asynchronous"),
    ) as consumer, patch.object(
        clipboard_service,
        "prune_old_events",
        side_effect=RuntimeError("maintenance must remain separate"),
    ) as prune:
        event_id = clipboard_service.record_clipboard_event(
            activity_id,
            "main command succeeds",
            _window(),
            copied_at="2026-06-18 09:00:05",
            sequence_number=204,
        )

    assert event_id is not None
    assert _job(activity_id) is not None
    consumer.assert_not_called()
    prune.assert_not_called()


def test_clipboard_retention_keeps_only_last_month(temp_db):
    activity_id = activity_service.create_activity(
        "Edge",
        "msedge.exe",
        "Research",
        start_time="2026-06-18 09:00:00",
    )
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
                ) VALUES (?, ?, 'Edge', 'msedge.exe', 'Research', ?, ?, ?, ?, ?)
                """,
                (
                    activity_id,
                    copied_at,
                    copied_text,
                    copied_text,
                    len(copied_text),
                    copied_at,
                    copied_at,
                ),
            )
    assert clipboard_service.prune_old_events(
        now="2026-06-18 09:00:00"
    ) == 1
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT copied_text FROM activity_clipboard_event ORDER BY copied_at"
        ).fetchall()
    assert [row["copied_text"] for row in rows] == ["new"]


def test_file_text_mappings_include_activity_file_path(temp_db):
    _enable_capture()
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Spec.docx - Word",
        file_path_hint="D:\\Client\\Spec.docx",
        start_time="2026-06-18 09:00:00",
    )
    clipboard_service.record_clipboard_event(
        activity_id,
        "useful copied paragraph",
        _window("D:\\Client\\Spec.docx"),
        copied_at="2026-06-18 09:00:05",
    )
    rows = clipboard_fact_query_service.list_file_text_mappings(
        "2026-06-18 00:00:00",
        "2026-06-18 23:59:59",
    )
    assert rows[0]["file_path"] == "D:\\Client\\Spec.docx"
    assert rows[0]["copied_text"] == "useful copied paragraph"
