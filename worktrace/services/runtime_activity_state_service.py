"""Runtime activity state cleanup owner.

This module owns cleanup of transient activity state stored outside
``activity_log``. It never deletes history rows or finalized activity data.
"""

from __future__ import annotations

import logging

from . import session_boundary_service
from .settings_service import clear_settings_cache, set_setting


PENDING_CARRY_PROVENANCE_KEY = "pending_short_carry_provenance"


def clear_runtime_activity_state(
    reason: str,
    *,
    clear_snapshot: bool = True,
    clear_pending: bool = True,
    clear_ownership: bool = True,
) -> None:
    """Clear transient activity state in an idempotent way."""
    if clear_snapshot:
        set_setting("current_activity_snapshot", "")
    if clear_pending:
        set_setting("pending_short_seconds", "0")
        set_setting(PENDING_CARRY_PROVENANCE_KEY, "")
    if clear_snapshot or clear_pending or clear_ownership:
        clear_settings_cache()
    logging.info(
        "runtime activity state cleared reason=%s snapshot=%s pending=%s ownership=%s",
        reason,
        bool(clear_snapshot),
        bool(clear_pending),
        bool(clear_ownership),
    )


def record_runtime_boundary(
    reason: str,
    *,
    clear_snapshot: bool = True,
    clear_pending: bool = True,
) -> None:
    """Record a hard runtime boundary and clear transient display carry."""
    session_boundary_service.record_boundary(reason=reason)
    clear_runtime_activity_state(
        reason,
        clear_snapshot=clear_snapshot,
        clear_pending=clear_pending,
        clear_ownership=True,
    )


__all__ = [
    "PENDING_CARRY_PROVENANCE_KEY",
    "clear_runtime_activity_state",
    "record_runtime_boundary",
]
