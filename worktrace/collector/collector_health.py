from __future__ import annotations

import logging
from datetime import datetime

from ..db import now_str
from ..services.settings_service import get_int_setting, set_setting

HEALTH_HEALTHY = "healthy"
HEALTH_DEGRADED = "degraded"
HEALTH_FAILING = "failing"
HEALTH_STOPPED = "stopped"

_FAILING_THRESHOLD = 3


def record_collector_started(at_time: str | None = None) -> None:
    set_setting("collector_status", "running")
    set_setting("collector_health_state", HEALTH_HEALTHY)
    reset_collector_failures()
    logging.info("collector health state=healthy phase=start")


def record_successful_observation(at_time: str | None = None) -> None:
    at = at_time or now_str()
    set_setting("collector_health_state", HEALTH_HEALTHY)
    set_setting("collector_last_successful_observation_at", at)
    set_setting("collector_consecutive_failures", "0")
    set_setting("collector_last_failure_phase", "")
    set_setting("collector_last_failure_kind", "")


def record_transient_failure(phase: str, exc: BaseException, at_time: str | None = None) -> None:
    at = at_time or now_str()
    failures = get_int_setting("collector_consecutive_failures", 0) + 1
    state = HEALTH_FAILING if failures >= _FAILING_THRESHOLD else HEALTH_DEGRADED
    set_setting("collector_health_state", state)
    set_setting("collector_last_failure_at", at)
    set_setting("collector_consecutive_failures", str(failures))
    set_setting("collector_last_failure_phase", _safe_phase(phase))
    set_setting("collector_last_failure_kind", type(exc).__name__)
    logging.warning(
        "collector transient failure phase=%s kind=%s consecutive=%s",
        _safe_phase(phase),
        type(exc).__name__,
        failures,
    )


def record_fatal_failure(phase: str, exc: BaseException, at_time: str | None = None) -> None:
    at = at_time or now_str()
    set_setting("collector_health_state", HEALTH_STOPPED)
    set_setting("collector_last_failure_at", at)
    set_setting("collector_last_failure_phase", _safe_phase(phase))
    set_setting("collector_last_failure_kind", type(exc).__name__)
    logging.error(
        "collector fatal failure phase=%s kind=%s",
        _safe_phase(phase),
        type(exc).__name__,
    )


def record_collector_stopped(at_time: str | None = None) -> None:
    set_setting("collector_status", "stopped")
    set_setting("collector_health_state", HEALTH_STOPPED)
    set_setting("last_shutdown_at", at_time or now_str())
    logging.info("collector health state=stopped")


def reset_collector_failures() -> None:
    set_setting("collector_consecutive_failures", "0")


def record_health_code(code: str, at_time: str | None = None) -> None:
    set_setting("collector_last_failure_at", at_time or now_str())
    set_setting("collector_last_failure_phase", "runtime")
    set_setting("collector_last_failure_kind", str(code or "runtime_event"))
    logging.info("collector health code=%s", str(code or "runtime_event"))


def is_transient_failure(exc: BaseException) -> bool:
    return not isinstance(exc, (SystemExit, KeyboardInterrupt, MemoryError))


def _safe_phase(phase: str) -> str:
    value = str(phase or "unknown").strip()
    return value if value else "unknown"


def format_time(value: datetime | str | None = None) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value or now_str())


__all__ = [
    "HEALTH_DEGRADED",
    "HEALTH_FAILING",
    "HEALTH_HEALTHY",
    "HEALTH_STOPPED",
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
