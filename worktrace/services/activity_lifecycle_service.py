"""ActivityLifecycle Command Facade — sole owner of open-row state transitions."""

from __future__ import annotations

import logging
from typing import Any

from ..constants import HISTORY_PERSIST_THRESHOLD_SECONDS, STATUS_NORMAL
from . import activity_service, session_boundary_service


# Unified close-finalize helper


def finalize_closed_activity_ids(closed_ids: list[int]) -> None:
    """Run project inference / automatic rules on a batch of just-closed rows.

    This is the **single unified close-finalize helper**. Every code path
    that closes an open row (``start_activity``'s built-in close-old-rows,
    ``close_activity``, ``close_all_open_activities``, recovery close,
    midnight split) must route the closed ids through this helper so the
    persisted project assignment converges consistently.

    MUST be called **after** the DB transaction that closed the rows has
    exited, so inference runs on a clean connection (no nested-connection
    / lock risk). ``process_new_activity`` skips in-progress rows, so
    calling it before the row is actually closed would be a no-op.

    A failure on one row is logged and never blocks the remaining rows.
    """
    if not closed_ids:
        return
    from .project_inference_service import process_new_activity

    for aid in closed_ids:
        try:
            process_new_activity(aid)
        except Exception:
            # Defensive: never let an inference failure on one row
            # prevent the remaining rows from being finalized. The row is
            # already closed; its assignment simply stays at whatever was
            # inferred at create time.
            logging.exception(
                "close-finalize inference failed for activity_id=%s", aid
            )


# Open-row lifecycle commands


def start_activity(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
) -> int:
    """Create a new open activity row, closing pre-existing open rows first.

    Steps (in order):

    1. Close every pre-existing open row (``end_time IS NULL``) via the
       low-level ``close_all_open_rows`` helper and collect the closed ids.
    2. Finalize the closed ids (project inference / automatic rules)
       **outside** the close transaction.
    3. Insert the new open activity row via the low-level
       ``insert_activity_row`` helper.

    Returns the new activity_id.

    Use this for the collector's first observation of a brand-new activity
    signature that should be persisted immediately (rare — most collector
    activities go through :func:`persist_open_activity_if_ready` after the
    30-second threshold).
    """
    closed_ids = activity_service.close_all_open_rows(start_time)
    if closed_ids:
        finalize_closed_activity_ids(closed_ids)
    return activity_service.insert_activity_row(
        start_time=start_time,
        source=source,
        **payload,
    )


def persist_open_activity_if_ready(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
    elapsed_seconds: int,
    force: bool = False,
) -> int | None:
    """Persist a virtual activity as a new open DB row.

    The 30-second threshold (``HISTORY_PERSIST_THRESHOLD_SECONDS``) is
    enforced INSIDE this facade. Callers MUST pass the actual
    ``elapsed_seconds``; the facade no longer trusts callers to gate the
    threshold.

    ``force=True`` bypasses the threshold and is only legal for the
    clipboard force-persist path (which itself re-checks ``STATUS_NORMAL``).
    Ordinary callers must pass ``force=False`` and rely on the facade's
    threshold check.

    Returns the new ``activity_id`` on persist, or ``None`` when the
    threshold gate rejects the persist (no-op).
    """
    if not force and int(elapsed_seconds) < HISTORY_PERSIST_THRESHOLD_SECONDS:
        return None
    return _persist_open_activity_unchecked(
        start_time=start_time, source=source, payload=payload
    )


def force_persist_open_activity_for_clipboard(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
) -> int | None:
    """Force-persist a normal activity for clipboard capture.

    Bypasses the 30-second threshold. The facade enforces
    ``STATUS_NORMAL`` internally: callers cannot bypass this by passing
    an idle / paused / excluded / error status. A non-normal payload is
    rejected with ``None`` (no-op) and never reaches the DB.

    Returns the new ``activity_id`` on persist, or ``None`` when the
    status gate rejects the persist (no-op).
    """
    if payload.get("status") != STATUS_NORMAL:
        return None
    return _persist_open_activity_unchecked(
        start_time=start_time, source=source, payload=payload
    )


def _persist_open_activity_unchecked(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
) -> int:
    """Low-level persist helper with NO threshold / status gate.

    Internal only — every public persistence path goes through
    :func:`persist_open_activity_if_ready` or
    :func:`force_persist_open_activity_for_clipboard`, which enforce the
    threshold / status invariants. Returns the new ``activity_id``.
    """
    activity_id = activity_service.insert_activity_row(
        start_time=start_time,
        source=source,
        **payload,
    )
    activity_service.finalize_created_activity(activity_id)
    _sync_open_row_project_safely(activity_id, status=payload.get("status"))
    return activity_id


