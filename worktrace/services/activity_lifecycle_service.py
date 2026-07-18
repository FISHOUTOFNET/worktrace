"""Activity lifecycle command boundary.

Every durable lifecycle transition is committed in one SQLite transaction.
Eligible closed activities receive a durable inference job in that same
transaction; post-commit processing is only a latency optimization.
"""

from __future__ import annotations

import logging
from typing import Any

from ..constants import STATUS_ERROR, STATUS_NORMAL
from ..data_generation_repository import DataGenerationNamespace
from ..db import now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import (
    activity_fact_repository,
    activity_inference_job_repository,
    session_boundary_service,
)
from .settings_service import set_settings_in_transaction


def _report_uow() -> DomainUnitOfWork:
    return DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,))


def _enqueue_closed_inference_jobs(conn, closed_ids: list[int]) -> int:
    return activity_inference_job_repository.enqueue_closed_activity_ids(
        conn,
        closed_ids,
    )


def finalize_closed_activity_ids(closed_ids: list[int] | None) -> None:
    """Best-effort immediate consumption of already-durable inference jobs."""

    if not closed_ids:
        return
    normalized = sorted({int(activity_id) for activity_id in closed_ids})
    from .project_inference_service import process_pending_inference_jobs

    try:
        process_pending_inference_jobs(
            limit=len(normalized),
            activity_ids=normalized,
        )
    except Exception:
        logging.exception(
            "close-finalize inference worker failed for activity_ids=%s",
            normalized,
        )


def start_activity(*, start_time: str, source: str, payload: dict[str, Any]) -> int:
    prepared = activity_fact_repository.prepare_activity(
        start_time=start_time,
        source=source,
        payload=payload,
    )
    with _report_uow() as uow:
        conn = uow.connection
        closed_ids = activity_fact_repository.close_all_open_activities(
            conn,
            start_time,
        )
        activity_id = activity_fact_repository.insert_open_activity(
            conn,
            prepared,
        )
        _enqueue_closed_inference_jobs(conn, closed_ids)
        uow.mark_changed()
    finalize_closed_activity_ids(closed_ids)
    _sync_open_row_project_safely(activity_id, status=prepared.status)
    return activity_id


def persist_open_activity(
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
) -> int:
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
    *,
    start_time: str,
    source: str,
    payload: dict[str, Any],
) -> int | None:
    if payload.get("status") != STATUS_NORMAL:
        return None
    return persist_open_activity(
        start_time=start_time,
        source=source,
        payload=payload,
    )


def checkpoint_activity(activity_id: int, duration_seconds: int) -> bool:
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
        conn = uow.connection
        changed = activity_fact_repository.close_activity(
            conn,
            activity_id,
            end_time,
            duration_seconds=duration_seconds,
        )
        if changed:
            _enqueue_closed_inference_jobs(conn, [int(activity_id)])
            uow.mark_changed()
    if changed:
        finalize_closed_activity_ids([int(activity_id)])


def close_all_open_activities(end_time: str | None = None) -> list[int]:
    requested_end = end_time or now_str()
    with _report_uow() as uow:
        conn = uow.connection
        closed_ids = activity_fact_repository.close_all_open_activities(
            conn,
            requested_end,
        )
        if closed_ids:
            _enqueue_closed_inference_jobs(conn, closed_ids)
            uow.mark_changed()
    finalize_closed_activity_ids(closed_ids)
    return closed_ids


def close_at_boundary(
    occurred_at: str,
    reason: str,
    *,
    current_activity_id: int | None = None,
    current_duration_seconds: int | None = None,
) -> list[int]:
    requested_at = str(occurred_at or now_str())
    closed_ids: list[int] = []
    with _report_uow() as uow:
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
        _enqueue_closed_inference_jobs(conn, closed_ids)
        session_boundary_service.insert_boundary(conn, requested_at, reason)
        uow.mark_changed()
    finalize_closed_activity_ids(closed_ids)
    return closed_ids


