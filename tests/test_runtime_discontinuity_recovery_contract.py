from __future__ import annotations

import pytest

from worktrace.collector import collector
from worktrace.collector.clock_tracker import ClockDiscontinuity
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.platforms.base import PlatformTemporarilyUnavailableError

pytestmark = [pytest.mark.unit, pytest.mark.collector_runtime]


def _discontinuity() -> ClockDiscontinuity:
    return ClockDiscontinuity(
        reason="collector_stall",
        safe_end_time="2026-09-01 10:00:00",
        wall_delta_seconds=181.0,
        monotonic_delta_seconds=181.0,
    )


def test_runtime_discontinuity_recovery_orders_collector_and_platform_reset(
    monkeypatch,
):
    calls: list[tuple[object, ...]] = []

    class Adapter:
        def set_clipboard_capture_enabled(self, enabled):
            calls.append(("clipboard", enabled))

        def reset_runtime_state(self):
            calls.append(("platform_reset",))

    class Machine:
        def reset_for_runtime_discontinuity(self, *, at_time, reason):
            calls.append(("collector_reset", at_time, reason))

    monkeypatch.setattr(
        collector.collector_health,
        "record_health_code",
        lambda code, at: calls.append(("health", code, at)),
    )

    deadline = collector._recover_runtime_discontinuity(
        adapter=Adapter(),
        machine=Machine(),
        discontinuity=_discontinuity(),
        at_time="2026-09-01 10:03:01",
        monotonic_time=500.0,
    )

    assert calls == [
        ("clipboard", False),
        ("collector_reset", "2026-09-01 10:00:00", "collector_stall"),
        ("platform_reset",),
        ("health", "collector_stall", "2026-09-01 10:03:01"),
    ]
    assert deadline == pytest.approx(501.0)


def test_runtime_discontinuity_recovery_can_retry_after_platform_reset_failure(
    monkeypatch,
):
    calls: list[str] = []

    class Adapter:
        attempts = 0

        def set_clipboard_capture_enabled(self, enabled):
            calls.append(f"clipboard:{enabled}")

        def reset_runtime_state(self):
            self.attempts += 1
            calls.append(f"platform:{self.attempts}")
            if self.attempts == 1:
                raise PlatformTemporarilyUnavailableError("resume_in_progress")

    class Machine:
        def reset_for_runtime_discontinuity(self, *, at_time, reason):
            calls.append("collector")

    monkeypatch.setattr(
        collector.collector_health,
        "record_health_code",
        lambda *_args: calls.append("health"),
    )

    adapter = Adapter()
    with pytest.raises(PlatformTemporarilyUnavailableError):
        collector._recover_runtime_discontinuity(
            adapter=adapter,
            machine=Machine(),
            discontinuity=_discontinuity(),
            at_time="2026-09-01 10:03:01",
            monotonic_time=500.0,
        )

    deadline = collector._recover_runtime_discontinuity(
        adapter=adapter,
        machine=Machine(),
        discontinuity=_discontinuity(),
        at_time="2026-09-01 10:03:02",
        monotonic_time=501.0,
    )

    assert calls == [
        "clipboard:False",
        "collector",
        "platform:1",
        "clipboard:False",
        "collector",
        "platform:2",
        "health",
    ]
    assert deadline == pytest.approx(502.0)


def test_state_machine_discontinuity_reset_is_idempotent(monkeypatch):
    machine = CollectorStateMachine()
    machine.state = "recording"
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        machine,
        "_stop_recording_at_boundary",
        lambda at_time, reason: calls.append((at_time, reason)),
    )

    machine.reset_for_runtime_discontinuity(
        at_time="2026-09-01 10:00:00",
        reason="collector_stall",
    )
    machine.reset_for_runtime_discontinuity(
        at_time="2026-09-01 10:00:00",
        reason="collector_stall",
    )

    assert calls == [("2026-09-01 10:00:00", "sleep_resume")]
    assert machine.state == "stopped"
    assert machine.active_signature is None


def test_discontinuity_telemetry_contains_safe_clock_deltas(caplog):
    with caplog.at_level("WARNING"):
        collector._log_runtime_discontinuity(_discontinuity())

    assert any(
        "discontinuity_reason=collector_stall" in item.message
        and "wall_delta_seconds=181.000" in item.message
        and "monotonic_delta_seconds=181.000" in item.message
        for item in caplog.records
    )