def close_activity(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
) -> None:
    """Close an open activity row and run project inference.

    Performs the low-level close via ``close_activity_row`` and then
    calls ``finalize_closed_activity_ids`` so enabled folder / keyword
    rules apply to the just-closed row. The inference runs outside the
    close transaction.
    """
    activity_service.close_activity_row(
        activity_id, end_time, duration_seconds=duration_seconds
    )
    finalize_closed_activity_ids([activity_id])


def close_all_open_activities(end_time: str | None = None) -> list[int]:
    """Close every open activity row (``end_time IS NULL``).

    Performs the low-level close-all via ``close_all_open_rows`` and then
    finalizes every closed id. Returns the list of closed ids.

    Used by shutdown / pause / time-jump / collector stop paths.
    """
    closed_ids = activity_service.close_all_open_rows(end_time)
    finalize_closed_activity_ids(closed_ids)
    return closed_ids


def persist_midnight_anchor(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
    project_id: int,
) -> int:
    """Persist a midnight-anchor open activity with a concrete project.

    Creates the open row (pure CRUD), finalizes it, and applies the
    ``midnight_anchor`` assignment source (confidence 90, stronger than
    the open-row sync's ``uncategorized`` / ``suggested_project_name``
    sources). Used by the collector's midnight split path.

    Returns the new activity_id.
    """
    activity_id = activity_service.insert_activity_row(
        start_time=start_time,
        source=source,
        **payload,
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.apply_midnight_anchor_assignment(activity_id, int(project_id))
    return activity_id


def recover_close_activity(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
    status: str | None = None,
) -> None:
    """Recovery non-cross-midnight close + finalize.

    Used by ``recovery_service.recover_unclosed_records`` for the
    non-cross-midnight path. Performs the low-level close (with an
    optional status override for STATUS_ERROR recovery) and then
    finalizes so project inference / automatic rules converge on the
    recovered row. ``recovery_service`` no longer directly SQL-closes
    open rows.
    """
    activity_service.close_activity_row(
        activity_id,
        end_time,
        duration_seconds=duration_seconds,
        status=status,
    )
    finalize_closed_activity_ids([activity_id])


def recover_cross_midnight_segment(
    *,
    start_time: str,
    end_time: str,
    source: str,
    status: str,
    payload: dict[str, Any],
    project_id: int | None = None,
) -> int:
    """Create + close a single recovered cross-midnight segment.

    Used by ``recovery_service._recover_cross_midnight_row`` for each
    day-spanned segment of an unclosed record that crossed midnight. When
    ``status`` is ``STATUS_NORMAL`` and ``project_id`` is concrete, the
    ``midnight_anchor`` assignment is applied before close so the
    recovered segment keeps the original row's concrete project.

    Returns the new activity_id (the segment is closed inside this call).
    """
    activity_id = activity_service.insert_activity_row(
        start_time=start_time,
        source=source,
        status=status,
        **payload,
    )
    activity_service.finalize_created_activity(activity_id)
    if status == STATUS_NORMAL and project_id is not None:
        activity_service.apply_midnight_anchor_assignment(activity_id, int(project_id))
    close_activity(activity_id, end_time)
    return activity_id


def recover_first_half_close(
    activity_id: int,
    end_time: str,
    duration_seconds: int,
) -> None:
    """Close the first half of a cross-midnight unclosed record and finalize.

    Delegates to :func:`close_activity` with an explicit ``duration_seconds``
    (computed from start_time to first_midnight). The inference runs via
    ``close_activity`` → ``finalize_closed_activity_ids``.
    """
    close_activity(
        activity_id, end_time, duration_seconds=duration_seconds
    )


# Internal helpers


def _sync_open_row_project_safely(activity_id: int, *, status: str | None) -> None:
    """Converge the freshly-persisted open row's project assignment.

    Only runs for ``STATUS_NORMAL`` rows (system-status rows are never
    project-inferred). Wrapped in try/except so an inference failure does
    not discard the just-persisted open row — the assignment simply stays
    at whatever ``insert_activity_row`` wrote (``uncategorized``).
    """
    if status != STATUS_NORMAL:
        return
    from .project_inference_service import sync_persisted_open_activity_project

    try:
        sync_persisted_open_activity_project(activity_id)
    except Exception:
        logging.exception(
            "open-row project sync failed for activity_id=%s", activity_id
        )


__all__ = [
    "finalize_closed_activity_ids",
    "start_activity",
    "persist_open_activity_if_ready",
    "force_persist_open_activity_for_clipboard",
    "close_activity",
    "close_all_open_activities",
    "persist_midnight_anchor",
    "recover_close_activity",
    "recover_cross_midnight_segment",
    "recover_first_half_close",
]
