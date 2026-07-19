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
    "fatal_collector_stop",
}

FORBIDDEN_TRANSIENT_REASONS = {
    "paused",
    "stopped",
    "time_jump",
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
    "secure_import",
    "clear_all",
    "maintenance_pause",
}


def normalize_hard_boundary_reason(reason: str) -> str:
    """Normalize whitespace only; current-only code accepts no reason aliases."""

    return str(reason or "").strip()


def is_allowed_hard_boundary_reason(reason: str) -> bool:
    return normalize_hard_boundary_reason(reason) in ALLOWED_HARD_BOUNDARY_REASONS


def validate_hard_boundary_reason(reason: str) -> str:
    normalized = normalize_hard_boundary_reason(reason)
    if (
        normalized in FORBIDDEN_TRANSIENT_REASONS
        or normalized not in ALLOWED_HARD_BOUNDARY_REASONS
    ):
        raise ValueError(f"invalid hard boundary reason: {reason}")
    return normalized


__all__ = [
    "ALLOWED_HARD_BOUNDARY_REASONS",
    "FORBIDDEN_TRANSIENT_REASONS",
    "is_allowed_hard_boundary_reason",
    "normalize_hard_boundary_reason",
    "validate_hard_boundary_reason",
]
