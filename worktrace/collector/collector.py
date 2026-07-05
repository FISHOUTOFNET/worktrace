from __future__ import annotations

import logging
import threading
from datetime import datetime, time as datetime_time
from typing import Any

from ..constants import DEFAULT_IDLE_THRESHOLD_SECONDS, TIME_FORMAT
from ..db import now_str
from ..platforms.base import PlatformAdapter
from ..services import clipboard_service, privacy_service, recovery_service
from ..services.secure_backup_service import is_secure_import_in_progress
from ..services.settings_service import get_bool_setting, get_int_setting, get_setting, set_setting
from .heartbeat import update_heartbeat
from .state_machine import CollectorStateMachine


class CollectorControl:
    """Small command channel owned by the runtime and consumed by collector."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self._pause_requested = False
        self._pause_done = threading.Event()
        self._pause_result: dict[str, Any] = {"ok": False, "pause_pending": False}

    def request_pause(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
        with self._lock:
            self._pause_requested = True
            self._pause_done.clear()
            self._pause_result = {"ok": False, "pause_pending": True}
            self._wake_event.set()
        if not self._pause_done.wait(timeout_seconds):
            return {"ok": False, "pause_pending": True}
        with self._lock:
            return dict(self._pause_result)

    def take_pause_request(self) -> bool:
        with self._lock:
            if not self._pause_requested:
                return False
            self._pause_requested = False
            self._wake_event.clear()
            return True

    def complete_pause(self, result: dict[str, Any]) -> None:
        with self._lock:
            self._pause_result = dict(result)
            self._pause_done.set()

    def wait(self, stop_event: threading.Event, timeout_seconds: float) -> None:
        deadline = datetime.now().timestamp() + max(0.0, timeout_seconds)
        while not stop_event.is_set():
            if self._wake_event.wait(timeout=0.1):
                return
            if datetime.now().timestamp() >= deadline:
                return


def run_collector(
    adapter: PlatformAdapter,
    stop_event: threading.Event,
    control: CollectorControl | None = None,
) -> None:
    machine = CollectorStateMachine()
    last_loop_time: str | None = None
    heartbeat_counter = 0
    prune_counter = 0
    logging.info("collector start")
    set_setting("collector_status", "running")
    _normalize_poll_interval_setting()
    recovery_service.recover_unclosed_records()
    clipboard_service.prune_old_events()

    while not stop_event.is_set():
        try:
            now = now_str()
            idle_threshold_seconds = get_int_setting("idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD_SECONDS)
            if last_loop_time and recovery_service.detect_time_jump(last_loop_time, now, idle_threshold_seconds):
                machine.reset_for_time_jump(last_loop_time)
            elif last_loop_time:
                midnight = _midnight_crossed_between(last_loop_time, now)
                if midnight is not None:
                    machine.split_at_midnight(midnight)

            heartbeat_counter += 1
            if heartbeat_counter == 1 or heartbeat_counter >= 4:
                update_heartbeat("running")
                heartbeat_counter = 0

            if control is not None and control.take_pause_request():
                _pause_machine_then_expose(machine, now, set_user_paused=True)
                control.complete_pause({"ok": True, "pause_pending": False})
                _sleep_poll(stop_event, control)
                last_loop_time = now
                continue

            if not get_bool_setting("first_run_notice_accepted", False):
                _pause_machine_then_expose(machine, now)
                _sleep_poll(stop_event, control)
                last_loop_time = now
                continue

            if get_bool_setting("user_paused", False):
                _pause_machine_then_expose(machine, now)
                _sleep_poll(stop_event, control)
                last_loop_time = now
                continue

            if is_secure_import_in_progress():
                _pause_machine_then_expose(machine, now)
                _sleep_poll(stop_event, control)
                last_loop_time = now
                continue

            active_window = adapter.get_active_window()
            observation_time = now_str()
            clipboard_events = _clipboard_events(adapter) if clipboard_service.is_capture_enabled() else []
            idle_seconds = adapter.get_idle_seconds()
            idle_threshold = max(1, idle_threshold_seconds)

            if idle_seconds >= idle_threshold:
                machine.transition_to("idle", at_time=observation_time)
            elif privacy_service.is_excluded(active_window):
                machine.transition_to("excluded", at_time=observation_time)
            else:
                machine.transition_to("recording", active_window, at_time=observation_time)
                for event in clipboard_events:
                    machine.record_clipboard_event(event, at_time=observation_time)
            prune_counter += 1
            if prune_counter >= 20:
                clipboard_service.prune_old_events()
                prune_counter = 0
            last_loop_time = observation_time
            _sleep_poll(stop_event, control)
        except Exception:
            logging.exception("collector unexpected exception")
            set_setting("collector_status", "error")
            try:
                machine.transition_to("error", at_time=now_str())
            except Exception:
                logging.exception("failed to persist collector error state")
            _sleep_poll(stop_event, control)

    machine.transition_to("stopped", at_time=now_str())
    set_setting("collector_status", "stopped")
    set_setting("last_shutdown_at", now_str())
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


def _sleep_poll(stop_event: threading.Event, control: CollectorControl | None = None) -> None:
    interval = max(1, get_int_setting("poll_interval_seconds", 1))
    if control is not None:
        control.wait(stop_event, interval)
        return
    stop_event.wait(interval)


def _clipboard_events(adapter: PlatformAdapter):
    try:
        return adapter.get_clipboard_events()
    except AttributeError:
        return []
    except Exception:
        logging.debug("clipboard event polling failed", exc_info=True)
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
