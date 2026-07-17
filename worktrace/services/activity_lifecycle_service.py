"""Activity lifecycle command boundary.

Every durable lifecycle transition is committed in one SQLite transaction.
Project inference remains a post-commit, retryable derivation and can never
prevent the caller from receiving an already-created activity id.
"""

from __future__ import annotations

import logging
from typing import Any

from ..constants import STATUS_NORMAL, UNCATEGORIZED_PROJECT
from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import activity_fact_repository


def _report_uow() -> DomainUnitOfWork:
    return DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,))


def _mark_inference_retry_safely(activity_id: int) -> None:
    try:
        from .assignment_command_service import mark_inference_retry

        with _report_uow() as uow:
            row = uow.connection.execute(
                "SELECT id FROM project WHERE name = ?",
                (UNCATEGORIZED_PROJECT,),
            ).fetchone()
            if row is None:
                return
            mark_inference_retry(uow.connection, activity_id, int(row["id"]))
            uow.mark_changed()
    except Exception:
        logging.exception(
            "close-finalize inference retry marker failed for activity_id=%s",
            activity_id,
        )


def finalize_closed_activity_ids(closed_ids: list[int]) -> None:
    """Run project inference after the close transaction has committed."""

    if not closed_ids:
        return
    from .project_inference_service import process_new_activity

    for activity_id in closed_ids:
        try:
            process_new_activity(activity_id)
        except Exception:
            logging.exception(
                "close-finalize inference failed for activity_id=%s",
                activity_id,
            )
            _mark_inference_retry_safely(activity_id)


def start_activity(*, start_time: str, source: str, payload: dict[str, Any]) -> int:
    """Atomically close the prior open row and create the replacement."""

    prepared = activity_fact_repository.prepare_activity(
        start_time=start_time,
        source=source,
        payload=payload,
    )
    with _report_uow() as uow:
        closed_ids = activity_fact_repository.close_all_open_activities(
            uow.connection,
            start_time,
        )
        activity_id = activity_fact_repository.insert_open_activity(
            uow.connection,
            prepared,
        )
        uow.mark_changed()
    finalize_closed_activity_ids(closed_ids)
    _sync_open_row_project_safely(activity_id, status=prepared.status)
    return activity_id


def persist_open_activity(
    *, start_time: str, source: str, payload: dict[str, Any]
) -> int:
    """Create one open fact and return its id immediately after commit."""

    prepared = activity_fact_repository.prepare_activity(
        start_time=start_time,
        source=source,
        payload=payload,
    )
    with _report_uow() as uow:
        activity_id = activity_fact_repository.insert_open_activity(
            uow.connection,
            prepared,
        )
        uow.mark_changed()
    _sync_open_row_project_safely(activity_id, status=prepared.status)
    return activity_id


def force_persist_open_activity_for_clipboard(
    *, start_time: str, source: str, payload: dict[str, Any]
) -> int | None:
    if payload.get("status") != STATUS_NORMAL:
        return None
    return persist_open_activity(
        start_time=start_time,
        source=source,
        payload=payload,
    )


def checkpoint_activity(activity_id: int, duration_seconds: int) -> bool:
    """Persist a monotonic crash-recovery checkpoint without cache invalidation."""

    with DomainUnitOfWork() as uow:
        changed = activity_fact_repository.checkpoint_activity_duration(
            uow.connection,
            activity_id,
            duration_seconds,
        )
        if changed:
            uow.mark_changed()
        return changed


def close_activity(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
) -> None:
    with _report_uow() as uow:
        changed = activity_fact_repository.close_activity(
            uow.connection,
            activity_id,
            end_time,
            duration_seconds=duration_seconds,
        )
        if changed:
            uow.mark_changed()
    if changed:
        finalize_closed_activity_ids([int(activity_id)])


def close_all_open_activities(end_time: str | None = None) -> list[int]:
    requested_end = end_time or now_str()
    with _report_uow() as uow:
        closed_ids = activity_fact_repository.close_all_open_activities(
            uow.connection,
            requested_end,
        )
        if closed_ids:
            uow.mark_changed()
    finalize_closed_activity_ids(closed_ids)
    return closed_ids


def persist_midnight_anchor(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
    project_id: int,
) -> int:
    prepared = activity_fact_repository.prepare_activity(
        start_time=start_time,
        source=source,
        payload=payload,
        initial_project_id=int(project_id),
        assignment_source="midnight_anchor",
        assignment_confidence=90,
    )
    with _report_uow() as uow:
        activity_id = activity_fact_repository.insert_open_activity(
            uow.connection,
            prepared,
        )
        uow.mark_changed()
    return activity_id


def recover_close_activity(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
    status: str | None = None,
) -> None:
    with _report_uow() as uow:
        changed = activity_fact_repository.close_activity(
            uow.connection,
            activity_id,
            end_time,
            duration_seconds=duration_seconds,
            status=status,
        )
        if changed:
            uow.mark_changed()
    if changed:
        finalize_closed_activity_ids([int(activity_id)])


def recover_cross_midnight_segment(
    *,
    start_time: str,
    end_time: str,
    source: str,
    status: str,
    payload: dict[str, Any],
    project_id: int | None = None,
) -> int:
    prepared = activity_fact_repository.prepare_activity(
        start_time=start_time,
        source=source,
        payload={**payload, "status": status},
        initial_project_id=(
            int(project_id)
            if status == STATUS_NORMAL and project_id is not None
            else None
        ),
        assignment_source=(
            "midnight_anchor"
            if status == STATUS_NORMAL and project_id is not None
            else None
        ),
        assignment_confidence=(
            90 if status == STATUS_NORMAL and project_id is not None else None
        ),
    )
    with _report_uow() as uow:
        activity_id = activity_fact_repository.insert_open_activity(
            uow.connection,
            prepared,
        )
        activity_fact_repository.close_activity(
            uow.connection,
            activity_id,
            end_time,
        )
        uow.mark_changed()
    finalize_closed_activity_ids([activity_id])
    return activity_id


def recover_first_half_close(
    activity_id: int,
    end_time: str,
    duration_seconds: int,
) -> None:
    close_activity(
        activity_id,
        end_time,
        duration_seconds=duration_seconds,
    )


def _sync_open_row_project_safely(
    activity_id: int,
    *,
    status: str | None,
) -> None:
    if status != STATUS_NORMAL:
        return
    from .project_inference_service import sync_persisted_open_activity_project

    try:
        sync_persisted_open_activity_project(activity_id)
    except Exception:
        logging.exception(
            "open-row project sync failed for activity_id=%s",
            activity_id,
        )


__all__ = [
    "checkpoint_activity",
    "close_activity",
    "close_all_open_activities",
    "finalize_closed_activity_ids",
    "force_persist_open_activity_for_clipboard",
    "persist_midnight_anchor",
    "persist_open_activity",
    "recover_close_activity",
    "recover_cross_midnight_segment",
    "recover_first_half_close",
    "start_activity",
]
