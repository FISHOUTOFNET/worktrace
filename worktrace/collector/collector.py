from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, time as datetime_time
from typing import Any, Callable

from ..constants import DEFAULT_IDLE_THRESHOLD_SECONDS, TIME_FORMAT
from ..db import now_str
from ..platforms.base import PlatformAdapter
from ..services import clipboard_service, privacy_service
from ..services.secure_backup_service import is_secure_import_in_progress
from ..services.settings_service import (
    get_bool_setting,
    get_int_setting,
    get_setting,
    set_setting,
)
from . import collector_health
from .clock_tracker import ClockTracker
from .heartbeat import update_heartbeat
from .state_machine import CollectorStateMachine

POLL_CADENCE_SECONDS = 1.0


class CollectorControl:
    """Small cancellable command channel owned by the runtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self._pause_requested = False
        self._pause_done = threading.Event()
        self._pause_result: dict[str, Any] = {
            "ok": False,
            "pause_pending": False,
        }
        self._reset_requested = False
        self._reset_done = threading.Event()
        self._reset_result: dict[str, Any] = {
            "ok": False,
            "reset_pending": False,
        }

    def request_pause(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
        with self._lock:
            self._pause_requested = True
            self._pause_done.clear()
            self._pause_result = {"ok": False, "pause_pending": True}
            self._wake_event.set()
        if not self._pause_done.wait(timeout_seconds):
            with self._lock:
                self._pause_requested = False
                self._refresh_wake_event_locked()
            return {"ok": False, "pause_pending": False, "timed_out": True}
        with self._lock:
            return dict(self._pause_result)

    def take_pause_request(self) -> bool:
        with self._lock:
            if not self._pause_requested:
                return False
            self._pause_requested = False
            self._refresh_wake_event_locked()
            return True

    def complete_pause(self, result: dict[str, Any]) -> None:
        with self._lock:
            self._pause_result = dict(result)
            self._pause_done.set()

    def request_reset(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
        with self._lock:
            self._reset_requested = True
            self._reset_done.clear()
            self._reset_result = {"ok": False, "reset_pending": True}
            self._wake_event.set()
        if not self._reset_done.wait(timeout_seconds):
            with self._lock:
                self._reset_requested = False
                self._refresh_wake_event_locked()
            return {"ok": False, "reset_pending": False, "timed_out": True}
        with self._lock:
            return dict(self._reset_result)

    def take_reset_request(self) -> bool:
        with self._lock:
            if not self._reset_requested:
                return False
            self._reset_requested = False
            self._refresh_wake_event_locked()
            return True

    def complete_reset(self, result: dict[str, Any]) -> None:
        with self._lock:
            self._reset_result = dict(result)
            self._reset_done.set()

    def _refresh_wake_event_locked(self) -> None:
        if self._pause_requested or self._reset_requested:
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
) -> None:
    machine = CollectorStateMachine()
    clock_tracker = ClockTracker()
    last_loop_time: str | None = None
    heartbeat_counter = 0
    prune_counter = 0
    fatal_stop = False
    logging.info("collector start")
    collector_health.record_collector_started(now_str())
    _normalize_poll_interval_setting()
    clipboard_service.prune_old_events()
    next_poll_deadline = time.monotonic() + POLL_CADENCE_SECONDS

    while not stop_event.is_set():
        phase = "loop"
        try:
            now = now_str()
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

            maintenance_active = is_secure_import_in_progress()
            prune_counter += 1
            if prune_counter >= 20 and not maintenance_active:
                clipboard_service.prune_old_events()
                prune_counter = 0

            if control is not None and control.take_reset_request():
                _set_clipboard_capture_enabled(adapter, False)
                machine.reset_runtime_state("database_generation_changed")
                control.complete_reset({"ok": True, "reset_pending": False})
                next_poll_deadline = _sleep_until_next_poll(
                    stop_event,
                    control,
                    next_poll_deadline,
                )
                last_loop_time = now
                continue

            if last_loop_time:
                midnight = _midnight_crossed_between(last_loop_time, now)
                if midnight is not None:
                    machine.split_at_midnight(midnight)

            phase = "heartbeat"
            heartbeat_counter += 1
            if heartbeat_counter == 1 or heartbeat_counter >= 4:
                update_heartbeat("running")
                heartbeat_counter = 0

            phase = "gate_check"
            if control is not None and control.take_pause_request():
                _set_clipboard_capture_enabled(adapter, False)
                _pause_machine_then_expose(
                    machine,
                    now,
                    set_user_paused=True,
                )
                control.complete_pause({"ok": True, "pause_pending": False})
                next_poll_deadline = _sleep_until_next_poll(
                    stop_event,
                    control,
                    next_poll_deadline,
                )
                last_loop_time = now
                continue

            if not get_bool_setting("first_run_notice_accepted", False):
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

            if maintenance_active:
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
            clipboard_events = (
                _clipboard_events(adapter) if capture_enabled else []
            )
            phase = "idle"
            idle_seconds = adapter.get_idle_seconds()
            idle_threshold = max(1, idle_threshold_seconds)

            phase = "transition"
            if idle_seconds >= idle_threshold:
                machine.transition_to("idle", at_time=observation_time)
            else:
                phase = "privacy"
                try:
                    excluded = privacy_service.is_excluded(active_window)
                except privacy_service.PrivacyResolutionPending:
                    # When an exclusion folder exists but the active local path
                    # cannot be resolved, the safe observation is anonymous.
                    collector_health.record_health_code(
                        "privacy_resolution_pending",
                        observation_time,
                    )
                    phase = "transition"
                    machine.transition_to("excluded", at_time=observation_time)
                else:
                    phase = "transition"
                    if excluded:
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
            if not collector_health.is_transient_failure(exc):
                collector_health.record_fatal_failure(phase, exc, now_str())
                fatal_stop = True
                break
            collector_health.record_transient_failure(phase, exc, now_str())
            next_poll_deadline = _sleep_until_next_poll(
                stop_event,
                control,
                next_poll_deadline,
            )

    _set_clipboard_capture_enabled(adapter, False)
    try:
        if fatal_stop:
            machine.stop(
                at_time=now_str(),
                reason="fatal_collector_stop",
            )
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
    *,
    set_user_paused: bool = False,
) -> None:
    machine.pause(at_time=at_time)
    if set_user_paused:
        set_setting("user_paused", "true")
    set_setting("collector_status", "paused")
    update_heartbeat("paused")


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
    logging.debug(
        "collector loop exceeded cadence by %.3fs",
        abs(delay),
    )
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
    setter = getattr(adapter, "set_clipboard_capture_enabled", None)
    if setter is None:
        return
    try:
        setter(bool(enabled))
    except Exception as exc:
        collector_health.record_transient_failure(
            "clipboard_lifecycle",
            exc,
            now_str(),
        )


def _clipboard_events(adapter: PlatformAdapter):
    try:
        return adapter.get_clipboard_events()
    except AttributeError:
        return []
    except Exception as exc:
        collector_health.record_transient_failure("clipboard", exc, now_str())
        logging.debug(
            "clipboard event polling failed kind=%s",
            type(exc).__name__,
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
