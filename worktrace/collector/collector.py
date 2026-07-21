from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time as datetime_time
from enum import Enum
import threading
import time
import uuid
from typing import Any, Callable

from ..constants import DEFAULT_IDLE_THRESHOLD_SECONDS, TIME_FORMAT
from ..db import now_str
from ..platforms.base import PlatformAdapter
from ..services import (
    clipboard_service,
    folder_index_service,
    privacy_gate_service,
    privacy_service,
)
from ..services.settings_service import (
    get_bool_setting,
    get_int_setting,
    get_setting,
    set_setting,
)
from . import collector_health
from .clock_tracker import ClockTracker
from .collector_failure_policy import classify_collector_failure
from .heartbeat import update_heartbeat
from .state_machine import CollectorStateMachine

POLL_CADENCE_SECONDS = 1.0


class CollectorCommandKind(str, Enum):
    USER_PAUSE = "user_pause"
    MAINTENANCE_HOLD = "maintenance_hold"
    DATABASE_RESET = "database_reset"
    MAINTENANCE_RELEASE = "maintenance_release"


class CollectorCommandState(str, Enum):
    PENDING = "pending"
    TAKEN = "taken"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class CollectorHoldState(str, Enum):
    OPERATIONAL = "operational"
    HOLD_REQUESTED = "hold_requested"
    SEALING = "sealing"
    HELD = "held"
    RESETTING = "resetting"
    RELEASE_REQUESTED = "release_requested"


@dataclass
class _CollectorCommand:
    command_id: str
    kind: CollectorCommandKind
    state: CollectorCommandState = CollectorCommandState.PENDING
    done_event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] = field(default_factory=dict)


