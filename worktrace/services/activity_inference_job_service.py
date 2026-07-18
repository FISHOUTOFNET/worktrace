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
from . import activity_inference_job_repository as jobs

InferenceCommand = Callable[[Any, int], tuple[dict, bool]]


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
    if requested_ids is not None:
        with DomainUnitOfWork() as uow:
            jobs.enqueue_closed_activity_ids(uow.connection, requested_ids)

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
            with DomainUnitOfWork() as uow:
                conn = uow.connection
                current = jobs.list_runnable_jobs(
                    conn,
                    limit=1,
                    activity_ids=[activity_id],
                )
                if not current:
                    continue
                activity = conn.execute(
                    """
                    SELECT activity.end_time, activity.status,
                           activity.is_hidden, activity.is_deleted,
                           assignment.is_manual, assignment.source
                    FROM activity_log activity
                    LEFT JOIN activity_project_assignment assignment
                      ON assignment.activity_id = activity.id
                    WHERE activity.id = ?
                    """,
                    (activity_id,),
                ).fetchone()
                eligible = bool(
                    activity is not None
                    and activity["end_time"] is not None
                    and str(activity["status"] or "") == "normal"
                    and not int(activity["is_hidden"] or 0)
                    and not int(activity["is_deleted"] or 0)
                    and not int(activity["is_manual"] or 0)
                    and str(activity["source"] or "") != "midnight_anchor"
                )
                if not eligible:
                    jobs.delete_job(conn, activity_id)
                    completed += 1
                    continue

                _result, assignment_changed = infer_activity(conn, activity_id)
                if assignment_changed:
                    uow.add_effects(DataGenerationNamespace.REPORT_STRUCTURE)
                jobs.delete_job(conn, activity_id)
                completed += 1
        except Exception as exc:
            code = _classify_failure(exc)
            logging.error(
                "activity inference job failed activity_id=%s code=%s",
                activity_id,
                code.value,
            )
            _record_failure_safely(activity_id, code)
    return completed


def start_inference_worker(
    stop_event: threading.Event,
    *,
    batch_size: int = 50,
    poll_seconds: float = 1.0,
) -> threading.Thread:
    """Start the single AppRuntime-owned inference worker."""

    thread = threading.Thread(
        target=_worker_loop,
        args=(stop_event, max(1, int(batch_size)), max(0.1, float(poll_seconds))),
        name="WorkTraceInferenceWorker",
        daemon=True,
    )
    thread.start()
    return thread


def _worker_loop(
    stop_event: threading.Event,
    batch_size: int,
    poll_seconds: float,
) -> None:
    from .project_inference_service import (
        assign_project_for_activity_with_change_in_transaction,
    )

    while not stop_event.is_set():
        try:
            processed = process_pending_inference_jobs(
                assign_project_for_activity_with_change_in_transaction,
                limit=batch_size,
            )
        except Exception:
            logging.error("activity inference worker iteration failed")
            processed = 0
        if processed >= batch_size:
            continue
        stop_event.wait(poll_seconds)


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
        if message == jobs.InferenceFailureCode.SECURE_IMPORT_IN_PROGRESS.value:
            return jobs.InferenceFailureCode.SECURE_IMPORT_IN_PROGRESS
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
        logging.error(
            "activity inference failure state could not be persisted activity_id=%s",
            activity_id,
        )


__all__ = [
    "InferenceCommand",
    "process_pending_inference_jobs",
    "start_inference_worker",
]
