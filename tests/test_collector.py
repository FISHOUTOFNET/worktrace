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
