from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime

from ..constants import TIME_FORMAT
from ..db import active_database_epoch_key, now_str
from ..services.settings_service import get_int_setting, get_setting, set_settings
from .collector_failure_policy import (
    RETRYABLE_COLLECTOR_FAILURE_CODES,
    CollectorFailureCode,
)

HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_FAILING = "failing"
HEALTH_STOPPED = "stopped"

_FAILING_THRESHOLD = 3
_SUCCESS_PERSIST_INTERVAL_SECONDS = 30
_STATE_LOCK = threading.RLock()
_SAFE_CODE_PATTERN = re.compile(r"[^a-z0-9_]+")


@dataclass
class _RuntimeHealthState:
    health_state: str
    failures: int
    last_failure_at: str
    last_success_persisted_at: str


_STATE_BY_DATABASE: dict[tuple[str, int], _RuntimeHealthState] = {}


def _runtime_state() -> _RuntimeHealthState:
    key = active_database_epoch_key()
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
    code: CollectorFailureCode,
    at_time: str | None = None,
) -> None:
    safe_code = _safe_failure_code(code)
    if code not in RETRYABLE_COLLECTOR_FAILURE_CODES:
        raise ValueError("collector_failure_code_not_retryable")
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
            "collector_last_failure_kind": safe_code,
        }
    )
    logging.warning(
        "collector transient failure phase=%s code=%s consecutive=%s",
        _safe_phase(phase),
        safe_code,
        failures,
    )


def record_fatal_failure(
    phase: str,
    code: CollectorFailureCode,
    at_time: str | None = None,
) -> None:
    safe_code = _safe_failure_code(code)
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
            "collector_last_failure_kind": safe_code,
        }
    )
    logging.error(
        "collector fatal failure phase=%s code=%s",
        _safe_phase(phase),
        safe_code,
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
    safe_code = _safe_health_code(code)
    state = _runtime_state()
    with _STATE_LOCK:
        state.last_failure_at = at
    set_settings(
        {
            "collector_last_failure_at": at,
            "collector_last_failure_phase": "runtime",
            "collector_last_failure_kind": safe_code,
        }
    )
    logging.info("collector health code=%s", safe_code)


def _safe_phase(phase: str) -> str:
    value = str(phase or "unknown").strip().lower()
    normalized = _SAFE_CODE_PATTERN.sub("_", value).strip("_")
    return (normalized or "unknown")[:64]


def _safe_failure_code(code: CollectorFailureCode) -> str:
    if not isinstance(code, CollectorFailureCode):
        raise TypeError("collector_failure_code_required")
    return code.value


def _safe_health_code(code: str) -> str:
    value = str(code or "").strip().lower()
    normalized = _SAFE_CODE_PATTERN.sub("_", value).strip("_")
    return (normalized or CollectorFailureCode.UNEXPECTED_FAILURE.value)[:64]


def format_time(value: datetime | str | None = None) -> str:
    if isinstance(value, datetime):
        return value.strftime(TIME_FORMAT)
    return str(value or now_str())


__all__ = [
    "HEALTH_DEGRADED",
    "HEALTH_FAILING",
    "HEALTH_HEALTHY",
    "HEALTH_STOPPED",
    "format_time",
    "record_collector_started",
    "record_collector_stopped",
    "record_fatal_failure",
    "record_health_code",
    "record_successful_observation",
    "record_transient_failure",
    "reset_collector_failures",
]
