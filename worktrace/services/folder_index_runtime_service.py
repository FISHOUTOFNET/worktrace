"""Runtime orchestration for folder-index eligibility and worker lifecycle.

The durable scanner remains in ``folder_index_service``. This layer owns the
catalog eligibility boundary while preserving the original module object and its
fault-injection seams.
"""

from __future__ import annotations

import logging
import threading
import time

from ..db import get_connection
from ..write_gate import DATABASE_WRITE_GATE
from . import folder_index_service as _core
from . import folder_index_maintenance_service, folder_index_state_repository
from . import privacy_gate_service

_CORE_ENSURE_INDEX_STATES = _core.ensure_index_states_for_folder_rules
_CORE_REBUILD_FOLDER_INDEX = _core.rebuild_folder_index
_CORE_VALIDATE_READY_INDEXES = _core.validate_ready_indexes


def _ineligible_rule_ids() -> list[int]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT state.folder_rule_id
            FROM folder_rule_index_state state
            LEFT JOIN folder_project_rule fpr
              ON fpr.id = state.folder_rule_id
            LEFT JOIN project p
              ON p.id = fpr.project_id
            WHERE fpr.id IS NULL
               OR COALESCE(fpr.enabled, 0) <> 1
               OR p.id IS NULL
               OR COALESCE(p.enabled, 0) <> 1
               OR COALESCE(p.is_archived, 0) <> 0
               OR COALESCE(p.is_deleted, 0) <> 0
            ORDER BY state.folder_rule_id
            """
        ).fetchall()
    return [int(row["folder_rule_id"]) for row in rows]


def reconcile_index_eligibility() -> int:
    """Remove derived state for catalog entries that cannot currently match."""

    rule_ids = _ineligible_rule_ids()
    if not rule_ids:
        return 0
    with get_connection() as conn:
        for rule_id in rule_ids:
            folder_index_state_repository.delete_rule_index(conn, rule_id)
    return len(rule_ids)


def ensure_index_states_for_folder_rules() -> None:
    _CORE_ENSURE_INDEX_STATES()
    reconcile_index_eligibility()


def _rule_is_eligible(rule_id: int) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM folder_project_rule fpr
            JOIN project p ON p.id = fpr.project_id
            WHERE fpr.id = ?
              AND fpr.enabled = 1
              AND p.enabled = 1
              AND COALESCE(p.is_archived, 0) = 0
              AND COALESCE(p.is_deleted, 0) = 0
            """,
            (int(rule_id),),
        ).fetchone()
    return row is not None


def rebuild_folder_index(
    rule_id: int,
    stop_event: threading.Event | None = None,
) -> bool:
    if not _rule_is_eligible(rule_id):
        _core.delete_index_for_rule(int(rule_id))
        return False
    return _CORE_REBUILD_FOLDER_INDEX(int(rule_id), stop_event)


def validate_ready_indexes(stop_event: threading.Event | None = None) -> None:
    reconcile_index_eligibility()
    _CORE_VALIDATE_READY_INDEXES(stop_event)


def run_folder_index_worker(
    stop_event: threading.Event,
    *,
    health,
) -> None:
    logging.info("folder index worker loop enter")
    next_hot_refresh_at = 0.0
    try:
        ensure_index_states_for_folder_rules()
        _core.recover_interrupted_indexes()
        reconcile_index_eligibility()
        if privacy_gate_service.is_sensitive_runtime_allowed():
            validate_ready_indexes(stop_event)
    except Exception:
        logging.exception("folder index startup validation failed")
        health.failed("folder_index_startup_failed")
    else:
        health.succeeded()

    while not stop_event.is_set():
        try:
            if DATABASE_WRITE_GATE.writes_blocked():
                health.maintenance_paused(True)
                _core._wait_for_worker()
                continue
            health.maintenance_paused(False)
            if not privacy_gate_service.is_sensitive_runtime_allowed():
                health.maintenance_paused(True)
                _core._wait_for_worker()
                continue
            health.maintenance_paused(False)

            ensure_index_states_for_folder_rules()
            _core._retry_pending_gc()

            monotonic_now = time.monotonic()
            if monotonic_now >= next_hot_refresh_at:
                folder_index_maintenance_service.request_refresh_for_hot_projects()
                next_hot_refresh_at = monotonic_now + _core._HOT_REFRESH_CHECK_SECONDS

            rebuilt_any = False
            for rule_id in _core._pending_rule_ids():
                if stop_event.is_set() or DATABASE_WRITE_GATE.writes_blocked():
                    break
                if rebuild_folder_index(rule_id, stop_event):
                    rebuilt_any = True
            if rebuilt_any:
                try:
                    folder_index_maintenance_service.reconcile_open_unclassified_activities()
                except Exception:
                    logging.exception(
                        "folder index post-refresh reconciliation failed"
                    )
            health.succeeded()
            _core._wait_for_worker()
        except Exception:
            logging.exception("folder index worker error")
            health.failed("folder_index_iteration_failed")
            _core._wait_for_worker()
    logging.info("folder index worker loop exit")


__all__ = [
    "ensure_index_states_for_folder_rules",
    "rebuild_folder_index",
    "reconcile_index_eligibility",
    "run_folder_index_worker",
    "validate_ready_indexes",
]
