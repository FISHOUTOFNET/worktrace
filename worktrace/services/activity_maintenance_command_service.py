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
    settings; maintenance is not a user-observable pause transition. Once the
    Collector has acknowledged a seal, repeated maintenance polling has no
    durable command to execute and therefore performs no write attempt.
    """

    if current_activity_id is None:
        return []
    requested_at = str(occurred_at or now_str())
    activity_id = int(current_activity_id)
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        conn = uow.connection
        changed = activity_fact_repository.close_activity(
            conn,
            activity_id,
            requested_at,
            duration_seconds=current_duration_seconds,
        )
        if not changed:
            return []
        activity_inference_job_repository.enqueue_closed_activity_ids(
            conn,
            [activity_id],
        )
        uow.mark_changed()
    return [activity_id]


__all__ = ["seal_open_activity_for_maintenance"]
