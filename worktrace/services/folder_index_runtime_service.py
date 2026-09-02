"""Runtime orchestration for folder-index eligibility and worker lifecycle.

The durable scanner remains in ``folder_index_service``. This layer owns the
catalog eligibility boundary while preserving the original module object and its
fault-injection seams.
"""

from __future__ import annotations

import logging
import threading
import time

from ..constants import EXCLUDED_PROJECT
from ..database_failure_policy import classify_database_failure
from ..db import get_connection
from ..retry_state import RetryEpisode
from ..worker_health import WorkerHealthReporter, degraded_failure
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


def request_refresh_for_enabled_rules(include_excluded: bool = False) -> None:
    """Compatibility refresh path whose cooldown records successful work only."""

    database_key, replacement_epoch = _core._replacement_cache_identity()
    cache_key = (database_key, replacement_epoch, bool(include_excluded))
    current = time.monotonic()
    if (
        current - _core._MISS_REFRESH_TIMES.get(cache_key, 0.0)
        < _core._MISS_REFRESH_COOLDOWN_SECONDS
    ):
        return

    project_clause = "" if include_excluded else "AND p.name <> ?"
    params: list[object] = [] if include_excluded else [EXCLUDED_PROJECT]
    with get_connection() as conn:
        rule_ids = [
            int(row["id"])
            for row in conn.execute(
                f"""
                SELECT fpr.id
                FROM folder_project_rule fpr
                JOIN project p ON p.id = fpr.project_id
                WHERE fpr.enabled = 1
                  AND p.enabled = 1
                  AND COALESCE(p.is_archived, 0) = 0
                  AND COALESCE(p.is_deleted, 0) = 0
                  {project_clause}
                ORDER BY fpr.id
                """,
                params,
            ).fetchall()
        ]
    for rule_id in rule_ids:
        _core.request_rebuild_for_rule(rule_id)

    # A failed database read or enqueue must not suppress the next retry.
    _core._MISS_REFRESH_TIMES[cache_key] = time.monotonic()


def run_folder_index_worker(
    stop_event: threading.Event,
    *,
    health: WorkerHealthReporter,
) -> None:
    """Own folder-index retry, interrupted-build recovery and truthful health."""

    retry_episode = RetryEpisode(
        initial_delay_seconds=_core._WORKER_IDLE_SECONDS,
        max_delay_seconds=30.0,
    )
    logging.info("folder index worker loop enter")
    next_hot_refresh_at = 0.0
    startup_reconciliation_pending = True
    interrupted_index_recovery_pending = False
    reconciliation_pending = False

    while not stop_event.is_set():
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

        try:
            if startup_reconciliation_pending:
                ensure_index_states_for_folder_rules()
                _core.recover_interrupted_indexes()
                reconcile_index_eligibility()
                validate_ready_indexes(stop_event)
                startup_reconciliation_pending = False
                reconciliation_pending = True
            else:
                if interrupted_index_recovery_pending:
                    _core.recover_interrupted_indexes()
                    interrupted_index_recovery_pending = False
                ensure_index_states_for_folder_rules()
                _core._retry_pending_gc()
                folder_index_maintenance_service.request_refresh_for_unresolved_file_misses()

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
                    reconciliation_pending = True

            if reconciliation_pending:
                outcome = (
                    folder_index_maintenance_service.reconcile_open_unclassified_activities_outcome()
                )
                if outcome.infrastructure_failure is not None:
                    code = outcome.infrastructure_failure.value
                    retry = retry_episode.failed(code)
                    health.failed(
                        degraded_failure(code) if outcome.reconciled > 0 else code
                    )
                    if retry.detail_log_due:
                        logging.warning(
                            "folder index reconciliation interrupted code=%s reconciled=%s attempted=%s",
                            code,
                            outcome.reconciled,
                            outcome.attempted,
                        )
                    elif retry.summary_log_due:
                        logging.warning(
                            "folder index reconciliation failure continues code=%s consecutive=%s elapsed_seconds=%.1f",
                            code,
                            retry.attempt,
                            retry.elapsed_seconds,
                        )
                    stop_event.wait(
                        max(_core._WORKER_IDLE_SECONDS, retry.delay_seconds)
                    )
                    continue

                recovery = retry_episode.succeeded()
                if outcome.failed:
                    health.failed(
                        degraded_failure("folder_index_reconciliation_partial")
                    )
                    if recovery.recovered:
                        logging.info(
                            "folder index worker infrastructure recovered code=%s attempts=%s elapsed_seconds=%.1f",
                            recovery.code,
                            recovery.attempts,
                            recovery.elapsed_seconds,
                        )
                    _core._wait_for_worker()
                    continue
                reconciliation_pending = False
            else:
                recovery = retry_episode.succeeded()

            health.succeeded()
            if recovery.recovered:
                logging.info(
                    "folder index worker recovered code=%s attempts=%s elapsed_seconds=%.1f",
                    recovery.code,
                    recovery.attempts,
                    recovery.elapsed_seconds,
                )
            _core._wait_for_worker()
        except Exception as exc:
            database_failure = classify_database_failure(exc)
            if database_failure is not None:
                code = database_failure.value
                if not startup_reconciliation_pending:
                    interrupted_index_recovery_pending = True
            else:
                code = (
                    "folder_index_startup_failed"
                    if startup_reconciliation_pending
                    else "folder_index_iteration_failed"
                )
            retry = retry_episode.failed(code)
            health.failed(code)
            if retry.detail_log_due:
                logging.warning(
                    "folder index worker failure code=%s",
                    code,
                    exc_info=True,
                )
            elif retry.summary_log_due:
                logging.warning(
                    "folder index worker failure continues code=%s consecutive=%s elapsed_seconds=%.1f",
                    code,
                    retry.attempt,
                    retry.elapsed_seconds,
                )
            stop_event.wait(
                max(_core._WORKER_IDLE_SECONDS, retry.delay_seconds)
            )

    logging.info("folder index worker loop exit")



__all__ = [
    "ensure_index_states_for_folder_rules",
    "rebuild_folder_index",
    "reconcile_index_eligibility",
    "request_refresh_for_enabled_rules",
    "run_folder_index_worker",
    "validate_ready_indexes",
]
