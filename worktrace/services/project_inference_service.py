"""Public project-inference facade with durable closed-row orchestration."""

from __future__ import annotations

from collections.abc import Iterable

from ..db import get_connection
from . import project_inference_core as _core

for _name in _core.__all__:
    globals()[_name] = getattr(_core, _name)


def process_pending_inference_jobs(
    limit: int = 100,
    *,
    activity_ids: Iterable[int] | None = None,
) -> int:
    """Consume durable jobs through the bounded transactional worker."""

    from .activity_inference_job_service import process_pending_inference_jobs as consume

    return consume(
        _core.assign_project_for_activity_in_transaction,
        limit=max(0, int(limit)),
        activity_ids=activity_ids,
    )


def process_new_activity(activity_id: int) -> dict:
    """Use the outbox for closed rows and direct synchronization for open rows."""

    normalized = int(activity_id)
    with get_connection() as conn:
        activity = conn.execute(
            """
            SELECT end_time, is_hidden, is_deleted
            FROM activity_log
            WHERE id = ?
            """,
            (normalized,),
        ).fetchone()
    if activity is None:
        raise ValueError(f"activity not found: {normalized}")
    if activity["end_time"] is None:
        return _core.process_new_activity(normalized)

    process_pending_inference_jobs(limit=1, activity_ids=[normalized])
    with get_connection() as conn:
        job_exists = conn.execute(
            "SELECT 1 FROM activity_inference_job WHERE activity_id = ?",
            (normalized,),
        ).fetchone()
    if job_exists is not None:
        return _core.get_assignment_for_activity(normalized)
    if int(activity["is_hidden"] or 0) or int(activity["is_deleted"] or 0):
        return _core.get_assignment_for_activity(normalized)
    return _core.get_assignment_for_activity(normalized)


def retry_pending_inference(limit: int = 100) -> int:
    """Compatibility entry point for the runtime startup opportunity."""

    return process_pending_inference_jobs(limit=max(0, int(limit)))


__all__ = sorted(
    set(_core.__all__)
    | {
        "process_new_activity",
        "process_pending_inference_jobs",
        "retry_pending_inference",
    }
)
