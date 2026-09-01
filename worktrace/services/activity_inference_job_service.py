"""Bounded consumer for durable closed-activity inference jobs."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from collections.abc import Callable, Iterable
from typing import Any

from ..data_generation_repository import DataGenerationNamespace
from ..database_failure_policy import DatabaseFailureKind, classify_database_failure
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..retry_state import RetryEpisode
from ..worker_health import WorkerHealthReporter, degraded_failure
from ..write_gate import DATABASE_WRITE_GATE
from . import activity_inference_job_repository as jobs
from .activity_inference_policy import is_closed_activity_inference_eligible

InferenceCommand = Callable[[Any, int], dict]
_FOLDER_INDEX_DEFER_SECONDS = 15


@dataclass(frozen=True)
class InferenceBatchResult:
    attempted: int = 0
    processed: int = 0
    failed: int = 0
    infrastructure_failure: DatabaseFailureKind | None = None


def _process_pending_inference_batch(
    infer_activity: InferenceCommand,
    limit: int = 100,
    *,
    activity_ids: Iterable[int] | None = None,
) -> InferenceBatchResult:
    normalized_limit = max(0, int(limit))
    if normalized_limit == 0:
        return InferenceBatchResult()
    requested_ids = (
        sorted({int(activity_id) for activity_id in activity_ids})
        if activity_ids is not None
        else None
    )
    if requested_ids == []:
        return InferenceBatchResult()

    with get_connection() as conn:
        runnable = jobs.list_runnable_jobs(
            conn,
            limit=normalized_limit,
            activity_ids=requested_ids,
        )

    attempted = 0
    processed = 0
    failed = 0
    for job in runnable:
        activity_id = int(job["activity_id"])
        attempted += 1
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
                    processed += 1
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
                processed += 1
        except Exception as exc:
            infrastructure_failure = classify_database_failure(exc)
            if infrastructure_failure is not None:
                logging.warning(
                    "activity inference batch paused activity_id=%s code=%s",
                    activity_id,
                    infrastructure_failure.value,
                )
                return InferenceBatchResult(
                    attempted=attempted,
                    processed=processed,
                    failed=failed,
                    infrastructure_failure=infrastructure_failure,
                )
            code = _classify_failure(exc)
            logging.exception(
                "activity inference job failed activity_id=%s code=%s",
                activity_id,
                code.value,
            )
            persistence_failure = _record_failure_safely(activity_id, code)
            if persistence_failure is not None:
                return InferenceBatchResult(
                    attempted=attempted,
                    processed=processed,
                    failed=failed,
                    infrastructure_failure=persistence_failure,
                )
            failed += 1
    return InferenceBatchResult(
        attempted=attempted,
        processed=processed,
        failed=failed,
    )


def process_pending_inference_jobs(
    infer_activity: InferenceCommand,
    limit: int = 100,
    *,
    activity_ids: Iterable[int] | None = None,
) -> int:
    """Consume a bounded job set while preserving the processed-count API."""

    return _process_pending_inference_batch(
        infer_activity,
        limit=limit,
        activity_ids=activity_ids,
    ).processed



def run_inference_worker(
    stop_event: threading.Event,
    infer_activity: InferenceCommand,
    *,
    health: WorkerHealthReporter,
    batch_size: int = 50,
    poll_seconds: float = 1.0,
) -> None:
    """Run bounded inference batches with separate job and infrastructure retry."""

    size = max(1, int(batch_size))
    interval = max(0.1, float(poll_seconds))
    retry_episode = RetryEpisode()
    backlog_degraded = False
    logging.info("activity inference worker loop enter")
    while not stop_event.is_set():
        if DATABASE_WRITE_GATE.writes_blocked():
            health.maintenance_paused(True)
            stop_event.wait(interval)
            continue
        health.maintenance_paused(False)
        try:
            batch = _process_pending_inference_batch(
                infer_activity,
                limit=size,
            )
        except Exception as exc:
            database_failure = classify_database_failure(exc)
            code = (
                database_failure.value
                if database_failure is not None
                else "inference_iteration_failed"
            )
            retry = retry_episode.failed(code)
            health.failed(code)
            if retry.detail_log_due:
                logging.warning(
                    "activity inference worker iteration failed code=%s",
                    code,
                    exc_info=True,
                )
            elif retry.summary_log_due:
                logging.warning(
                    "activity inference worker failure continues code=%s consecutive=%s elapsed_seconds=%.1f",
                    code,
                    retry.attempt,
                    retry.elapsed_seconds,
                )
            stop_event.wait(max(interval, retry.delay_seconds))
            continue

        if batch.infrastructure_failure is not None:
            code = batch.infrastructure_failure.value
            retry = retry_episode.failed(code)
            health.failed(degraded_failure(code) if batch.processed > 0 else code)
            if retry.detail_log_due:
                logging.warning(
                    "activity inference worker batch interrupted code=%s processed=%s attempted=%s",
                    code,
                    batch.processed,
                    batch.attempted,
                )
            elif retry.summary_log_due:
                logging.warning(
                    "activity inference worker infrastructure failure continues code=%s consecutive=%s elapsed_seconds=%.1f",
                    code,
                    retry.attempt,
                    retry.elapsed_seconds,
                )
            stop_event.wait(max(interval, retry.delay_seconds))
            continue

        recovery = retry_episode.succeeded()
        if batch.failed:
            health.failed(degraded_failure("inference_job_failures"))
            backlog_degraded = True
        else:
            try:
                with get_connection() as conn:
                    failed_backlog = jobs.has_failed_jobs(conn)
            except Exception as exc:
                database_failure = classify_database_failure(exc)
                code = (
                    database_failure.value
                    if database_failure is not None
                    else "inference_iteration_failed"
                )
                retry = retry_episode.failed(code)
                health.failed(code)
                stop_event.wait(max(interval, retry.delay_seconds))
                continue
            if failed_backlog:
                if not backlog_degraded:
                    health.failed(degraded_failure("inference_job_failures"))
                    backlog_degraded = True
            else:
                health.succeeded()
                backlog_degraded = False

        if recovery.recovered:
            logging.info(
                "activity inference worker recovered code=%s attempts=%s elapsed_seconds=%.1f",
                recovery.code,
                recovery.attempts,
                recovery.elapsed_seconds,
            )
        if batch.attempted >= size:
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
    return jobs.InferenceFailureCode.UNEXPECTED_FAILURE



def _record_failure_safely(
    activity_id: int,
    code: jobs.InferenceFailureCode,
) -> DatabaseFailureKind | None:
    try:
        with DomainUnitOfWork() as uow:
            jobs.record_failure(
                uow.connection,
                activity_id,
                code,
                at_time=now_str(),
            )
    except Exception as exc:
        database_failure = classify_database_failure(exc)
        logging.exception(
            "activity inference failure state could not be persisted activity_id=%s",
            activity_id,
        )
        return database_failure
    return None



__all__ = [
    "InferenceCommand",
    "process_pending_inference_jobs",
    "run_inference_worker",
]
