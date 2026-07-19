"""Atomic activity seal used only by runtime maintenance quiescence."""
from __future__ import annotations

from ..data_generation_repository import DataGenerationNamespace
from ..db import now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import activity_fact_repository, activity_inference_job_repository


def seal_open_activity_for_maintenance(
    occurred_at: str | None = None,
    *,
    current_activity_id: int | None = None,
    current_duration_seconds: int | None = None,
) -> list[int]:
    """Close the current durable segment without creating a session boundary.

    Activity closure and inference-job creation commit in the same report UoW.
    The command deliberately does not mutate ``user_paused`` or collector
    settings; maintenance is not a user-observable pause transition.
    """

    requested_at = str(occurred_at or now_str())
    closed_ids: list[int] = []
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        conn = uow.connection
        if current_activity_id is not None and activity_fact_repository.close_activity(
            conn,
            int(current_activity_id),
            requested_at,
            duration_seconds=current_duration_seconds,
        ):
            closed_ids.append(int(current_activity_id))
        for activity_id in activity_fact_repository.close_all_open_activities(
            conn,
            requested_at,
        ):
            if activity_id not in closed_ids:
                closed_ids.append(activity_id)
        if closed_ids:
            activity_inference_job_repository.enqueue_closed_activity_ids(
                conn,
                closed_ids,
            )
            uow.mark_changed()
    return closed_ids


__all__ = ["seal_open_activity_for_maintenance"]
