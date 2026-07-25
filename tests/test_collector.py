from tests.support import runtime_state_fixture

import inspect
import re
import threading
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.collector_runtime,
    pytest.mark.integration,
    pytest.mark.db,
    pytest.mark.serial,
]

from worktrace.collector import collector as collector_mod
from worktrace.collector.collector import (
    CollectorControl,
    CollectorHoldState,
    _midnight_crossed_between,
    _normalize_poll_interval_setting,
    _sleep_until_next_poll,
    run_collector,
)
from worktrace.platforms.base import ActiveWindow
from worktrace.platforms.fake_adapter import FakeAdapter
from worktrace.services import activity_service, privacy_gate_service, settings_service


def _stop_after_poll(monkeypatch, stop_event):
    def fake_poll_wait(_stop_event, _control, next_poll_deadline):
        stop_event.set()
        return next_poll_deadline + 1.0

    monkeypatch.setattr(collector_mod, "_sleep_until_next_poll", fake_poll_wait)


def _queue_maintenance_hold(
    control: CollectorControl,
    result: dict,
) -> threading.Thread:
    def request() -> None:
        result.update(control.request_maintenance_hold(timeout_seconds=2.0))

    thread = threading.Thread(target=request, daemon=True)
    thread.start()
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if control.hold_state is CollectorHoldState.HOLD_REQUESTED:
            return thread
        thread.join(timeout=0.005)
    raise AssertionError("maintenance hold request was not queued")


