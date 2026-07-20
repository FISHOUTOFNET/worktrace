"""Durable fail-closed latch owned exclusively by database maintenance."""

from __future__ import annotations

from dataclasses import dataclass

from .settings_service import get_bool_setting, get_setting, set_settings


@dataclass(frozen=True)
class MaintenanceRecoveryLatch:
    blocked: bool
    reason: str | None


def read_latch() -> MaintenanceRecoveryLatch:
    blocked = get_bool_setting("maintenance_fail_closed", False)
    reason = str(get_setting("maintenance_fail_closed_reason", "") or "").strip()
    return MaintenanceRecoveryLatch(
        blocked=blocked,
        reason=reason or None,
    )


def persist_fail_closed(reason: str) -> None:
    normalized = str(reason or "").strip()
    if not normalized:
        raise ValueError("maintenance_recovery_reason_required")
    set_settings(
        {
            "maintenance_fail_closed": "true",
            "maintenance_fail_closed_reason": normalized,
            "user_paused": "true",
            "collector_status": "paused",
        }
    )


def clear_latch() -> None:
    set_settings(
        {
            "maintenance_fail_closed": "false",
            "maintenance_fail_closed_reason": "",
        }
    )


__all__ = [
    "MaintenanceRecoveryLatch",
    "clear_latch",
    "persist_fail_closed",
    "read_latch",
]