def pause_collection(
    occurred_at: str | None = None,
    *,
    reason: str = "user_pause",
    current_activity_id: int | None = None,
    current_duration_seconds: int | None = None,
) -> list[int]:
    """Atomically seal activity facts, record the pause, and persist pause state."""

    requested_at = str(occurred_at or now_str())
    closed_ids: list[int] = []
    with _report_uow() as uow:
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

        _enqueue_closed_inference_jobs(conn, closed_ids)
        paused_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'user_paused'"
        ).fetchone()
        already_paused = bool(
            paused_row
            and str(paused_row["value"] or "").strip().casefold() == "true"
        )
        changed = bool(closed_ids)
        if closed_ids or not already_paused:
            session_boundary_service.insert_boundary(conn, requested_at, reason)
            changed = True

        if set_settings_in_transaction(
            uow,
            conn,
            {
                "user_paused": "true",
                "collector_status": "paused",
            },
        ):
            changed = True
        if changed:
            uow.mark_changed()

    finalize_closed_activity_ids(closed_ids)
    from .runtime_activity_state_service import clear_runtime_activity_state

    clear_runtime_activity_state(reason)
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


def recover_activity_batch(
    commands: list[dict[str, Any]],
    boundaries: list[dict[str, str]],
) -> dict[str, list[int]]:
    """Commit all startup recovery activity facts and boundaries atomically."""

    closed_ids: list[int] = []
    created_ids: list[int] = []
    changed = False
    with _report_uow() as uow:
        conn = uow.connection
        for command in commands:
            kind = str(command.get("kind") or "")
            if kind == "close":
                activity_id = int(command["activity_id"])
                if activity_fact_repository.close_activity(
                    conn,
                    activity_id,
                    str(command["end_time"]),
                    duration_seconds=int(command.get("duration_seconds") or 0),
                    status=str(command.get("status") or "") or None,
                ):
                    closed_ids.append(activity_id)
                    changed = True
                continue
            if kind != "segment":
                raise ValueError("invalid_recovery_command")
            status = str(command.get("status") or STATUS_NORMAL)
            project_id = command.get("project_id")
            prepared = activity_fact_repository.prepare_activity(
                start_time=str(command["start_time"]),
                source=str(command["source"]),
                payload={**dict(command.get("payload") or {}), "status": status},
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
            activity_id = activity_fact_repository.insert_open_activity(conn, prepared)
            if not activity_fact_repository.close_activity(
                conn,
                activity_id,
                str(command["end_time"]),
            ):
                raise ValueError("recovery_segment_close_failed")
            created_ids.append(activity_id)
            closed_ids.append(activity_id)
            changed = True
        _enqueue_closed_inference_jobs(conn, closed_ids)
        for boundary in boundaries:
            session_boundary_service.insert_boundary(
                conn,
                str(boundary["occurred_at"]),
                str(boundary["reason"]),
            )
            changed = True
        if changed:
            uow.mark_changed()
    finalize_closed_activity_ids(closed_ids)
    return {"closed_ids": closed_ids, "created_ids": created_ids}


def mark_activity_error(activity_id: int) -> bool:
    """Move one durable activity to error status through the lifecycle owner."""

    with _report_uow() as uow:
        cursor = uow.connection.execute(
            """
            UPDATE activity_log
            SET status = ?, updated_at = ?
            WHERE id = ? AND status IS NOT ?
            """,
            (STATUS_ERROR, now_str(), int(activity_id), STATUS_ERROR),
        )
        changed = cursor.rowcount == 1
        if changed:
            uow.mark_changed()
        return changed


def recover_close_activity(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
    status: str | None = None,
) -> None:
    recover_activity_batch(
        [
            {
                "kind": "close",
                "activity_id": int(activity_id),
                "end_time": end_time,
                "duration_seconds": int(duration_seconds or 0),
                "status": status,
            }
        ],
        [],
    )


def recover_cross_midnight_segment(
    *,
    start_time: str,
    end_time: str,
    source: str,
    status: str,
    payload: dict[str, Any],
    project_id: int | None = None,
) -> int:
    result = recover_activity_batch(
        [
            {
                "kind": "segment",
                "start_time": start_time,
                "end_time": end_time,
                "source": source,
                "status": status,
                "payload": payload,
                "project_id": project_id,
            }
        ],
        [],
    )
    return int(result["created_ids"][0])


def recover_first_half_close(
    activity_id: int,
    end_time: str,
    duration_seconds: int,
) -> None:
    recover_close_activity(
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
    "close_at_boundary",
    "finalize_closed_activity_ids",
    "force_persist_open_activity_for_clipboard",
    "mark_activity_error",
    "persist_midnight_anchor",
    "persist_open_activity",
    "pause_collection",
    "recover_activity_batch",
    "recover_close_activity",
    "recover_cross_midnight_segment",
    "recover_first_half_close",
    "start_activity",
]
