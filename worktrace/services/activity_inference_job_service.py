"""Bounded consumer for durable closed-activity inference jobs."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import activity_inference_job_repository as jobs
from . import project_inference_service


def recover_interrupted_inference_jobs() -> int:
    """Return any committed running rows to pending after process interruption."""

    with DomainUnitOfWork() as uow:
        changed = jobs.recover_interrupted_jobs(uow.connection)
        if changed:
            uow.mark_changed()
        return changed


def process_pending_inference_jobs(
    limit: int = 100,
    *,
    activity_ids: Iterable[int] | None = None,
) -> int:
    """Consume a bounded job set; assignment and job deletion commit together."""

    normalized_limit = max(0, int(limit))
    if normalized_limit == 0:
        return 0
    with get_connection() as conn:
        runnable_ids = jobs.list_runnable_activity_ids(
            conn,
            limit=normalized_limit,
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
                project_inference_service.assign_project_for_activity_in_transaction(
                    conn,
                    activity_id,
                )
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
    "process_pending_inference_jobs",
    "recover_interrupted_inference_jobs",
]
