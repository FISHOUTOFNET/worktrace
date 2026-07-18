from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime

from ..constants import TIME_FORMAT
from ..db import get_db_path, now_str
from ..services.settings_service import get_int_setting, get_setting, set_settings

HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_FAILING = "failing"
HEALTH_STOPPED = "stopped"

_FAILING_THRESHOLD = 3
_SUCCESS_PERSIST_INTERVAL_SECONDS = 30
_STATE_LOCK = threading.RLock()


class TransientCollectorError(RuntimeError):
    """Explicit adapter or runtime signal that retrying the loop is safe."""


@dataclass
class _RuntimeHealthState:
    health_state: str
    failures: int
    last_failure_at: str
    last_success_persisted_at: str


_STATE_BY_DATABASE: dict[str, _RuntimeHealthState] = {}


def _database_key() -> str:
    return str(get_db_path().resolve())


def _runtime_state() -> _RuntimeHealthState:
    key = _database_key()
    with _STATE_LOCK:
        state = _STATE_BY_DATABASE.get(key)
        if state is None:
            state = _RuntimeHealthState(
                health_state=get_setting(
                    "collector_health_state",
                    HEALTH_STOPPED,
                )
                or HEALTH_STOPPED,
                failures=get_int_setting("collector_consecutive_failures", 0),
                last_failure_at=get_setting("collector_last_failure_at", "") or "",
                last_success_persisted_at=get_setting(
                    "collector_last_successful_observation_at",
                    "",
                )
                or "",
            )
            _STATE_BY_DATABASE[key] = state
        return state


def _elapsed_seconds(start: str, end: str) -> int | None:
    if not start or not end:
        return None
    try:
        return int(
            (
                datetime.strptime(end, TIME_FORMAT)
                - datetime.strptime(start, TIME_FORMAT)
            ).total_seconds()
        )
    except (TypeError, ValueError):
        return None


def record_collector_started(at_time: str | None = None) -> None:
    state = _runtime_state()
    with _STATE_LOCK:
        state.health_state = HEALTH_HEALTHY
        state.failures = 0
    set_settings(
        {
            "collector_status": "running",
            "collector_health_state": HEALTH_HEALTHY,
            "collector_consecutive_failures": "0",
        }
    )
    logging.info("collector health state=healthy phase=start")


def record_successful_observation(at_time: str | None = None) -> None:
    at = at_time or now_str()
    state = _runtime_state()
    with _STATE_LOCK:
        recovered = (
            state.health_state in (HEALTH_DEGRADED, HEALTH_FAILING)
            or state.failures > 0
        )
        previous_failure_at = state.last_failure_at
        elapsed = _elapsed_seconds(state.last_success_persisted_at, at)
        should_persist = bool(
            recovered
            or elapsed is None
            or elapsed < 0
            or elapsed >= _SUCCESS_PERSIST_INTERVAL_SECONDS
        )
        state.health_state = HEALTH_HEALTHY
        state.failures = 0
        if should_persist:
            state.last_success_persisted_at = at

    if not should_persist:
        return

    values = {
        "collector_health_state": HEALTH_HEALTHY,
        "collector_last_successful_observation_at": at,
        "collector_consecutive_failures": "0",
        "collector_last_failure_phase": "",
        "collector_last_failure_kind": "",
    }
    if recovered:
        values["collector_last_recovery_at"] = at
        values["collector_last_recovery_failure_at"] = previous_failure_at
    set_settings(values)


def record_transient_failure(
    phase: str,
    exc: BaseException,
    at_time: str | None = None,
) -> None:
    at = at_time or now_str()
    state = _runtime_state()
    with _STATE_LOCK:
        state.failures += 1
        state.health_state = (
            HEALTH_FAILING
            if state.failures >= _FAILING_THRESHOLD
            else HEALTH_DEGRADED
        )
        state.last_failure_at = at
        failures = state.failures
        health_state = state.health_state
    set_settings(
        {
            "collector_health_state": health_state,
            "collector_last_failure_at": at,
            "collector_consecutive_failures": str(failures),
            "collector_last_failure_phase": _safe_phase(phase),
            "collector_last_failure_kind": type(exc).__name__,
        }
    )
    logging.warning(
        "collector transient failure phase=%s kind=%s consecutive=%s",
        _safe_phase(phase),
        type(exc).__name__,
        failures,
    )


def record_fatal_failure(
    phase: str,
    exc: BaseException,
    at_time: str | None = None,
) -> None:
    at = at_time or now_str()
    state = _runtime_state()
    with _STATE_LOCK:
        state.health_state = HEALTH_STOPPED
        state.last_failure_at = at
    set_settings(
        {
            "collector_health_state": HEALTH_STOPPED,
            "collector_last_failure_at": at,
            "collector_last_failure_phase": _safe_phase(phase),
            "collector_last_failure_kind": type(exc).__name__,
        }
    )
    logging.error(
        "collector fatal failure phase=%s kind=%s",
        _safe_phase(phase),
        type(exc).__name__,
    )


def record_collector_stopped(at_time: str | None = None) -> None:
    state = _runtime_state()
    with _STATE_LOCK:
        state.health_state = HEALTH_STOPPED
    set_settings(
        {
            "collector_status": "stopped",
            "collector_health_state": HEALTH_STOPPED,
            "last_shutdown_at": at_time or now_str(),
        }
    )
    logging.info("collector health state=stopped")


def reset_collector_failures() -> None:
    state = _runtime_state()
    with _STATE_LOCK:
        state.failures = 0
    set_settings({"collector_consecutive_failures": "0"})


def record_health_code(code: str, at_time: str | None = None) -> None:
    at = at_time or now_str()
    state = _runtime_state()
    with _STATE_LOCK:
        state.last_failure_at = at
    set_settings(
        {
            "collector_last_failure_at": at,
            "collector_last_failure_phase": "runtime",
            "collector_last_failure_kind": str(code or "runtime_event"),
        }
    )
    logging.info("collector health code=%s", str(code or "runtime_event"))


def is_transient_failure(exc: BaseException) -> bool:
    """Return true only for failures explicitly proven safe to retry.

    Unknown exceptions are programming or contract failures by default. This
    prevents deterministic ``ValueError``/``RuntimeError``/``IndexError`` defects
    from being converted into an endless degraded Collector loop.
    """

    if isinstance(exc, TransientCollectorError):
        return True
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, sqlite3.DatabaseError):
        message = str(exc).lower()
        return any(
            token in message
            for token in (
                "locked",
                "busy",
                "secure_import_in_progress",
                "database_generation_changed",
            )
        )
    return False


def _safe_phase(phase: str) -> str:
    value = str(phase or "unknown").strip()
    return value if value else "unknown"


def format_time(value: datetime | str | None = None) -> str:
    if isinstance(value, datetime):
        return value.strftime(TIME_FORMAT)
    return str(value or now_str())


__all__ = [
    "HEALTH_DEGRADED",
    "HEALTH_FAILING",
    "HEALTH_HEALTHY",
    "HEALTH_STOPPED",
    "TransientCollectorError",
    "format_time",
    "is_transient_failure",
    "record_collector_started",
    "record_collector_stopped",
    "record_fatal_failure",
    "record_health_code",
    "record_successful_observation",
    "record_transient_failure",
    "reset_collector_failures",
]
