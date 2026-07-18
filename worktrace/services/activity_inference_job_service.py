"""Bounded consumer for durable closed-activity inference jobs."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from typing import Any

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import activity_inference_job_repository as jobs

InferenceCommand = Callable[[Any, int], dict]

_EXECUTION_LOCK = threading.RLock()


def recover_interrupted_inference_jobs() -> int:
    """Return any committed running rows to pending after process interruption."""

    with DomainUnitOfWork() as uow:
        changed = jobs.recover_interrupted_jobs(uow.connection)
        if changed:
            uow.mark_changed()
        return changed


def process_pending_inference_jobs(
    infer_activity: InferenceCommand,
    limit: int = 100,
    *,
    activity_ids: Iterable[int] | None = None,
) -> int:
    """Consume a bounded job set; assignment and job deletion commit together."""

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
    with _EXECUTION_LOCK:
        if requested_ids is not None:
            with DomainUnitOfWork() as uow:
                inserted = jobs.enqueue_closed_activity_ids(
                    uow.connection,
                    requested_ids,
                )
                if inserted:
                    uow.mark_changed()
        recover_interrupted_inference_jobs()
        return _process_pending_inference_jobs_locked(
            infer_activity,
            normalized_limit,
            activity_ids=requested_ids,
        )


def _process_pending_inference_jobs_locked(
    infer_activity: InferenceCommand,
    limit: int,
    *,
    activity_ids: Iterable[int] | None,
) -> int:
    with get_connection() as conn:
        runnable_ids = jobs.list_runnable_activity_ids(
            conn,
            limit=limit,
            activity_ids=activity_ids,
        )

    completed = 0
    for activity_id in runnable_ids:
        try:
            with DomainUnitOfWork(
                (DataGenerationNamespace.REPORT_STRUCTURE,)
            ) as uow:
                conn = uow.connection
                if not jobs.mark_running(conn, activity_id):
                    continue
                activity = conn.execute(
                    """
                    SELECT end_time, status, is_hidden, is_deleted
                    FROM activity_log
                    WHERE id = ?
                    """,
                    (int(activity_id),),
                ).fetchone()
                if (
                    activity is None
                    or activity["end_time"] is None
                    or str(activity["status"] or "") != "normal"
                    or int(activity["is_hidden"] or 0)
                    or int(activity["is_deleted"] or 0)
                ):
                    jobs.delete_completed_job(conn, activity_id)
                    uow.mark_changed()
                    completed += 1
                    continue
                infer_activity(conn, activity_id)
                if not jobs.delete_completed_job(conn, activity_id):
                    raise RuntimeError("inference_job_completion_lost")
                uow.mark_changed()
                completed += 1
        except Exception as exc:
            logging.exception(
                "activity inference job failed activity_id=%s",
                activity_id,
            )
            _record_failure_safely(activity_id, exc)
    return completed


def _record_failure_safely(activity_id: int, exc: BaseException) -> None:
    try:
        with DomainUnitOfWork() as uow:
            attempts = jobs.record_failure(
                uow.connection,
                activity_id,
                type(exc).__name__,
                at_time=now_str(),
            )
            if attempts:
                uow.mark_changed()
    except Exception:
        logging.exception(
            "activity inference failure state could not be persisted activity_id=%s",
            activity_id,
        )


__all__ = [
    "InferenceCommand",
    "process_pending_inference_jobs",
    "recover_interrupted_inference_jobs",
]
