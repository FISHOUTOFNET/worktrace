"""ActivityLifecycle Command Facade — sole owner of open-row state transitions.

Architecture boundary (see architecture.md §"Write side"):

    collector / recovery / clipboard / shutdown / runtime lifecycle
        ↓
    activity_lifecycle_service   (THIS module — command facade)
        ↓
    activity_service + project_inference_service + resource_service
    + session_boundary_service

Responsibilities
----------------
This service is the single command owner for every open-row lifecycle
transition in WorkTrace:

- creating a new open activity (closes pre-existing open rows first);
- closing an open activity;
- virtual → persisted_open persistence (30-second threshold);
- clipboard force-persist (bypasses the 30-second threshold, STATUS_NORMAL
  only);
- midnight split / midnight-anchor persistence;
- recovery close / recovery cross-midnight split;
- close-finalize convergence (project inference / automatic rules) on
  every row that transitions open → closed.

``activity_service`` retains the low-level DB/CRUD helpers
(``create_activity`` row insert, ``_close_activity_in_conn``,
``set_activity_duration``, ``apply_midnight_anchor_assignment`` etc.) but
is no longer the preferred business entry point. Production callers
(collector, recovery, clipboard, shutdown) should route through this
facade so the open-row state machine has exactly one owner.

Design rules
------------
- The facade is **stateless**. Callers (e.g. ``AutoActivityRecorder``)
  continue to own their in-memory state (``persisted_activity_id``,
  ``current_extra_seconds`` …); the facade only owns the DB transition.
- Inference / automatic-rules convergence runs **outside** the DB
  transaction (lazy connection) to avoid nested-connection / lock issues.
- An inference failure on one row is logged and never blocks the
  remaining rows or the new activity creation.
- Manual assignments / ``manual_override`` / concrete DB assignments are
  never overridden (guaranteed by ``process_new_activity`` /
  ``sync_persisted_open_activity_project`` guards).
- ``suggested_project_name`` never auto-creates a project.
- The 30-second persistence threshold (``HISTORY_PERSIST_THRESHOLD_SECONDS``)
  is enforced by the *caller*, not here — the facade only executes the
  persist command once the caller has decided the threshold is met.
- Clipboard force-persist bypasses the threshold but is restricted to
  ``STATUS_NORMAL`` by the caller; the facade does not re-check the
  threshold.
"""

from __future__ import annotations

import logging
from typing import Any

from ..constants import STATUS_NORMAL
from . import activity_service, session_boundary_service


# ---------------------------------------------------------------------------
# Unified close-finalize helper
# ---------------------------------------------------------------------------


