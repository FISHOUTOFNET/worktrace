"""Bounded consumer for durable closed-activity inference jobs."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterable
from typing import Any

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..retry_state import RetryEpisode
from ..worker_health import WorkerHealthReporter
from ..write_gate import DATABASE_WRITE_GATE
from . import activity_inference_job_repository as jobs
from .activity_inference_policy import is_closed_activity_inference_eligible

InferenceCommand = Callable[[Any, int], dict]
_FOLDER_INDEX_DEFER_SECONDS = 15


def process_pending_inference_jobs(
    infer_activity: InferenceCommand,
    limit: int = 100,
    *,
    activity_ids: Iterable[int] | None = None,
) -> int:
    """Consume a bounded job set; assignment and completion commit together."""

    normalized_limit = max(0, int(limit))
    if normalized_limit == 0:
        return 0
    requested_ids = (
        sorted({int(activity_id) for activity_id in activity_ids})
        if activity_ids is not None
        else None
    )
    if requested_ids == []:
        return 0

    with get_connection() as conn:
        runnable = jobs.list_runnable_jobs(
            conn,
            limit=normalized_limit,
            activity_ids=requested_ids,
        )

    completed = 0
    for job in runnable:
        activity_id = int(job["activity_id"])
        try:
            with DomainUnitOfWork(
                (DataGenerationNamespace.REPORT_STRUCTURE,)
            ) as uow:
                conn = uow.connection
                current = jobs.list_runnable_jobs(
                    conn,
                    limit=1,
                    activity_ids=[activity_id],
                )
                if not current:
                    continue
                state = jobs.read_activity_and_assignment(conn, activity_id)
                assignment = (
                    None
                    if state is None or state["assignment_activity_id"] is None
                    else state
                )
                if not is_closed_activity_inference_eligible(state, assignment):
                    jobs.delete_job(conn, activity_id)
                    completed += 1
                    continue

                before = _assignment_state(conn, activity_id)
                result = infer_activity(conn, activity_id)
                after = _assignment_state(conn, activity_id)
                if before != after:
                    uow.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)
                if str(result.get("_defer_reason") or "") == "folder_index_refresh":
                    jobs.defer_job(
                        conn,
                        activity_id,
                        delay_seconds=_FOLDER_INDEX_DEFER_SECONDS,
                    )
                else:
                    jobs.delete_job(conn, activity_id)
                completed += 1
        except Exception as exc:
            code = _classify_failure(exc)
            logging.exception(
                "activity inference job failed activity_id=%s code=%s",
                activity_id,
                code.value,
            )
            _record_failure_safely(activity_id, code)
    return completed


def run_inference_worker(
    stop_event: threading.Event,
    infer_activity: InferenceCommand,
    *,
    health: WorkerHealthReporter,
    batch_size: int = 50,
    poll_seconds: float = 1.0,
) -> None:
    """Run iterations only; AppRuntime owns thread started/stopped state."""

    size = max(1, int(batch_size))
    interval = max(0.1, float(poll_seconds))
    retry_episode = RetryEpisode()
    logging.info("activity inference worker loop enter")
    while not stop_event.is_set():
        if DATABASE_WRITE_GATE.writes_blocked():
            health.maintenance_paused(True)
            stop_event.wait(interval)
            continue
        health.maintenance_paused(False)
        try:
            processed = process_pending_inference_jobs(
                infer_activity,
                limit=size,
            )
        except Exception as exc:
            code = _classify_failure(exc)
            retry = retry_episode.failed(code.value)
            health.failed("inference_iteration_failed")
            if retry.detail_log_due:
                logging.warning(
                    "activity inference worker iteration failed code=%s",
                    code.value,
                    exc_info=True,
                )
            elif retry.summary_log_due:
                logging.warning(
                    "activity inference worker failure continues code=%s consecutive=%s elapsed_seconds=%.1f",
                    code.value,
                    retry.attempt,
                    retry.elapsed_seconds,
                )
            stop_event.wait(max(interval, retry.delay_seconds))
            continue
        recovery = retry_episode.succeeded()
        health.succeeded()
        if recovery.recovered:
            logging.info(
                "activity inference worker recovered code=%s attempts=%s elapsed_seconds=%.1f",
                recovery.code,
                recovery.attempts,
                recovery.elapsed_seconds,
            )
        if processed >= size:
            continue
        stop_event.wait(interval)
    logging.info("activity inference worker loop exit")


def _assignment_state(conn, activity_id: int) -> tuple[object, ...] | None:
    row = conn.execute(
        """
        SELECT project_id, confidence, source, is_manual,
               suggested_project_name, source_rule_type, source_rule_id
        FROM activity_project_assignment
        WHERE activity_id = ?
        """,
        (int(activity_id),),
    ).fetchone()
    return tuple(row) if row is not None else None


def _classify_failure(exc: BaseException) -> jobs.InferenceFailureCode:
    if isinstance(exc, ValueError) and str(exc) == "data_repair_required":
        return jobs.InferenceFailureCode.DATA_REPAIR_REQUIRED
    if isinstance(exc, sqlite3.OperationalError):
        sqlite_code = getattr(exc, "sqlite_errorcode", None)
        message = str(exc).strip().lower()
        if sqlite_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or message in {
            "database is locked",
            "database table is locked",
            "database is busy",
        }:
            return jobs.InferenceFailureCode.DATABASE_BUSY
        if message == jobs.InferenceFailureCode.DATABASE_MAINTENANCE_IN_PROGRESS.value:
            return jobs.InferenceFailureCode.DATABASE_MAINTENANCE_IN_PROGRESS
        if message == jobs.InferenceFailureCode.DATABASE_GENERATION_CHANGED.value:
            return jobs.InferenceFailureCode.DATABASE_GENERATION_CHANGED
    return jobs.InferenceFailureCode.UNEXPECTED_FAILURE


def _record_failure_safely(
    activity_id: int,
    code: jobs.InferenceFailureCode,
) -> None:
    try:
        with DomainUnitOfWork() as uow:
            jobs.record_failure(
                uow.connection,
                activity_id,
                code,
                at_time=now_str(),
            )
    except Exception:
        logging.exception(
            "activity inference failure state could not be persisted activity_id=%s",
            activity_id,
        )


__all__ = [
    "InferenceCommand",
    "process_pending_inference_jobs",
    "run_inference_worker",
]
