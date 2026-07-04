import threading
import time
import inspect

import pytest

pytestmark = [pytest.mark.collector_runtime, pytest.mark.integration, pytest.mark.db, pytest.mark.serial]

from worktrace.collector.collector import (
    CollectorControl,
    _midnight_crossed_between,
    _normalize_poll_interval_setting,
    run_collector,
)
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


def test_legacy_five_second_poll_interval_is_normalized(temp_db):
    settings_service.set_setting("poll_interval_seconds", "5")

    _normalize_poll_interval_setting()

    assert settings_service.get_setting("poll_interval_seconds") == "1"


def test_invalid_poll_interval_is_normalized(temp_db):
    settings_service.set_setting("poll_interval_seconds", "bad")

    _normalize_poll_interval_setting()

    assert settings_service.get_setting("poll_interval_seconds") == "1"


def test_custom_non_legacy_poll_interval_is_preserved(temp_db):
    settings_service.set_setting("poll_interval_seconds", "2")

    _normalize_poll_interval_setting()

    assert settings_service.get_setting("poll_interval_seconds") == "2"


def test_collector_observation_time_is_after_active_window_fast_path():
    source = inspect.getsource(run_collector)
    active_pos = source.find("active_window = adapter.get_active_window()")
    observation_pos = source.find("observation_time = now_str()", active_pos)
    transition_pos = source.find('machine.transition_to("recording"', observation_pos)
    assert active_pos != -1
    assert observation_pos > active_pos
    assert transition_pos > observation_pos
    assert "at_time=observation_time" in source


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


def test_collector_control_pause_finalizes_before_exposing_paused(monkeypatch):
    from worktrace.collector import collector as collector_mod

    calls: list[str] = []

    class FakeMachine:
        def pause(self, at_time=None):
            calls.append("machine.pause")

        def transition_to(self, state, at_time=None):
            calls.append("machine.transition_to:" + state)

    class RaisingAdapter:
        def get_active_window(self):
            raise AssertionError("active window should not be polled")

        def get_idle_seconds(self):
            raise AssertionError("idle state should not be polled")

    def fake_set_setting(key, value):
        if key in ("user_paused", "collector_status"):
            calls.append(f"set:{key}:{value}")

    monkeypatch.setattr(collector_mod, "CollectorStateMachine", lambda: FakeMachine())
    monkeypatch.setattr(collector_mod, "set_setting", fake_set_setting)
    monkeypatch.setattr(collector_mod, "get_setting", lambda key, default=None: default or "1")
    monkeypatch.setattr(collector_mod, "get_int_setting", lambda key, default=1: 1)
    monkeypatch.setattr(
        collector_mod,
        "get_bool_setting",
        lambda key, default=False: True if key == "first_run_notice_accepted" else False,
    )
    monkeypatch.setattr(collector_mod.recovery_service, "recover_unclosed_records", lambda: None)
    monkeypatch.setattr(collector_mod.clipboard_service, "prune_old_events", lambda: None)
    monkeypatch.setattr(collector_mod, "update_heartbeat", lambda status: calls.append("heartbeat:" + status))
    monkeypatch.setattr(collector_mod, "now_str", lambda: "2026-07-05 10:00:00")

    stop_event = threading.Event()
    control = CollectorControl()
    thread = threading.Thread(
        target=run_collector,
        args=(RaisingAdapter(), stop_event, control),
        daemon=True,
    )
    thread.start()
    result = control.request_pause(timeout_seconds=2)
    stop_event.set()
    thread.join(timeout=2)

    assert result == {"ok": True, "pause_pending": False}
    pause_index = calls.index("machine.pause")
    user_index = calls.index("set:user_paused:true")
    status_index = calls.index("set:collector_status:paused")
    assert pause_index < user_index < status_index


def test_collector_paused_branches_pause_before_status(monkeypatch):
    from worktrace.collector import collector as collector_mod

    calls: list[str] = []

    class FakeMachine:
        def pause(self, at_time=None):
            calls.append("machine.pause")

    monkeypatch.setattr(collector_mod, "update_heartbeat", lambda status: None)
    monkeypatch.setattr(collector_mod, "set_setting", lambda key, value: calls.append(f"set:{key}:{value}"))

    collector_mod._pause_machine_then_expose(FakeMachine(), "2026-07-05 10:00:00")

    assert calls[0] == "machine.pause"
    assert calls[1] == "set:collector_status:paused"


def test_collector_skips_active_window_when_import_guard_active(temp_db):
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
    assert activity_service.get_activities_by_date(time.strftime("%Y-%m-%d")) == []


def test_no_new_activity_during_import_guard(temp_db):
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