def finalize_closed_activity_ids(closed_ids: list[int]) -> None:
    """Run project inference / automatic rules on a batch of just-closed rows.

    This is the **single unified close-finalize helper**. Every code path
    that closes an open row (``create_activity``'s built-in close-old-rows,
    ``close_activity``, ``close_current_open_record``, recovery close,
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


# ---------------------------------------------------------------------------
# Open-row lifecycle commands
# ---------------------------------------------------------------------------


def start_activity(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
) -> int:
    """Create a new open activity row.

    Any pre-existing open rows are closed first by
    ``activity_service.create_activity`` (which collects the closed ids
    and finalizes them via :func:`finalize_closed_activity_ids`). Returns
    the new activity_id.

    Use this for the collector's first observation of a brand-new activity
    signature that should be persisted immediately (rare — most collector
    activities go through :func:`persist_open_activity_if_ready` after the
    30-second threshold).
    """
    return activity_service.create_activity(
        start_time=start_time,
        source=source,
        **payload,
    )


def persist_open_activity_if_ready(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
) -> int:
    """Persist a virtual activity as a new open DB row.

    This is the normal 30-second-threshold persistence path. The caller
    (``AutoActivityRecorder``) is responsible for enforcing the threshold;
    this facade only executes the persist command.

    Steps (in order):

    1. ``create_activity`` — inserts the open row AND closes any
       pre-existing open rows (finalizing each via
       :func:`finalize_closed_activity_ids`).
    2. ``finalize_created_activity`` — routes through
       ``process_new_activity``. For an open row this is effectively a
       no-op (``process_new_activity`` skips in-progress rows) but is kept
       for contract symmetry with the close path.
    3. ``sync_persisted_open_activity_project`` — converges the open row's
       project assignment so the virtual → persisted_open transition does
       not revert a concrete inferred project to ``未归类``. This is a
       no-op for rows that are already concrete (folder_rule /
       keyword_rule / midnight_anchor) or manually assigned.

    Returns the new activity_id.
    """
    activity_id = activity_service.create_activity(
        start_time=start_time,
        source=source,
        **payload,
    )
    activity_service.finalize_created_activity(activity_id)
    _sync_open_row_project_safely(activity_id, status=payload.get("status"))
    return activity_id


def force_persist_open_activity_for_clipboard(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
) -> int:
    """Force-persist a normal activity for clipboard capture.

    Bypasses the 30-second threshold. The caller
    (``AutoActivityRecorder.ensure_persisted_for_clipboard``) restricts
    this to ``STATUS_NORMAL``; the facade does not re-check the status.

    Semantics are identical to :func:`persist_open_activity_if_ready`
    (the threshold gate lives in the caller, not here). Returns the new
    activity_id.
    """
    return persist_open_activity_if_ready(
        start_time=start_time,
        source=source,
        payload=payload,
    )


def close_activity(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
) -> None:
    """Close an open activity row and run project inference.

    Delegates to ``activity_service.close_activity`` which closes the row
    in a transaction and then calls ``process_new_activity`` so enabled
    folder / keyword rules apply to the just-closed row. The inference
    runs outside the close transaction.
    """
    activity_service.close_activity(activity_id, end_time, duration_seconds=duration_seconds)


def close_all_open_activities(end_time: str | None = None) -> list[int]:
    """Close every open activity row (``end_time IS NULL``).

    Delegates to ``activity_service.close_current_open_record`` which
    collects the closed ids and finalizes each via
    ``process_new_activity``. Returns the list of closed ids.

    Used by shutdown / pause / time-jump / collector stop paths.
    """
    # close_current_open_record finalizes internally; we re-query the
    # closed ids for the caller's convenience (the helper does not yet
    # return them).
    from ..db import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id FROM activity_log WHERE end_time IS NULL ORDER BY id"
        ).fetchall()
    closed_ids = [int(r["id"]) for r in rows]
    activity_service.close_current_open_record(end_time)
    return closed_ids


def persist_midnight_anchor(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
    project_id: int,
) -> int:
    """Persist a midnight-anchor open activity with a concrete project.

    Creates the open row, finalizes it, and applies the
    ``midnight_anchor`` assignment source (confidence 90, stronger than
    the open-row sync's ``uncategorized`` / ``suggested_project_name``
    sources). Used by the collector's midnight split path.

    Returns the new activity_id.
    """
    activity_id = activity_service.create_activity(
        start_time=start_time,
        source=source,
        **payload,
    )
    activity_service.finalize_created_activity(activity_id)
    activity_service.apply_midnight_anchor_assignment(activity_id, int(project_id))
    return activity_id


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
    activity_id = activity_service.create_activity(
        start_time=start_time,
        source=source,
        status=status,
        **payload,
    )
    activity_service.finalize_created_activity(activity_id)
    if status == STATUS_NORMAL and project_id is not None:
        activity_service.apply_midnight_anchor_assignment(activity_id, int(project_id))
    activity_service.close_activity(activity_id, end_time)
    return activity_id


def recover_first_half_close(
    activity_id: int,
    end_time: str,
    duration_seconds: int,
) -> None:
    """Close the first half of a cross-midnight unclosed record and finalize.

    Delegates to :func:`close_activity` with an explicit ``duration_seconds``
    (computed from start_time to first_midnight). The inference runs via
    ``close_activity`` → ``process_new_activity``.
    """
    activity_service.close_activity(
        activity_id, end_time, duration_seconds=duration_seconds
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sync_open_row_project_safely(activity_id: int, *, status: str | None) -> None:
    """Converge the freshly-persisted open row's project assignment.

    Only runs for ``STATUS_NORMAL`` rows (system-status rows are never
    project-inferred). Wrapped in try/except so an inference failure does
    not discard the just-persisted open row — the assignment simply stays
    at whatever ``create_activity`` wrote (``uncategorized``).
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
    "recover_cross_midnight_segment",
    "recover_first_half_close",
]
