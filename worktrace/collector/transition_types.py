from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TypeAlias

from ..constants import TIME_FORMAT

ActivitySignature: TypeAlias = tuple[str, ...]


class ActivityEndReason(str, Enum):
    RESOURCE_SWITCH = "resource_switch"
    PAUSE_BOUNDARY = "pause_boundary"
    STOP_BOUNDARY = "stop_boundary"
    SHUTDOWN_BOUNDARY = "shutdown_boundary"
    TIME_JUMP_BOUNDARY = "time_jump_boundary"
    MIDNIGHT_BOUNDARY = "midnight_boundary"
    IDLE_BOUNDARY = "idle_boundary"
    EXCLUDED_BOUNDARY = "excluded_boundary"
    ERROR_BOUNDARY = "error_boundary"
    PRIVACY_BOUNDARY = "privacy_boundary"
    SECURE_IMPORT_BOUNDARY = "secure_import_boundary"
    FIRST_RUN_GATE_BOUNDARY = "first_run_gate_boundary"


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def seconds_between(start_time: str, end_time: str) -> int:
    return max(0, int((parse_time(end_time) - parse_time(start_time)).total_seconds()))
