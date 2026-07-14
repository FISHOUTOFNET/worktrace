from __future__ import annotations

import threading
import time

import pytest

from tests.support.activity_factory import create_closed_activity
from tests.support.db_helpers import assign_activity_project, fetch_one

from worktrace.collector import activity_session_recorder as recorder_module
from worktrace.collector.activity_session_recorder import ActivitySessionRecorder
from worktrace.collector.collector import CollectorControl, _sleep_until_next_poll
from worktrace.platforms.hardened_windows_adapter import _ClipboardMonitor
from worktrace.security.kdf import KdfError, KdfParams, derive_backup_key
from worktrace.services import (
    activity_lifecycle_service,
    activity_service,
    folder_rule_service,
    project_service,
    timeline_service,
)
from worktrace.services.folder_index_recovery_service import (
    recover_interrupted_indexes,
)
from worktrace.services.privacy_anonymization_service import anonymize_activity
from worktrace.services.secure_backup_service import SecureImportCoordinator

pytestmark = [
    pytest.mark.db,
    pytest.mark.integration,
    pytest.mark.contract,
    pytest.mark.serial,
]


def test_pause_timeout_cancels_stale_command():
    control = CollectorControl()

    result = control.request_pause(timeout_seconds=0)

    assert result == {
        "ok": False,
        "pause_pending": False,
        "timed_out": True,
    }
    assert control.take_pause_request() is False


def test_reset_command_is_acknowledged_once():
    control = CollectorControl()
    result_box: dict[str, dict] = {}

    thread = threading.Thread(
        target=lambda: result_box.setdefault(
            "result",
            control.request_reset(timeout_seconds=2),
        ),
        daemon=True,
    )
    thread.start()
    for _ in range(100):
        if control.take_reset_request():
            break
        time.sleep(0.005)
    else:  # pragma: no cover - deterministic failure branch
        pytest.fail("reset command was not published")
    control.complete_reset({"ok": True, "reset_pending": False})
    thread.join(timeout=2)

    assert result_box["result"] == {"ok": True, "reset_pending": False}
    assert control.take_reset_request() is False


def test_long_poll_gap_rebases_instead_of_replaying_ticks():
    next_deadline = _sleep_until_next_poll(
        threading.Event(),
        None,
        1.0,
        monotonic_func=lambda: 28_800.0,
        wait_func=lambda *_args: pytest.fail("must not wait after long gap"),
    )

    assert next_deadline == pytest.approx(28_801.0)


def test_recorder_generation_reset_forgets_old_activity_id(monkeypatch):
    cleared: list[str] = []

    class Publisher:
        def clear(self, reason: str) -> None:
            cleared.append(reason)

    monkeypatch.setattr(
        recorder_module,
        "clear_runtime_activity_state",
        lambda reason: cleared.append(reason),
    )
    recorder = ActivitySessionRecorder(snapshot_publisher=Publisher())
    recorder.current_payload = {"status": "normal"}
    recorder.current_signature = ("normal", "kind", "subtype", "identity")
    recorder.current_start_time = "2026-07-15 09:00:00"
    recorder.current_last_seen_time = "2026-07-15 09:01:00"
    recorder.persisted_activity_id = 77

    recorder.clear_runtime_state("database_generation_changed")

    assert recorder.current_payload is None
    assert recorder.current_signature is None
    assert recorder.current_start_time is None
    assert recorder.current_last_seen_time is None
    assert recorder.persisted_activity_id is None
    assert "database_generation_changed" in cleared


def test_maintenance_coordinator_pauses_and_resets_before_operation(temp_db):
    calls: list[str] = []
    coordinator = SecureImportCoordinator()
    coordinator.register_collector_pause_handler(
        lambda timeout_seconds=5.0: (
            calls.append("pause")
            or {"ok": True, "pause_pending": False}
        )
    )
    coordinator.register_collector_reset_handler(
        lambda timeout_seconds=5.0: (
            calls.append("reset")
            or {"ok": True, "reset_pending": False}
        )
    )

    with coordinator.acquire(reason="test") as guard:
        calls.append("operation")
        guard.mark_succeeded()

    assert calls == ["pause", "reset", "operation"]


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

    assert [item["activity_ids"] for item in sessions] == [[first], [second]]
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


def test_clipboard_monitor_does_not_start_or_retain_while_disabled():
    monitor = _ClipboardMonitor()

    monitor.set_enabled(False)
    assert monitor.drain() == []
    assert monitor._thread is None


def test_kdf_rejects_excessive_resource_parameters():
    with pytest.raises(KdfError, match="resource"):
        derive_backup_key(
            "passphrase",
            b"0" * 16,
            KdfParams(n=2**19, r=8, p=1),
        )
