from __future__ import annotations

import logging
import threading
from datetime import datetime, time as datetime_time

from ..constants import TIME_FORMAT
from ..db import now_str
from ..platforms.base import PlatformAdapter
from ..services import privacy_service, recovery_service
from ..services.settings_service import get_bool_setting, get_int_setting, set_setting
from .heartbeat import update_heartbeat
from .state_machine import CollectorStateMachine


def run_collector(adapter: PlatformAdapter, stop_event: threading.Event) -> None:
    machine = CollectorStateMachine()
    last_loop_time: str | None = None
    heartbeat_counter = 0
    logging.info("collector start")
    set_setting("collector_status", "running")
    recovery_service.recover_unclosed_records()

    while not stop_event.is_set():
        try:
            now = now_str()
            idle_threshold_seconds = get_int_setting("idle_threshold_seconds", 300)
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

            if not get_bool_setting("first_run_notice_accepted", False):
                set_setting("collector_status", "paused")
                machine.pause(at_time=now)
                _sleep_poll(stop_event)
                last_loop_time = now
                continue

            if get_bool_setting("user_paused", False):
                set_setting("collector_status", "paused")
                machine.pause(at_time=now)
                _sleep_poll(stop_event)
                last_loop_time = now
                continue

            active_window = adapter.get_active_window()
            idle_seconds = adapter.get_idle_seconds()
            idle_threshold = max(1, idle_threshold_seconds)

            if idle_seconds >= idle_threshold:
                machine.transition_to("idle", at_time=now)
            elif privacy_service.is_excluded(active_window):
                machine.transition_to("excluded", at_time=now)
            else:
                machine.transition_to("recording", active_window, at_time=now)
            last_loop_time = now
            _sleep_poll(stop_event)
        except Exception:
            logging.exception("collector unexpected exception")
            set_setting("collector_status", "error")
            try:
                machine.transition_to("error", at_time=now_str())
            except Exception:
                logging.exception("failed to persist collector error state")
            _sleep_poll(stop_event)

    machine.transition_to("stopped", at_time=now_str())
    set_setting("collector_status", "stopped")
    set_setting("last_shutdown_at", now_str())
    logging.info("collector stop")


def _sleep_poll(stop_event: threading.Event) -> None:
    interval = max(1, get_int_setting("poll_interval_seconds", 3))
    stop_event.wait(interval)


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
