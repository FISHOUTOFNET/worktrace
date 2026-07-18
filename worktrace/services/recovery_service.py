from __future__ import annotations

import logging
from datetime import datetime, time as datetime_time, timedelta

from ..constants import STATUS_ERROR, TIME_FORMAT
from ..db import get_connection, now_str
from . import activity_lifecycle_service, project_service, session_boundary_service
from .activity_fact_repair_service import (
    get_activity_fact_repair_state,
    repair_missing_activity_resources,
)
from .runtime_activity_state_service import clear_runtime_activity_state
from .settings_service import get_setting


def recover_unclosed_records() -> None:
    heartbeat = get_setting("last_collector_heartbeat", "") or ""
    fallback_now = now_str()
    heartbeat_dt = _parse_time(heartbeat)
    fallback_dt = _parse_time(fallback_now)
    heartbeat_is_valid = bool(
        heartbeat_dt is not None
        and fallback_dt is not None
        and heartbeat_dt <= fallback_dt
    )
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.*, apa.project_id AS assignment_project_id
            FROM activity_log a
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            WHERE a.end_time IS NULL
            ORDER BY a.id
            """
        ).fetchall()

    commands: list[dict] = []
    boundaries: list[dict[str, str]] = []
    recovered_at: list[str] = []
    for row in rows:
        end_time = heartbeat if heartbeat_is_valid else fallback_now
        status = row["status"] if heartbeat_is_valid else STATUS_ERROR
        try:
            duration = int(
                (
                    datetime.strptime(end_time, TIME_FORMAT)
                    - datetime.strptime(row["start_time"], TIME_FORMAT)
                ).total_seconds()
            )
        except ValueError:
            duration = 0
            status = STATUS_ERROR
            end_time = fallback_now
        if duration < 0:
            duration = 0
            status = STATUS_ERROR
            end_time = fallback_now
        start_dt = _parse_time(row["start_time"])
        end_dt = _parse_time(end_time)
        if (
            start_dt
            and end_dt
            and status != STATUS_ERROR
            and end_dt.date() > start_dt.date()
        ):
            row_commands, row_boundaries = _plan_cross_midnight_row(row, end_dt)
            commands.extend(row_commands)
            boundaries.extend(row_boundaries)
            recovered_at.append(end_dt.strftime(TIME_FORMAT))
            logging.info(
                "planned cross-midnight recovery id=%s",
                row["id"],
            )
            continue
        commands.append(
            {
                "kind": "close",
                "activity_id": int(row["id"]),
                "end_time": end_time,
                "duration_seconds": duration,
                "status": status,
            }
        )
        recovered_at.append(end_time)
        logging.info(
            "planned unclosed record recovery id=%s status=%s",
            row["id"],
            status,
        )

    if recovered_at:
        boundaries.append(
            {
                "occurred_at": max(recovered_at),
                "reason": "recovered",
            }
        )
    if commands or boundaries:
        activity_lifecycle_service.recover_activity_batch(commands, boundaries)
    _repair_missing_resource_facts()
    record_restart_boundary_if_needed()
    clear_runtime_activity_state("recovery_startup_boundary")


def _repair_missing_resource_facts() -> None:
    repaired = repair_missing_activity_resources()
    state = get_activity_fact_repair_state()
    logging.info(
        "startup activity resource repair policy=%s status=%s repaired=%s "
        "unknown=%s errors=%s",
        state["policy_version"],
        state["status"],
        repaired,
        state["unknown_count"],
        state["failed_count"],
    )


def _plan_cross_midnight_row(
    row,
    end_dt: datetime,
) -> tuple[list[dict], list[dict[str, str]]]:
    start_dt = datetime.strptime(row["start_time"], TIME_FORMAT)
    first_midnight = datetime.combine(
        start_dt.date() + timedelta(days=1),
        datetime_time.min,
    )
    projected_project_id = row["assignment_project_id"]
    original_project_id = (
        projected_project_id
        if project_service.is_concrete_project_id(projected_project_id)
        else None
    )
    commands: list[dict] = [
        {
            "kind": "close",
            "activity_id": int(row["id"]),
            "end_time": first_midnight.strftime(TIME_FORMAT),
            "duration_seconds": max(
                0,
                int((first_midnight - start_dt).total_seconds()),
            ),
            "status": row["status"],
        }
    ]
    boundaries: list[dict[str, str]] = []
    current_start = first_midnight
    while current_start < end_dt:
        next_midnight = datetime.combine(
            current_start.date() + timedelta(days=1),
            datetime_time.min,
        )
        current_end = min(end_dt, next_midnight)
        commands.append(
            {
                "kind": "segment",
                "start_time": current_start.strftime(TIME_FORMAT),
                "end_time": current_end.strftime(TIME_FORMAT),
                "source": row["source"],
                "status": row["status"],
                "payload": {
                    "app_name": row["app_name"],
                    "process_name": row["process_name"],
                    "window_title": row["window_title"],
                    "file_path_hint": row["file_path_hint"],
                },
                "project_id": original_project_id,
            }
        )
        boundaries.append(
            {
                "occurred_at": current_start.strftime(TIME_FORMAT),
                "reason": "midnight",
            }
        )
        current_start = current_end
    return commands, boundaries


def record_restart_boundary_if_needed() -> None:
    candidate = _latest_known_shutdown_boundary()
    if not candidate:
        return
    if session_boundary_service.has_boundary_between(candidate, candidate):
        return
    session_boundary_service.record_hard_boundary(candidate, "restart")


def _latest_known_shutdown_boundary() -> str | None:
    candidates = [
        get_setting("last_shutdown_at", "") or "",
        get_setting("last_collector_heartbeat", "") or "",
    ]
    parsed: list[tuple[datetime, str]] = []
    for candidate in candidates:
        try:
            parsed.append(
                (
                    datetime.strptime(candidate, TIME_FORMAT),
                    candidate,
                )
            )
        except ValueError:
            continue
    if not parsed:
        return None
    now = datetime.strptime(now_str(), TIME_FORMAT)
    past_candidates = [item for item in parsed if item[0] <= now]
    if not past_candidates:
        return None
    return max(past_candidates, key=lambda item: item[0])[1]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, TIME_FORMAT)
    except ValueError:
        return None


def detect_time_jump(
    last_loop_time: str,
    now: str,
    threshold_seconds: int = 300,
) -> bool:
    try:
        last_dt = datetime.strptime(last_loop_time, TIME_FORMAT)
        now_dt = datetime.strptime(now, TIME_FORMAT)
    except ValueError:
        return True
    return (now_dt - last_dt).total_seconds() > max(1, threshold_seconds)


def mark_record_error(activity_id: int, reason: str) -> None:
    activity_lifecycle_service.mark_activity_error(int(activity_id))
    logging.warning(
        "marked activity id=%s error reason=%s",
        activity_id,
        reason,
    )
