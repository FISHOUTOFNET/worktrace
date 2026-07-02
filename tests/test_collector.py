import threading
import time

from worktrace.collector.collector import _midnight_crossed_between, run_collector
from worktrace.platforms.base import ActiveWindow
from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.services import activity_service, settings_service


def test_collector_loop_with_fake_adapter(temp_db):
    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.set_setting("poll_interval_seconds", "1")
    settings_service.set_setting("idle_threshold_seconds", "60")
    adapter = FakeAdapter(
        windows=[ActiveWindow("Word", "word.exe", "Doc"), ActiveWindow("Excel", "excel.exe", "Sheet")],
        idle_values=[0, 0],
    )
    stop_event = threading.Event()
    thread = threading.Thread(target=run_collector, args=(adapter, stop_event), daemon=True)
    thread.start()
    time.sleep(1.3)
    stop_event.set()
    thread.join(timeout=3)
    rows = activity_service.get_activities_by_date(time.strftime("%Y-%m-%d"))
    assert rows == []
    assert settings_service.get_setting("collector_status") == "stopped"
    assert settings_service.get_setting("current_activity_snapshot", "") == ""


def test_collector_pause_does_not_poll_active_window(temp_db):
    class RaisingAdapter:
        calls = 0

        def get_active_window(self):
            self.calls += 1
            raise AssertionError("active window should not be polled while paused")

        def get_idle_seconds(self):
            raise AssertionError("idle state should not be polled while paused")

    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.set_setting("user_paused", "true")
    settings_service.set_setting("poll_interval_seconds", "1")
    settings_service.set_setting("current_activity_snapshot", '{"status":"normal"}')
    adapter = RaisingAdapter()
    stop_event = threading.Event()
    thread = threading.Thread(target=run_collector, args=(adapter, stop_event), daemon=True)
    thread.start()
    time.sleep(1.2)
    stop_event.set()
    thread.join(timeout=3)

    assert adapter.calls == 0
    assert activity_service.get_activities_by_date(time.strftime("%Y-%m-%d")) == []
    assert settings_service.get_setting("current_activity_snapshot", "") == ""


#
# When ``secure_import_in_progress=true`` the collector loop must skip
# active-window polling and must not write any real activity rows.


def test_collector_skips_active_window_when_import_guard_active(temp_db):
    """The collector must not poll the active window while the import guard is set."""

    class RaisingAdapter:
        calls = 0

        def get_active_window(self):
            self.calls += 1
            raise AssertionError("active window should not be polled during secure import")

        def get_idle_seconds(self):
            raise AssertionError("idle state should not be polled during secure import")

    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("secure_import_in_progress", "true")
    settings_service.set_setting("poll_interval_seconds", "1")
    settings_service.set_setting("current_activity_snapshot", '{"status":"normal"}')
    adapter = RaisingAdapter()
    stop_event = threading.Event()
    thread = threading.Thread(target=run_collector, args=(adapter, stop_event), daemon=True)
    thread.start()
    time.sleep(1.2)
    stop_event.set()
    thread.join(timeout=3)

    assert adapter.calls == 0
    # Note: collector_status will be "stopped" after the thread exits because
    # run_collector sets it on shutdown. The key assertion is that the active
    # window was never polled while the guard was active.
    assert activity_service.get_activities_by_date(time.strftime("%Y-%m-%d")) == []


def test_no_new_activity_during_import_guard(temp_db):
    """No activity_log rows should be created while the import guard is active."""
    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("secure_import_in_progress", "true")
    settings_service.set_setting("poll_interval_seconds", "1")
    settings_service.set_setting("idle_threshold_seconds", "60")

    adapter = FakeAdapter(
        windows=[ActiveWindow("GuardTestApp", "guard.exe", "Guard-Test-Window-Title-7Q2")],
        idle_values=[0],
    )
    stop_event = threading.Event()
    thread = threading.Thread(target=run_collector, args=(adapter, stop_event), daemon=True)
    thread.start()
    time.sleep(1.3)
    stop_event.set()
    thread.join(timeout=3)

    rows = activity_service.get_activities_by_date(time.strftime("%Y-%m-%d"))
    assert rows == [], f"no activity should be recorded during import guard, got {rows}"


def test_no_real_title_path_stored_during_import_guard(temp_db):
    """No real window title or file path should be persisted while the guard is active."""
    from worktrace.db import get_connection

    settings_service.set_setting("first_run_notice_accepted", "true")
    settings_service.set_setting("user_paused", "false")
    settings_service.set_setting("secure_import_in_progress", "true")
    settings_service.set_setting("poll_interval_seconds", "1")
    settings_service.set_setting("idle_threshold_seconds", "60")

    sensitive_title = "Guard-Leak-Test-Window-9XK"
    sensitive_path = "C:\\Guard-Leak-Test-Path-5M8\\secret.docx"
    adapter = FakeAdapter(
        windows=[ActiveWindow("LeakApp", "leak.exe", sensitive_title)],
        idle_values=[0],
    )
    stop_event = threading.Event()
    thread = threading.Thread(target=run_collector, args=(adapter, stop_event), daemon=True)
    thread.start()
    time.sleep(1.3)
    stop_event.set()
    thread.join(timeout=3)

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT window_title, file_path_hint FROM activity_log"
        ).fetchall()
    for row in rows:
        assert sensitive_title not in (row["window_title"] or "")
        assert sensitive_path not in (row["file_path_hint"] or "")


def test_midnight_crossing_detects_exact_boundary():
    assert _midnight_crossed_between("2026-06-18 23:59:59", "2026-06-19 00:00:02") == "2026-06-19 00:00:00"
    assert _midnight_crossed_between("2026-06-18 23:59:59", "2026-06-18 23:59:59") is None
    assert _midnight_crossed_between("2026-06-19 00:00:01", "2026-06-19 00:00:02") is None
