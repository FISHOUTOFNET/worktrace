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
from .activity_inference_policy import is_closed_activity_inference_eligible

InferenceCommand = Callable[[Any, int], dict]


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
            with DomainUnitOfWork() as uow:
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
                infer_activity(conn, activity_id)
                after = _assignment_state(conn, activity_id)
                if before != after:
                    uow.add_effects(DataGenerationNamespace.REPORT_STRUCTURE)
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
    batch_size: int = 50,
    poll_seconds: float = 1.0,
) -> None:
    """Run the blocking inference loop owned by ``AppRuntime``."""

    size = max(1, int(batch_size))
    interval = max(0.1, float(poll_seconds))
    logging.info("activity inference worker start")
    while not stop_event.is_set():
        try:
            processed = process_pending_inference_jobs(
                infer_activity,
                limit=size,
            )
        except Exception:
            logging.exception("activity inference worker iteration failed")
            processed = 0
        if processed >= size:
            continue
        stop_event.wait(interval)
    logging.info("activity inference worker stop")


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
        logging.exception(
            "activity inference failure state could not be persisted activity_id=%s",
            activity_id,
        )


__all__ = [
    "InferenceCommand",
    "process_pending_inference_jobs",
    "run_inference_worker",
]
