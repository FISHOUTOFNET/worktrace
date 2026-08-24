from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from worktrace.collector import collector as collector_mod
from worktrace.platforms.base import ActiveWindow


pytestmark = [pytest.mark.collector_runtime]


class _FakeMachine:
    def __init__(self, stop_event: threading.Event) -> None:
        self.stop_event = stop_event
        self.transitions: list[tuple[str, str]] = []
        self.resets: list[str] = []
        self.stops: list[tuple[str, str]] = []

    def transition_to(self, state: str, *_args, at_time: str) -> None:
        self.transitions.append((state, at_time))

    def reset_for_time_jump(self, safe_end_time: str) -> None:
        self.resets.append(safe_end_time)
        self.stop_event.set()

    def stop(self, *, at_time: str, reason: str) -> None:
        self.stops.append((at_time, reason))


class _LateSuccessAdapter:
    def __init__(self, clock: dict[str, object]) -> None:
        self.clock = clock

    def get_active_window(self) -> ActiveWindow:
        self.clock["wall"] = "2026-08-24 09:03:20"
        self.clock["monotonic"] = 200.0
        return ActiveWindow("Word", "word.exe", "Doc")

    def get_idle_seconds(self) -> int:
        return 0

    def set_clipboard_capture_enabled(self, _enabled: bool) -> None:
        return None

    def get_clipboard_events(self):
        return []


class _LateFatalAdapter(_LateSuccessAdapter):
    def get_active_window(self) -> ActiveWindow:
        self.clock["wall"] = "2026-08-24 09:03:20"
        self.clock["monotonic"] = 200.0
        raise RuntimeError("synthetic fatal after stall")


def _install_runtime_stubs(
    monkeypatch: pytest.MonkeyPatch,
    stop_event: threading.Event,
    clock: dict[str, object],
):
    machine = _FakeMachine(stop_event)
    successful_observations: list[str] = []

    monkeypatch.setattr(collector_mod, "CollectorStateMachine", lambda: machine)
    monkeypatch.setattr(collector_mod, "now_str", lambda: str(clock["wall"]))
    monkeypatch.setattr(
        collector_mod.time,
        "monotonic",
        lambda: float(clock["monotonic"]),
    )
    monkeypatch.setattr(collector_mod, "_normalize_poll_interval_setting", lambda: None)
    monkeypatch.setattr(collector_mod, "_run_clipboard_maintenance_tick", lambda: None)
    monkeypatch.setattr(collector_mod, "_set_clipboard_capture_enabled", lambda *_args: None)
    monkeypatch.setattr(collector_mod, "update_heartbeat", lambda *_args: None)
    monkeypatch.setattr(collector_mod, "get_bool_setting", lambda *_args: False)

    def get_int_setting(key: str, default: int) -> int:
        values = {
            "idle_threshold_seconds": 60,
            "clock_jump_threshold_seconds": 300,
            "collector_stall_threshold_seconds": 180,
        }
        return values.get(key, default)

    monkeypatch.setattr(collector_mod, "get_int_setting", get_int_setting)
    monkeypatch.setattr(
        collector_mod.privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: True,
    )
    monkeypatch.setattr(
        collector_mod.privacy_service,
        "evaluate_exclusion",
        lambda _window: SimpleNamespace(
            excluded=False,
            refresh_required=False,
            resolution_pending=False,
        ),
    )
    monkeypatch.setattr(
        collector_mod.clipboard_service,
        "is_capture_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_collector_started",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_collector_stopped",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_health_code",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_transient_failure",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_fatal_failure",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        collector_mod.collector_health,
        "record_successful_observation",
        successful_observations.append,
    )
    return machine, successful_observations


def test_late_success_is_discarded_before_it_can_advance_durable_time(monkeypatch) -> None:
    stop_event = threading.Event()
    clock: dict[str, object] = {
        "wall": "2026-08-24 09:00:00",
        "monotonic": 0.0,
    }
    machine, successful = _install_runtime_stubs(
        monkeypatch,
        stop_event,
        clock,
    )

    collector_mod.run_collector(_LateSuccessAdapter(clock), stop_event)

    assert machine.resets == ["2026-08-24 09:00:00"]
    assert ("recording", "2026-08-24 09:03:20") not in machine.transitions
    assert successful == []
    assert machine.transitions[-1] == ("stopped", "2026-08-24 09:00:00")


def test_fatal_after_blocking_observation_closes_at_last_safe_boundary(monkeypatch) -> None:
    stop_event = threading.Event()
    clock: dict[str, object] = {
        "wall": "2026-08-24 09:00:00",
        "monotonic": 0.0,
    }
    machine, successful = _install_runtime_stubs(
        monkeypatch,
        stop_event,
        clock,
    )

    collector_mod.run_collector(_LateFatalAdapter(clock), stop_event)

    assert successful == []
    assert machine.transitions == []
    assert machine.stops == [
        ("2026-08-24 09:00:00", "fatal_collector_stop")
    ]