def test_collector_loop_with_fake_adapter(temp_db, monkeypatch):
    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("poll_interval_seconds", "1")
    settings_service.set_setting("idle_threshold_seconds", "60")
    adapter = FakeAdapter(
        windows=[
            ActiveWindow("Word", "word.exe", "Doc"),
            ActiveWindow("Excel", "excel.exe", "Sheet"),
        ],
        idle_values=[0, 0],
    )
    stop_event = threading.Event()
    _stop_after_poll(monkeypatch, stop_event)
    thread = threading.Thread(
        target=run_collector,
        args=(adapter, stop_event),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive(), "collector test thread did not terminate"
    rows = activity_service.get_activities_by_date(time.strftime("%Y-%m-%d"))
    assert len(rows) == 1
    assert rows[0]["app_name"] == "Word"
    assert rows[0]["process_name"] == "word.exe"
    assert rows[0]["window_title"] == "Doc"
    assert rows[0]["status"] == "normal"
    assert settings_service.get_setting("collector_status") == "stopped"
    assert runtime_state_fixture.get_setting("current_activity_snapshot", "") == ""


def test_legacy_five_second_poll_interval_is_normalized(temp_db):
    settings_service.set_setting("poll_interval_seconds", "5")

    _normalize_poll_interval_setting()

    assert settings_service.get_setting("poll_interval_seconds") == "1"


def test_legacy_three_second_poll_interval_is_normalized(temp_db):
    settings_service.set_setting("poll_interval_seconds", "3")

    _normalize_poll_interval_setting()

    assert settings_service.get_setting("poll_interval_seconds") == "1"


def test_invalid_poll_interval_is_normalized(temp_db):
    settings_service.set_setting("poll_interval_seconds", "bad")

    _normalize_poll_interval_setting()

    assert settings_service.get_setting("poll_interval_seconds") == "1"


def test_any_non_one_poll_interval_is_normalized(temp_db):
    settings_service.set_setting("poll_interval_seconds", "2")

    _normalize_poll_interval_setting()

    assert settings_service.get_setting("poll_interval_seconds") == "1"


def test_fixed_rate_poll_sleep_does_not_add_work_time_to_interval():
    stop_event = threading.Event()
    waits: list[float] = []
    times = iter([0.7])

    next_deadline = _sleep_until_next_poll(
        stop_event,
        None,
        1.0,
        monotonic_func=lambda: next(times),
        wait_func=lambda stop, control, timeout: waits.append(timeout),
    )

    assert waits == pytest.approx([0.3])
    assert next_deadline == pytest.approx(2.0)


def test_fixed_rate_poll_skips_extra_sleep_when_work_exceeds_interval():
    stop_event = threading.Event()
    waits: list[float] = []

    next_deadline = _sleep_until_next_poll(
        stop_event,
        None,
        1.0,
        monotonic_func=lambda: 1.2,
        wait_func=lambda stop, control, timeout: waits.append(timeout),
    )

    assert waits == []
    assert next_deadline == pytest.approx(2.0)


def test_fixed_rate_poll_wait_can_be_interrupted_by_pause_request():
    stop_event = threading.Event()
    control = CollectorControl()
    waits: list[float] = []

    def fake_control_wait(stop, timeout):
        waits.append(timeout)

    control.wait = fake_control_wait  # type: ignore[method-assign]

    _sleep_until_next_poll(
        stop_event,
        control,
        5.0,
        monotonic_func=lambda: 4.25,
    )

    assert waits == pytest.approx([0.75])


def test_fixed_rate_poll_wait_can_be_interrupted_by_stop_event():
    stop_event = threading.Event()
    waits: list[float] = []

    def fake_stop_wait(timeout):
        waits.append(timeout)
        stop_event.set()

    stop_event.wait = fake_stop_wait  # type: ignore[method-assign]

    _sleep_until_next_poll(
        stop_event,
        None,
        5.0,
        monotonic_func=lambda: 4.25,
    )

    assert waits == pytest.approx([0.75])
    assert stop_event.is_set()


def test_collector_observation_time_is_after_active_window_fast_path():
    source = inspect.getsource(run_collector)
    active_pos = source.find("active_window = adapter.get_active_window()")
    observation_pos = source.find("observation_time = now_str()", active_pos)
    transition_match = re.search(
        r'machine\.transition_to\(\s*"recording"',
        source[observation_pos:],
    )
    transition_pos = (
        observation_pos + transition_match.start()
        if transition_match is not None
        else -1
    )
    assert active_pos != -1
    assert observation_pos > active_pos
    assert transition_pos > observation_pos
    assert "at_time=observation_time" in source


def test_collector_pause_does_not_poll_active_window(temp_db, monkeypatch):
    class RaisingAdapter:
        calls = 0

        def get_active_window(self):
            self.calls += 1
            raise AssertionError("active window should not be polled while paused")

        def get_idle_seconds(self):
            raise AssertionError("idle state should not be polled while paused")

        def set_clipboard_capture_enabled(self, enabled: bool) -> None:
            return None

        def get_clipboard_events(self):
            return []

    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("user_paused", "true")
    settings_service.set_setting("poll_interval_seconds", "1")
    runtime_state_fixture.set_setting(
        "current_activity_snapshot",
        '{"status":"normal"}',
    )
    adapter = RaisingAdapter()
    stop_event = threading.Event()
    _stop_after_poll(monkeypatch, stop_event)
    thread = threading.Thread(
        target=run_collector,
        args=(adapter, stop_event),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive(), "collector test thread did not terminate"

    assert adapter.calls == 0
    rows = activity_service.get_activities_by_date(time.strftime("%Y-%m-%d"))
    non_system_rows = [row for row in rows if row["resource_kind"] != "system"]
    assert non_system_rows == []
    assert runtime_state_fixture.get_setting("current_activity_snapshot", "") == ""


def test_collector_control_pause_completes_lifecycle_before_ack(monkeypatch):
    calls: list[str] = []

    class FakeMachine:
        """Fake machine aligned with the CollectorStateMachine interface.

        Records all lifecycle calls so tests can verify ordering.  The
        production pause path calls ``pause()``, not ``stop()`` —
        ``stop()`` is only called on fatal collector failure.  Both
        methods are present here for interface completeness.
        """

        def pause(self, at_time=None):
            calls.append("machine.pause")

        def transition_to(self, state, at_time=None):
            calls.append("machine.transition_to:" + state)

        def stop(self, at_time=None, reason="user_stop"):
            calls.append("machine.stop:" + reason)

        def reset_runtime_state(self, reason):
            calls.append("machine.reset_runtime_state:" + reason)

        def quiesce_for_maintenance(self, at_time=None):
            calls.append("machine.quiesce_for_maintenance")

        def split_at_midnight(self, midnight):
            calls.append("machine.split_at_midnight")

        def record_clipboard_event(self, event, at_time=None):
            calls.append("machine.record_clipboard_event")

    class RaisingAdapter:
        def get_active_window(self):
            raise AssertionError("active window should not be polled")

        def get_idle_seconds(self):
            raise AssertionError("idle state should not be polled")

        def set_clipboard_capture_enabled(self, enabled: bool) -> None:
            return None

        def get_clipboard_events(self):
            return []

    monkeypatch.setattr(collector_mod, "CollectorStateMachine", lambda: FakeMachine())
    monkeypatch.setattr(
        collector_mod,
        "get_setting",
        lambda key, default=None: default or "1",
    )
    monkeypatch.setattr(collector_mod, "get_int_setting", lambda key, default=1: 1)
    monkeypatch.setattr(
        collector_mod,
        "get_bool_setting",
        lambda key, default=False: False,
    )
    monkeypatch.setattr(
        collector_mod.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )
    monkeypatch.setattr(
        collector_mod.clipboard_service,
        "prune_old_events",
        lambda: None,
    )
    monkeypatch.setattr(
        collector_mod,
        "update_heartbeat",
        lambda status: calls.append("heartbeat:" + status),
    )
    monkeypatch.setattr(
        collector_mod,
        "now_str",
        lambda: "2026-07-05 10:00:00",
    )

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
    assert not thread.is_alive(), "collector test thread did not terminate"

    assert result["ok"] is True
    assert result["pause_pending"] is False
    assert result["command_state"] == "completed"
    assert result["command_state_unknown"] is False
    assert isinstance(result["command_id"], str) and result["command_id"]
    pause_index = calls.index("machine.pause")
    heartbeat_index = calls.index("heartbeat:paused")
    assert pause_index < heartbeat_index
    # Pause path must NOT call stop() — stop is for fatal failures only.
    assert not any(c.startswith("machine.stop") for c in calls), (
        f"pause path must not call machine.stop(), calls={calls}"
    )


def test_collector_fatal_stop_calls_machine_stop_once(monkeypatch):
    """Fatal collector failure must call machine.stop() exactly once.

    The production shutdown path (collector.py lines 622-628) calls
    ``machine.stop(at_time=..., reason='fatal_collector_stop')`` when
    ``fatal_stop`` is True.  This test verifies the lifecycle contract:
    stop is called once with the correct reason, and the collector
    records stopped after the machine lifecycle completes.
    """
    calls: list[str] = []
    stop_reasons: list[str] = []

    class FakeMachine:
        def __init__(self) -> None:
            self.stop_error: Exception | None = None

        def pause(self, at_time=None):
            calls.append("machine.pause")

        def transition_to(self, state, at_time=None):
            calls.append("machine.transition_to:" + state)

        def stop(self, at_time=None, reason="user_stop"):
            calls.append("machine.stop:" + reason)
            stop_reasons.append(reason)
            if self.stop_error is not None:
                raise self.stop_error

        def reset_runtime_state(self, reason):
            calls.append("machine.reset_runtime_state:" + reason)

        def quiesce_for_maintenance(self, at_time=None):
            calls.append("machine.quiesce_for_maintenance")

        def split_at_midnight(self, midnight):
            calls.append("machine.split_at_midnight")

        def record_clipboard_event(self, event, at_time=None):
            calls.append("machine.record_clipboard_event")

    class FatalAdapter:
        """Adapter that raises a non-retryable error on first poll."""

        def get_active_window(self):
            raise RuntimeError("fatal_adapter_failure")

        def get_idle_seconds(self):
            raise AssertionError("should not reach idle after fatal")

        def set_clipboard_capture_enabled(self, enabled: bool) -> None:
            return None

        def get_clipboard_events(self):
            return []

    fake_machine = FakeMachine()
    monkeypatch.setattr(collector_mod, "CollectorStateMachine", lambda: fake_machine)
    monkeypatch.setattr(
        collector_mod,
        "get_setting",
        lambda key, default=None: default or "1",
    )
    monkeypatch.setattr(collector_mod, "get_int_setting", lambda key, default=1: 1)
    monkeypatch.setattr(
        collector_mod,
        "get_bool_setting",
        lambda key, default=False: False,
    )
    monkeypatch.setattr(
        collector_mod.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )
    monkeypatch.setattr(
        collector_mod.clipboard_service,
        "prune_old_events",
        lambda: None,
    )
    monkeypatch.setattr(
        collector_mod,
        "update_heartbeat",
        lambda status: calls.append("heartbeat:" + status),
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_collector_stopped",
        lambda at_time: calls.append("record_collector_stopped"),
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_fatal_failure",
        lambda phase, code, at_time: calls.append("record_fatal_failure"),
    )

    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_collector,
        args=(FatalAdapter(), stop_event),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive(), "collector thread did not terminate after fatal"

    # machine.stop() called exactly once with fatal reason.
    stop_calls = [c for c in calls if c.startswith("machine.stop:")]
    assert len(stop_calls) == 1, f"expected 1 stop call, got {stop_calls}"
    assert "fatal_collector_stop" in stop_calls[0]

    # Lifecycle ordering: stop before record_collector_stopped.
    stop_index = calls.index(stop_calls[0])
    stopped_index = calls.index("record_collector_stopped")
    assert stop_index < stopped_index, (
        f"machine.stop must precede record_collector_stopped, calls={calls}"
    )


def test_collector_fatal_stop_survives_stop_failure(monkeypatch):
    """If machine.stop() raises during fatal shutdown, the collector must
    still record stopped (via the finally block) and terminate cleanly.
    """
    calls: list[str] = []

    class FakeMachine:
        def __init__(self) -> None:
            self.stop_error: Exception | None = RuntimeError("stop_failed")

        def pause(self, at_time=None):
            calls.append("machine.pause")

        def transition_to(self, state, at_time=None):
            calls.append("machine.transition_to:" + state)

        def stop(self, at_time=None, reason="user_stop"):
            calls.append("machine.stop:" + reason)
            if self.stop_error is not None:
                raise self.stop_error

        def reset_runtime_state(self, reason):
            calls.append("machine.reset_runtime_state:" + reason)

        def quiesce_for_maintenance(self, at_time=None):
            calls.append("machine.quiesce_for_maintenance")

        def split_at_midnight(self, midnight):
            calls.append("machine.split_at_midnight")

        def record_clipboard_event(self, event, at_time=None):
            calls.append("machine.record_clipboard_event")

    class FatalAdapter:
        def get_active_window(self):
            raise RuntimeError("fatal_adapter_failure")

        def get_idle_seconds(self):
            raise AssertionError("should not reach idle")

        def set_clipboard_capture_enabled(self, enabled: bool) -> None:
            return None

        def get_clipboard_events(self):
            return []

    monkeypatch.setattr(
        collector_mod, "CollectorStateMachine", lambda: FakeMachine()
    )
    monkeypatch.setattr(
        collector_mod,
        "get_setting",
        lambda key, default=None: default or "1",
    )
    monkeypatch.setattr(collector_mod, "get_int_setting", lambda key, default=1: 1)
    monkeypatch.setattr(
        collector_mod,
        "get_bool_setting",
        lambda key, default=False: False,
    )
    monkeypatch.setattr(
        collector_mod.privacy_gate_service,
        "is_privacy_notice_accepted",
        lambda: True,
    )
    monkeypatch.setattr(
        collector_mod.clipboard_service,
        "prune_old_events",
        lambda: None,
    )
    monkeypatch.setattr(
        collector_mod,
        "update_heartbeat",
        lambda status: calls.append("heartbeat:" + status),
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_collector_stopped",
        lambda at_time: calls.append("record_collector_stopped"),
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_fatal_failure",
        lambda phase, code, at_time: calls.append("record_fatal_failure"),
    )

    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_collector,
        args=(FatalAdapter(), stop_event),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive(), "collector thread did not terminate"

    # stop() was called (and raised), but record_collector_stopped still ran.
    assert any(c.startswith("machine.stop") for c in calls)
    assert "record_collector_stopped" in calls
    stop_index = next(i for i, c in enumerate(calls) if c.startswith("machine.stop"))
    stopped_index = calls.index("record_collector_stopped")
    assert stop_index < stopped_index


def test_collector_paused_branch_delegates_to_lifecycle_machine(monkeypatch):
    calls: list[str] = []

    class FakeMachine:
        def pause(self, at_time=None):
            calls.append("machine.pause")

    monkeypatch.setattr(collector_mod, "update_heartbeat", lambda status: None)
    collector_mod._pause_machine_then_expose(
        FakeMachine(),
        "2026-07-05 10:00:00",
    )

    assert calls == ["machine.pause"]


def test_maintenance_hold_prevents_sampling_and_activity_writes(temp_db):
    class RaisingAdapter:
        calls = 0

        def get_active_window(self):
            self.calls += 1
            raise AssertionError("active window must not be sampled while held")

        def get_idle_seconds(self):
            raise AssertionError("idle state must not be sampled while held")

        def get_clipboard_events(self):
            raise AssertionError("clipboard must not be sampled while held")

        def set_clipboard_capture_enabled(self, enabled: bool) -> None:
            return None

    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("user_paused", "false")
    control = CollectorControl()
    result: dict = {}
    request_thread = _queue_maintenance_hold(control, result)
    adapter = RaisingAdapter()
    stop_event = threading.Event()
    collector_thread = threading.Thread(
        target=run_collector,
        args=(adapter, stop_event, control),
        daemon=True,
    )
    collector_thread.start()
    request_thread.join(timeout=2)

    assert not request_thread.is_alive()
    assert result["ok"] is True
    assert result["command_kind"] == "maintenance_hold"
    assert result["command_state"] == "completed"
    assert result["terminal_state"] == "held"
    assert result["command_state_unknown"] is False
    assert control.hold_state is CollectorHoldState.HELD
    assert adapter.calls == 0
    rows = activity_service.get_activities_by_date(time.strftime("%Y-%m-%d"))
    assert [row for row in rows if row["resource_kind"] != "system"] == []

    stop_event.set()
    collector_thread.join(timeout=3)
    assert not collector_thread.is_alive()


def test_maintenance_hold_never_persists_sensitive_adapter_data(temp_db):
    from worktrace.db import get_connection

    sensitive_title = "Hold-Leak-Test-Window-9XK"
    sensitive_path = "C:\\Hold-Leak-Test-Path-5M8\\secret.docx"

    class SensitiveAdapter:
        def get_active_window(self):
            return ActiveWindow(
                "LeakApp",
                "leak.exe",
                sensitive_title,
                sensitive_path,
            )

        def get_idle_seconds(self):
            return 0

        def get_clipboard_events(self):
            return []

        def set_clipboard_capture_enabled(self, enabled: bool) -> None:
            return None

    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("user_paused", "false")
    control = CollectorControl()
    result: dict = {}
    request_thread = _queue_maintenance_hold(control, result)
    stop_event = threading.Event()
    collector_thread = threading.Thread(
        target=run_collector,
        args=(SensitiveAdapter(), stop_event, control),
        daemon=True,
    )
    collector_thread.start()
    request_thread.join(timeout=2)

    assert not request_thread.is_alive()
    assert result["ok"] is True
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT window_title, file_path_hint FROM activity_log"
        ).fetchall()
    for row in rows:
        assert sensitive_title not in (row["window_title"] or "")
        assert sensitive_path not in (row["file_path_hint"] or "")

    stop_event.set()
    collector_thread.join(timeout=3)
    assert not collector_thread.is_alive()


def test_collector_has_no_secure_backup_reverse_dependency():
    root = Path(__file__).resolve().parents[1]
    source = (root / "worktrace" / "collector" / "collector.py").read_text(
        encoding="utf-8"
    )
    assert "secure_backup" not in source
    assert "is_secure_import_in_progress" not in source
    assert "maintenance_hold" in source


def test_midnight_crossing_detects_exact_boundary():
    assert _midnight_crossed_between(
        "2026-06-18 23:59:59",
        "2026-06-19 00:00:02",
    ) == "2026-06-19 00:00:00"
    assert _midnight_crossed_between(
        "2026-06-18 23:59:59",
        "2026-06-18 23:59:59",
    ) is None
    assert _midnight_crossed_between(
        "2026-06-19 00:00:01",
        "2026-06-19 00:00:02",
    ) is None


def test_privacy_gate_false_skips_active_window_and_disables_clipboard(
    temp_db,
    monkeypatch,
):
    monkeypatch.setattr(
        collector_mod.privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: False,
    )
    settings_service.set_setting("poll_interval_seconds", "1")
    settings_service.set_setting("idle_threshold_seconds", "60")
    adapter = FakeAdapter()
    adapter.set_clipboard_capture_enabled(True)
    calls = {"active_window": 0}
    original_get_active_window = adapter.get_active_window

    def tracking_get_active_window():
        calls["active_window"] += 1
        return original_get_active_window()

    adapter.get_active_window = tracking_get_active_window
    stop_event = threading.Event()
    _stop_after_poll(monkeypatch, stop_event)
    thread = threading.Thread(
        target=run_collector,
        args=(adapter, stop_event),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive(), "collector test thread did not terminate"

    assert calls["active_window"] == 0
    assert adapter.clipboard_capture_enabled is False


def test_privacy_gate_read_exception_disables_clipboard_and_skips_observation(
    temp_db,
    monkeypatch,
):
    def raising_gate():
        raise RuntimeError("gate_read_failed")

    monkeypatch.setattr(
        collector_mod.privacy_gate_service,
        "is_sensitive_runtime_allowed",
        raising_gate,
    )
    settings_service.set_setting("poll_interval_seconds", "1")
    settings_service.set_setting("idle_threshold_seconds", "60")
    adapter = FakeAdapter()
    adapter.set_clipboard_capture_enabled(True)
    calls = {"active_window": 0}
    original_get_active_window = adapter.get_active_window

    def tracking_get_active_window():
        calls["active_window"] += 1
        return original_get_active_window()

    adapter.get_active_window = tracking_get_active_window
    stop_event = threading.Event()
    _stop_after_poll(monkeypatch, stop_event)
    thread = threading.Thread(
        target=run_collector,
        args=(adapter, stop_event),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive(), "collector test thread did not terminate"

    assert calls["active_window"] == 0
    assert adapter.clipboard_capture_enabled is False
    assert settings_service.get_setting("collector_last_failure_phase", "") != ""


def test_privacy_state_unavailable_after_enable_closes_clipboard_monitor(
    temp_db,
    monkeypatch,
):
    state = {"calls": 0}

    def stateful_gate():
        state["calls"] += 1
        return state["calls"] == 1

    monkeypatch.setattr(
        collector_mod.privacy_gate_service,
        "is_sensitive_runtime_allowed",
        stateful_gate,
    )
    privacy_gate_service.accept_privacy_notice()
    settings_service.set_setting("poll_interval_seconds", "1")
    settings_service.set_setting("idle_threshold_seconds", "60")
    settings_service.set_setting("clipboard_capture_enabled", "true")
    adapter = FakeAdapter()
    adapter.set_clipboard_capture_enabled(True)
    stop_event = threading.Event()
    sleep_calls = {"count": 0}

    def fake_poll_wait(_stop_event, _control, next_poll_deadline):
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 2:
            stop_event.set()
        return next_poll_deadline + 1.0

    monkeypatch.setattr(collector_mod, "_sleep_until_next_poll", fake_poll_wait)
    thread = threading.Thread(
        target=run_collector,
        args=(adapter, stop_event),
        daemon=True,
    )
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive(), "collector test thread did not terminate"

    assert adapter.clipboard_capture_enabled is False
    assert state["calls"] >= 2