class CollectorControl:
    """Identity-bearing Collector command channel with observable terminal states."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._wake_event = threading.Event()
        self._commands: dict[str, _CollectorCommand] = {}
        self._pending_ids: dict[CollectorCommandKind, str] = {}
        self._hold_state = CollectorHoldState.OPERATIONAL

    @property
    def hold_state(self) -> CollectorHoldState:
        with self._lock:
            return self._hold_state

    def request_pause(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
        return self._request(CollectorCommandKind.USER_PAUSE, timeout_seconds)

    def take_pause_request(self) -> str | None:
        return self._take(CollectorCommandKind.USER_PAUSE)

    def complete_pause(self, command_id: str, result: dict[str, Any]) -> bool:
        return self._complete(
            command_id,
            CollectorCommandKind.USER_PAUSE,
            result,
            terminal_state=CollectorHoldState.OPERATIONAL,
        )

    def request_maintenance_hold(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        with self._lock:
            if self._hold_state is CollectorHoldState.HELD:
                return self._synthetic_completed(
                    CollectorCommandKind.MAINTENANCE_HOLD,
                    CollectorHoldState.HELD,
                    already_held=True,
                )
            if self._hold_state is not CollectorHoldState.OPERATIONAL:
                return self._state_conflict(CollectorCommandKind.MAINTENANCE_HOLD)
            self._hold_state = CollectorHoldState.HOLD_REQUESTED
        result = self._request(CollectorCommandKind.MAINTENANCE_HOLD, timeout_seconds)
        if not bool(result.get("ok")) and result.get("command_state") == "cancelled":
            with self._lock:
                if self._hold_state is CollectorHoldState.HOLD_REQUESTED:
                    self._hold_state = CollectorHoldState.OPERATIONAL
        return result

    def take_maintenance_hold_request(self) -> str | None:
        command_id = self._take(CollectorCommandKind.MAINTENANCE_HOLD)
        if command_id is not None:
            with self._lock:
                self._hold_state = CollectorHoldState.SEALING
        return command_id

    def complete_maintenance_hold(
        self,
        command_id: str,
        result: dict[str, Any],
    ) -> bool:
        completed = self._complete(
            command_id,
            CollectorCommandKind.MAINTENANCE_HOLD,
            result,
            terminal_state=CollectorHoldState.HELD,
        )
        if completed:
            with self._lock:
                self._hold_state = CollectorHoldState.HELD
        return completed

    def request_reset(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
        with self._lock:
            if self._hold_state is not CollectorHoldState.HELD:
                return self._state_conflict(CollectorCommandKind.DATABASE_RESET)
            self._hold_state = CollectorHoldState.RESETTING
        result = self._request(CollectorCommandKind.DATABASE_RESET, timeout_seconds)
        if not bool(result.get("ok")) and not bool(result.get("command_state_unknown")):
            with self._lock:
                self._hold_state = CollectorHoldState.HELD
        return result

    def take_reset_request(self) -> str | None:
        return self._take(CollectorCommandKind.DATABASE_RESET)

    def complete_reset(self, command_id: str, result: dict[str, Any]) -> bool:
        completed = self._complete(
            command_id,
            CollectorCommandKind.DATABASE_RESET,
            result,
            terminal_state=CollectorHoldState.HELD,
        )
        if completed:
            with self._lock:
                self._hold_state = CollectorHoldState.HELD
        return completed

    def request_maintenance_release(
        self,
        timeout_seconds: float = 5.0,
    ) -> dict[str, Any]:
        with self._lock:
            if self._hold_state is CollectorHoldState.OPERATIONAL:
                return self._synthetic_completed(
                    CollectorCommandKind.MAINTENANCE_RELEASE,
                    CollectorHoldState.OPERATIONAL,
                    already_released=True,
                )
            if self._hold_state is not CollectorHoldState.HELD:
                return self._state_conflict(CollectorCommandKind.MAINTENANCE_RELEASE)
            self._hold_state = CollectorHoldState.RELEASE_REQUESTED
        result = self._request(CollectorCommandKind.MAINTENANCE_RELEASE, timeout_seconds)
        if not bool(result.get("ok")) and not bool(result.get("command_state_unknown")):
            with self._lock:
                self._hold_state = CollectorHoldState.HELD
        return result

    def take_maintenance_release_request(self) -> str | None:
        return self._take(CollectorCommandKind.MAINTENANCE_RELEASE)

    def complete_maintenance_release(
        self,
        command_id: str,
        result: dict[str, Any],
    ) -> bool:
        completed = self._complete(
            command_id,
            CollectorCommandKind.MAINTENANCE_RELEASE,
            result,
            terminal_state=CollectorHoldState.OPERATIONAL,
        )
        if completed:
            with self._lock:
                self._hold_state = CollectorHoldState.OPERATIONAL
        return completed

    def query_command(self, command_id: str) -> dict[str, Any] | None:
        with self._lock:
            command = self._commands.get(str(command_id or ""))
            if command is None:
                return None
            if command.state is CollectorCommandState.COMPLETED:
                return dict(command.result)
            return self._command_status(command, ok=False)

    def _request(
        self,
        kind: CollectorCommandKind,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        command = _CollectorCommand(command_id=uuid.uuid4().hex, kind=kind)
        with self._lock:
            previous_id = self._pending_ids.get(kind)
            previous = self._commands.get(previous_id or "")
            if previous is not None and previous.state is CollectorCommandState.PENDING:
                return {
                    **self._command_status(previous, ok=False),
                    "error": "command_already_pending",
                }
            command.result = self._command_status(command, ok=False)
            self._commands[command.command_id] = command
            self._pending_ids[kind] = command.command_id
            self._wake_event.set()

        if command.done_event.wait(max(0.0, float(timeout_seconds))):
            with self._lock:
                return dict(command.result)

        with self._lock:
            if command.state is CollectorCommandState.COMPLETED:
                return dict(command.result)
            if command.state is CollectorCommandState.PENDING:
                command.state = CollectorCommandState.CANCELLED
                self._pending_ids.pop(kind, None)
                self._refresh_wake_event_locked()
                return {
                    **self._command_status(command, ok=False),
                    "timed_out": True,
                }
            if command.state is CollectorCommandState.TAKEN:
                command.state = CollectorCommandState.UNKNOWN
            return {
                **self._command_status(command, ok=False),
                "timed_out": True,
            }

    def _take(self, kind: CollectorCommandKind) -> str | None:
        with self._lock:
            command_id = self._pending_ids.get(kind)
            command = self._commands.get(command_id or "")
            if command is None or command.state is not CollectorCommandState.PENDING:
                self._pending_ids.pop(kind, None)
                self._refresh_wake_event_locked()
                return None
            command.state = CollectorCommandState.TAKEN
            self._pending_ids.pop(kind, None)
            self._refresh_wake_event_locked()
            return command.command_id

    def _complete(
        self,
        command_id: str,
        kind: CollectorCommandKind,
        result: dict[str, Any],
        *,
        terminal_state: CollectorHoldState,
    ) -> bool:
        with self._lock:
            command = self._commands.get(str(command_id or ""))
            if command is None or command.kind is not kind:
                return False
            if command.state not in {
                CollectorCommandState.TAKEN,
                CollectorCommandState.UNKNOWN,
            }:
                return False
            command.state = CollectorCommandState.COMPLETED
            command.result = {
                **dict(result),
                **self._command_status(command, ok=bool(result.get("ok"))),
                "terminal_state": terminal_state.value,
            }
            command.done_event.set()
            return True

    def _synthetic_completed(
        self,
        kind: CollectorCommandKind,
        terminal_state: CollectorHoldState,
        **values: Any,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "command_id": f"synthetic-{uuid.uuid4().hex}",
            "command_kind": kind.value,
            "command_state": CollectorCommandState.COMPLETED.value,
            "command_state_unknown": False,
            "terminal_state": terminal_state.value,
            **values,
        }

    def _state_conflict(self, kind: CollectorCommandKind) -> dict[str, Any]:
        return {
            "ok": False,
            "command_id": "",
            "command_kind": kind.value,
            "command_state": CollectorCommandState.CANCELLED.value,
            "command_state_unknown": False,
            "terminal_state": self._hold_state.value,
            "error": "collector_command_state_conflict",
        }

    @staticmethod
    def _command_status(command: _CollectorCommand, *, ok: bool) -> dict[str, Any]:
        return {
            "ok": bool(ok),
            "command_id": command.command_id,
            "command_kind": command.kind.value,
            "command_state": command.state.value,
            "command_state_unknown": command.state is CollectorCommandState.UNKNOWN,
        }

    def _refresh_wake_event_locked(self) -> None:
        if self._pending_ids:
            self._wake_event.set()
        else:
            self._wake_event.clear()

    def wait(self, stop_event: threading.Event, timeout_seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while not stop_event.is_set():
            if self._wake_event.wait(timeout=0.1):
                return
            if time.monotonic() >= deadline:
                return


def run_collector(
    adapter: PlatformAdapter,
    stop_event: threading.Event,
    control: CollectorControl | None = None,
    startup_ready_event: threading.Event | None = None,
    startup_failed_event: threading.Event | None = None,
) -> None:
    """Run collection with explicit startup and maintenance-hold handshakes."""

    try:
        machine = CollectorStateMachine()
        clock_tracker = ClockTracker()
        last_loop_time: str | None = None
        heartbeat_counter = 0
        prune_counter = 0
        fatal_stop = False
        held = False
        logging.info("collector start")
        collector_health.record_collector_started(now_str())
        _normalize_poll_interval_setting()
        _run_clipboard_maintenance_tick()
        next_poll_deadline = time.monotonic() + POLL_CADENCE_SECONDS
    except Exception as exc:
        disposition = classify_collector_failure(exc)
        collector_health.record_fatal_failure("startup", disposition.code, now_str())
        collector_health.record_collector_stopped(now_str())
        if startup_failed_event is not None:
            startup_failed_event.set()
        logging.error(
            "collector startup initialization failed code=%s",
            disposition.code.value,
        )
        return

    if startup_ready_event is not None:
        startup_ready_event.set()

    while not stop_event.is_set():
        phase = "loop"
        try:
            now = now_str()

            if held:
                reset_command_id = (
                    control.take_reset_request() if control is not None else None
                )
                if reset_command_id is not None:
                    phase = "database_reset"
                    _set_clipboard_capture_enabled(adapter, False)
                    machine.reset_runtime_state("database_generation_changed")
                    control.complete_reset(
                        reset_command_id,
                        {"ok": True, "reset_pending": False},
                    )
                    last_loop_time = now
                    continue

                release_command_id = (
                    control.take_maintenance_release_request()
                    if control is not None
                    else None
                )
                if release_command_id is not None:
                    phase = "maintenance_release"
                    held = False
                    control.complete_maintenance_release(
                        release_command_id,
                        {"ok": True, "release_pending": False},
                    )
                    last_loop_time = None
                    next_poll_deadline = time.monotonic() + POLL_CADENCE_SECONDS
                    continue

                _set_clipboard_capture_enabled(adapter, False)
                _wait_for_poll_delay(stop_event, control, POLL_CADENCE_SECONDS)
                continue

            hold_command_id = (
                control.take_maintenance_hold_request()
                if control is not None
                else None
            )
            if hold_command_id is not None:
                phase = "maintenance_hold"
                _set_clipboard_capture_enabled(adapter, False)
                machine.quiesce_for_maintenance(at_time=now)
                held = True
                control.complete_maintenance_hold(
                    hold_command_id,
                    {"ok": True, "hold_pending": False},
                )
                last_loop_time = now
                continue

            pause_command_id = (
                control.take_pause_request() if control is not None else None
            )
            if pause_command_id is not None:
                phase = "user_pause"
                _set_clipboard_capture_enabled(adapter, False)
                _pause_machine_then_expose(machine, now)
                control.complete_pause(
                    pause_command_id,
                    {"ok": True, "pause_pending": False},
                )
                last_loop_time = now
                next_poll_deadline = _sleep_until_next_poll(
                    stop_event,
                    control,
                    next_poll_deadline,
                )
                continue

            monotonic_now = time.monotonic()
            phase = "gate_check"
            idle_threshold_seconds = get_int_setting(
                "idle_threshold_seconds",
                DEFAULT_IDLE_THRESHOLD_SECONDS,
            )
            discontinuity = clock_tracker.observe(
                now,
                monotonic_now,
                clock_jump_threshold_seconds=get_int_setting(
                    "clock_jump_threshold_seconds",
                    300,
                ),
                stall_threshold_seconds=get_int_setting(
                    "collector_stall_threshold_seconds",
                    180,
                ),
            )
            if discontinuity is not None:
                _set_clipboard_capture_enabled(adapter, False)
                clock_tracker.apply_discontinuity(machine, discontinuity)
                collector_health.record_health_code(discontinuity.reason, now)
                last_loop_time = now
                next_poll_deadline = monotonic_now + POLL_CADENCE_SECONDS
                continue

            prune_counter += 1
            if prune_counter >= 20:
                _run_clipboard_maintenance_tick()
                prune_counter = 0

            if last_loop_time:
                midnight = _midnight_crossed_between(last_loop_time, now)
                if midnight is not None:
                    machine.split_at_midnight(midnight)

            phase = "heartbeat"
            heartbeat_counter += 1
            if heartbeat_counter == 1 or heartbeat_counter >= 4:
                update_heartbeat("running")
                heartbeat_counter = 0

            if not privacy_gate_service.is_sensitive_runtime_allowed():
                _set_clipboard_capture_enabled(adapter, False)
                _pause_machine_then_expose(machine, now)
                next_poll_deadline = _sleep_until_next_poll(
                    stop_event,
                    control,
                    next_poll_deadline,
                )
                last_loop_time = now
                continue

            if get_bool_setting("user_paused", False):
                _set_clipboard_capture_enabled(adapter, False)
                _pause_machine_then_expose(machine, now)
                next_poll_deadline = _sleep_until_next_poll(
                    stop_event,
                    control,
                    next_poll_deadline,
                )
                last_loop_time = now
                continue

            phase = "active_window"
            active_window = adapter.get_active_window()
            observation_time = now_str()
            phase = "clipboard"
            capture_enabled = clipboard_service.is_capture_enabled()
            _set_clipboard_capture_enabled(adapter, capture_enabled)
            clipboard_events = _clipboard_events(adapter) if capture_enabled else []
            phase = "idle"
            idle_seconds = adapter.get_idle_seconds()
            idle_threshold = max(1, idle_threshold_seconds)

            phase = "transition"
            if idle_seconds >= idle_threshold:
                machine.transition_to("idle", at_time=observation_time)
            else:
                phase = "privacy"
                decision = privacy_service.evaluate_exclusion(active_window)
                if decision.refresh_required:
                    folder_index_service.request_refresh_for_enabled_rules(
                        include_excluded=True
                    )
                if decision.resolution_pending:
                    collector_health.record_health_code(
                        "privacy_resolution_pending",
                        observation_time,
                    )
                phase = "transition"
                if decision.excluded:
                    machine.transition_to("excluded", at_time=observation_time)
                else:
                    machine.transition_to(
                        "recording",
                        active_window,
                        at_time=observation_time,
                    )
                    for event in clipboard_events:
                        machine.record_clipboard_event(
                            event,
                            at_time=observation_time,
                        )
            collector_health.record_successful_observation(observation_time)
            last_loop_time = observation_time
            next_poll_deadline = _sleep_until_next_poll(
                stop_event,
                control,
                next_poll_deadline,
            )
        except Exception as exc:
            disposition = classify_collector_failure(exc)
            if not disposition.retryable:
                collector_health.record_fatal_failure(
                    phase,
                    disposition.code,
                    now_str(),
                )
                fatal_stop = True
                break
            collector_health.record_transient_failure(
                phase,
                disposition.code,
                now_str(),
            )
            logging.exception(
                "collector transient failure phase=%s code=%s",
                phase,
                disposition.code.value,
            )
            # Best-effort fail-closed: stop sensitive clipboard capture before
            # the retry sleep so a transient failure cannot keep the clipboard
            # monitor producing observations while the collector is degraded.
            try:
                _set_clipboard_capture_enabled(adapter, False)
            except Exception as clip_exc:
                clip_disposition = classify_collector_failure(clip_exc)
                if not clip_disposition.retryable:
                    collector_health.record_fatal_failure(
                        "clipboard_fail_closed",
                        clip_disposition.code,
                        now_str(),
                    )
                    fatal_stop = True
                    break
            next_poll_deadline = _sleep_until_next_poll(
                stop_event,
                control,
                next_poll_deadline,
            )

    try:
        _set_clipboard_capture_enabled(adapter, False)
    except Exception as exc:
        disposition = classify_collector_failure(exc)
        collector_health.record_fatal_failure(
            "clipboard_shutdown",
            disposition.code,
            now_str(),
        )
    try:
        if held:
            machine.reset_runtime_state("shutdown_during_maintenance_hold")
        elif fatal_stop:
            machine.stop(at_time=now_str(), reason="fatal_collector_stop")
        else:
            machine.transition_to("stopped", at_time=now_str())
    finally:
        collector_health.record_collector_stopped(now_str())
    logging.info("collector stop")


def _normalize_poll_interval_setting() -> None:
    raw = get_setting("poll_interval_seconds", "1") or "1"
    try:
        value = int(str(raw).strip())
    except ValueError:
        value = 0
    if value != 1:
        set_setting("poll_interval_seconds", "1")


def _pause_machine_then_expose(
    machine: CollectorStateMachine,
    at_time: str,
) -> None:
    machine.pause(at_time=at_time)
    update_heartbeat("paused")


def _run_clipboard_maintenance_tick() -> None:
    """Run bounded optional retention maintenance without blocking collection."""

    try:
        clipboard_service.prune_old_events()
    except Exception as exc:
        disposition = classify_collector_failure(exc)
        collector_health.record_transient_failure(
            "clipboard_maintenance",
            disposition.code,
            now_str(),
        )


def _wait_for_poll_delay(
    stop_event: threading.Event,
    control: CollectorControl | None,
    timeout_seconds: float,
) -> None:
    if control is not None:
        control.wait(stop_event, timeout_seconds)
        return
    stop_event.wait(timeout_seconds)


def _sleep_until_next_poll(
    stop_event: threading.Event,
    control: CollectorControl | None,
    next_poll_deadline: float,
    *,
    monotonic_func: Callable[[], float] = time.monotonic,
    wait_func: Callable[
        [threading.Event, CollectorControl | None, float],
        None,
    ] = _wait_for_poll_delay,
) -> float:
    now = monotonic_func()
    delay = float(next_poll_deadline) - now
    if delay > 0:
        wait_func(stop_event, control, delay)
        return float(next_poll_deadline) + POLL_CADENCE_SECONDS
    if delay <= -POLL_CADENCE_SECONDS:
        logging.debug(
            "collector missed one or more intervals by %.3fs; rebasing",
            abs(delay),
        )
        return float(now) + POLL_CADENCE_SECONDS
    logging.debug("collector loop exceeded cadence by %.3fs", abs(delay))
    return float(next_poll_deadline) + POLL_CADENCE_SECONDS


def _sleep_poll(
    stop_event: threading.Event,
    control: CollectorControl | None = None,
) -> None:
    interval = max(1, get_int_setting("poll_interval_seconds", 1))
    _wait_for_poll_delay(stop_event, control, float(interval))


def _set_clipboard_capture_enabled(
    adapter: PlatformAdapter,
    enabled: bool,
) -> None:
    try:
        adapter.set_clipboard_capture_enabled(bool(enabled))
    except Exception as exc:
        disposition = classify_collector_failure(exc)
        if not disposition.retryable:
            raise
        collector_health.record_transient_failure(
            "clipboard_lifecycle",
            disposition.code,
            now_str(),
        )


def _clipboard_events(adapter: PlatformAdapter):
    try:
        return adapter.get_clipboard_events()
    except Exception as exc:
        disposition = classify_collector_failure(exc)
        if not disposition.retryable:
            raise
        collector_health.record_transient_failure(
            "clipboard",
            disposition.code,
            now_str(),
        )
        return []


def _midnight_crossed_between(previous: str, current: str) -> str | None:
    try:
        previous_dt = datetime.strptime(previous, TIME_FORMAT)
        current_dt = datetime.strptime(current, TIME_FORMAT)
    except ValueError:
        return None
    if current_dt <= previous_dt or current_dt.date() <= previous_dt.date():
        return None
    midnight = datetime.combine(current_dt.date(), datetime_time.min)
    if previous_dt < midnight <= current_dt:
        return midnight.strftime(TIME_FORMAT)
    return None


__all__ = [
    "CollectorCommandKind",
    "CollectorCommandState",
    "CollectorControl",
    "CollectorHoldState",
    "run_collector",
]
