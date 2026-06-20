import threading
import time

from worktrace.collector.collector import run_collector
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
