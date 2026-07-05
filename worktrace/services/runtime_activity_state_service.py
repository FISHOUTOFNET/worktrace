"""Runtime activity state cleanup owner.

This module owns cleanup of transient activity state stored outside
``activity_log``. It never deletes history rows or finalized activity data.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..constants import STATUS_NORMAL
from ..db import now_str
from . import session_boundary_service
from .settings_service import clear_settings_cache, get_setting, set_setting


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


def _read_pending_short_seconds() -> int:
    raw = get_setting("pending_short_seconds", "0") or "0"
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def write_pending_short_carry(
    seconds: int,
    *,
    source_start_time: str,
    source_end_time: str,
) -> None:
    """Persist short-activity carry with minimal boundary provenance."""
    normalized = max(0, int(seconds))
    if normalized <= 0:
        clear_runtime_activity_state(
            "pending_carry_clear",
            clear_snapshot=False,
            clear_pending=True,
            clear_ownership=False,
        )
        return
    latest_boundary = session_boundary_service.latest_boundary_time() or ""
    prior = _load_pending_carry_provenance()
    prior_start = str(prior.get("source_start_time") or "")
    prior_end = str(prior.get("source_end_time") or "")
    prior_boundary = str(prior.get("latest_boundary_at_write") or "")
    if (
        prior.get("version") == 1
        and prior.get("source_status") == STATUS_NORMAL
        and prior_start
        and prior_end
        and prior_boundary == latest_boundary
        and prior_end <= str(source_start_time or "")
        and not session_boundary_service.has_boundary_between(prior_start, str(source_end_time or ""))
    ):
        source_start_time = prior_start
    provenance = {
        "version": 1,
        "source_status": STATUS_NORMAL,
        "source_start_time": str(source_start_time or ""),
        "source_end_time": str(source_end_time or ""),
        "latest_boundary_at_write": latest_boundary,
        "written_at": now_str(),
    }
    set_setting("pending_short_seconds", str(normalized))
    set_setting(PENDING_CARRY_PROVENANCE_KEY, json.dumps(provenance, sort_keys=True))


def _load_pending_carry_provenance() -> dict[str, Any]:
    raw = get_setting(PENDING_CARRY_PROVENANCE_KEY, "") or ""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def validate_pending_short_carry(
    *,
    current_start_time: str,
    current_status: str,
    pending_seconds: int | None = None,
) -> dict[str, Any]:
    """Validate that pending carry belongs to the current continuous session.

    The returned dict is display-safe and contains no resource/window data.
    Invalid carry is ignored by callers; runtime boundary cleanup remains the
    owner for clearing stale settings.
    """
    seconds = _read_pending_short_seconds() if pending_seconds is None else max(0, int(pending_seconds))
    if seconds <= 0:
        return {"valid": False, "seconds": 0, "reason": "no_pending"}
    if current_status != STATUS_NORMAL:
        return {"valid": False, "seconds": 0, "reason": "status_not_normal"}
    if not current_start_time:
        return {"valid": False, "seconds": 0, "reason": "missing_current_start"}

    provenance = _load_pending_carry_provenance()
    if not provenance:
        return {"valid": False, "seconds": 0, "reason": "missing_provenance"}
    if provenance.get("version") != 1 or provenance.get("source_status") != STATUS_NORMAL:
        return {"valid": False, "seconds": 0, "reason": "invalid_provenance"}

    source_start = str(provenance.get("source_start_time") or "")
    source_end = str(provenance.get("source_end_time") or "")
    if not source_start or not source_end:
        return {"valid": False, "seconds": 0, "reason": "missing_source_bounds"}
    if source_end > current_start_time:
        return {"valid": False, "seconds": 0, "reason": "source_after_current"}
    if source_start[:10] != current_start_time[:10] or source_end[:10] != current_start_time[:10]:
        return {"valid": False, "seconds": 0, "reason": "date_boundary"}
    if session_boundary_service.has_boundary_between(source_start, current_start_time):
        return {"valid": False, "seconds": 0, "reason": "boundary_between"}

    latest_now = session_boundary_service.latest_boundary_time() or ""
    latest_at_write = str(provenance.get("latest_boundary_at_write") or "")
    if latest_now != latest_at_write:
        return {"valid": False, "seconds": 0, "reason": "new_boundary_after_write"}
    if latest_now and latest_now >= source_start:
        return {"valid": False, "seconds": 0, "reason": "boundary_at_source"}

    return {
        "valid": True,
        "seconds": seconds,
        "reason": "validated_pending_carry",
        "source_start_time": source_start,
        "source_end_time": source_end,
        "latest_boundary_at_write": latest_at_write,
    }


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
    "validate_pending_short_carry",
    "write_pending_short_carry",
]
