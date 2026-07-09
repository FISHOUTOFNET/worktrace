from __future__ import annotations

ALLOWED_HARD_BOUNDARY_REASONS = {
    "user_pause",
    "pause_fallback",
    "user_stop",
    "shutdown",
    "restart",
    "recovered",
    "sleep_resume",
    "midnight",
    "secure_import",
    "clear_all",
    "fatal_collector_stop",
}

LEGACY_REASON_ALIASES = {
    "paused": "user_pause",
    "stopped": "user_stop",
    "time_jump": "sleep_resume",
}

FORBIDDEN_TRANSIENT_REASONS = {
    "transient_exception",
    "adapter_failure",
    "active_window_failure",
    "idle_poll_failure",
    "privacy_check_failure",
    "clipboard_failure",
    "db_busy",
    "ui_bridge_failure",
    "loop_overrun",
    "same_resource_stall_recovery",
    "collector_degraded",
    "collector_failing",
}


def normalize_hard_boundary_reason(reason: str) -> str:
    value = str(reason or "").strip()
    return LEGACY_REASON_ALIASES.get(value, value)


def is_allowed_hard_boundary_reason(reason: str) -> bool:
    return normalize_hard_boundary_reason(reason) in ALLOWED_HARD_BOUNDARY_REASONS


def validate_hard_boundary_reason(reason: str) -> str:
    normalized = normalize_hard_boundary_reason(reason)
    if normalized in FORBIDDEN_TRANSIENT_REASONS or normalized not in ALLOWED_HARD_BOUNDARY_REASONS:
        raise ValueError(f"invalid hard boundary reason: {reason}")
    return normalized


__all__ = [
    "ALLOWED_HARD_BOUNDARY_REASONS",
    "FORBIDDEN_TRANSIENT_REASONS",
    "LEGACY_REASON_ALIASES",
    "is_allowed_hard_boundary_reason",
    "normalize_hard_boundary_reason",
    "validate_hard_boundary_reason",
]
