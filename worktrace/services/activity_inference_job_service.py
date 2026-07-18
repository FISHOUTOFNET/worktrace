"""Bounded consumer for durable closed-activity inference obligations."""

from __future__ import annotations

import logging
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
            logging.error(
                "activity inference job failed activity_id=%s code=%s",
                activity_id,
                type(exc).__name__,
            )
            _record_failure_safely(activity_id, type(exc).__name__)
    return completed


def _record_failure_safely(activity_id: int, error_code: str) -> None:
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
    except Exception as exc:
        logging.error(
            "activity inference failure state unavailable activity_id=%s code=%s",
            activity_id,
            type(exc).__name__,
        )


__all__ = ["InferenceCommand", "process_pending_inference_jobs"]
