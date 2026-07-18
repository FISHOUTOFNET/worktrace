"""Bounded consumer for durable closed-activity inference obligations.

The worker is the only completion owner: assignment writes and job deletion
share one root UoW, while failures roll back and update backoff separately.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterable
from typing import Any

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import activity_inference_job_repository as jobs

InferenceCommand = Callable[[Any, int], dict]


def process_pending_inference_jobs(
    infer_activity: InferenceCommand,
    limit: int = 100,
    *,
    activity_ids: Iterable[int] | None = None,
) -> int:
    """Consume due jobs; assignment and completion commit in one root UoW."""

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
        due_ids = jobs.list_due_activity_ids(
            conn,
            limit=normalized_limit,
            activity_ids=requested_ids,
        )

    completed = 0
    for activity_id in due_ids:
        try:
            with DomainUnitOfWork(
                (DataGenerationNamespace.REPORT_STRUCTURE,)
            ) as uow:
                conn = uow.connection
                if jobs.due_job(conn, activity_id) is None:
                    continue
                if not jobs.activity_is_eligible(conn, activity_id):
                    jobs.delete_job(conn, activity_id)
                    uow.mark_changed()
                    completed += 1
                    continue
                infer_activity(conn, activity_id)
                jobs.delete_job(conn, activity_id)
                uow.mark_changed()
                completed += 1
        except Exception as exc:
            error_code = _classify_failure(exc)
            logging.error(
                "activity inference job failed activity_id=%s code=%s",
                activity_id,
                error_code.value,
            )
            _record_failure_safely(activity_id, error_code)
    return completed


def run_inference_worker(
    stop_event: threading.Event,
    infer_activity: InferenceCommand,
    *,
    limit: int = 50,
    poll_seconds: float = 1.0,
) -> None:
    """Run bounded opportunity processing; SQLite rechecks provide coordination."""

    while not stop_event.is_set():
        try:
            process_pending_inference_jobs(
                infer_activity,
                limit=max(1, int(limit)),
            )
        except Exception:
            logging.exception("activity inference worker iteration failed")
        stop_event.wait(max(0.1, float(poll_seconds)))


def start_inference_worker(
    stop_event: threading.Event,
    infer_activity: InferenceCommand,
) -> threading.Thread:
    thread = threading.Thread(
        target=run_inference_worker,
        args=(stop_event, infer_activity),
        name="WorkTraceInferenceWorker",
        daemon=True,
    )
    thread.start()
    return thread


def _classify_failure(exc: BaseException) -> jobs.InferenceJobErrorCode:
    if isinstance(exc, sqlite3.OperationalError):
        sqlite_code = getattr(exc, "sqlite_errorcode", None)
        if sqlite_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            return jobs.InferenceJobErrorCode.DATABASE_BUSY
        if str(exc).strip().lower() in {
            "database is busy",
            "database is locked",
            "database table is locked",
        }:
            return jobs.InferenceJobErrorCode.DATABASE_BUSY
    if isinstance(exc, ValueError) and str(exc) == "data_repair_required":
        return jobs.InferenceJobErrorCode.DATA_REPAIR_REQUIRED
    return jobs.InferenceJobErrorCode.INFERENCE_FAILED


def _record_failure_safely(
    activity_id: int,
    error_code: jobs.InferenceJobErrorCode,
) -> None:
    try:
        with DomainUnitOfWork() as uow:
            attempts = jobs.record_failure(
                uow.connection,
                int(activity_id),
                error_code,
                at_time=now_str(),
            )
            if attempts:
                uow.mark_changed()
    except Exception:
        logging.exception(
            "activity inference failure state unavailable activity_id=%s",
            activity_id,
        )


__all__ = [
    "InferenceCommand",
    "process_pending_inference_jobs",
    "run_inference_worker",
    "start_inference_worker",
]
