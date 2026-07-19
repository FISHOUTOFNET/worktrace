from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import datetime, time as datetime_time, timedelta

from ..constants import STATUS_ERROR, TIME_FORMAT
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..write_gate import DATABASE_WRITE_GATE
from . import (
    activity_lifecycle_service,
    project_service,
    session_boundary_service,
    startup_recovery_job_repository,
)
from .runtime_activity_state_service import clear_runtime_activity_state
from .settings_service import get_setting

_SYNC_SEGMENT_LIMIT = 4
_WORKER_SEGMENT_BATCH_SIZE = 7
_WORKER_IDLE_SECONDS = 1.0


def recover_unclosed_records() -> None:
    """Seal open rows with constant startup work and durable long-span progress."""

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
    continuations: list[dict] = []
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
            row_commands, row_boundaries, continuation = _plan_cross_midnight_row(
                row,
                end_dt,
            )
            commands.extend(row_commands)
            boundaries.extend(row_boundaries)
            if continuation is None:
                recovered_at.append(end_dt.strftime(TIME_FORMAT))
            else:
                continuations.append(continuation)
            logging.info(
                "planned cross-midnight recovery id=%s deferred=%s",
                row["id"],
                continuation is not None,
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
    if commands or boundaries or continuations:
        activity_lifecycle_service.recover_activity_batch(
            commands,
            boundaries,
            continuations,
        )
    record_restart_boundary_if_needed()
    clear_runtime_activity_state("recovery_startup_boundary")


def run_startup_recovery_worker(
    stop_event: threading.Event,
    *,
    batch_segments: int = _WORKER_SEGMENT_BATCH_SIZE,
    poll_seconds: float = _WORKER_IDLE_SECONDS,
) -> None:
    """Run bounded durable recovery continuation batches under ``AppRuntime``."""

    limit = max(1, int(batch_segments))
    interval = max(0.1, float(poll_seconds))
    logging.info("startup recovery continuation worker start")
    while not stop_event.is_set():
        if DATABASE_WRITE_GATE.active():
            stop_event.wait(interval)
            continue
        with get_connection() as conn:
            jobs = startup_recovery_job_repository.list_runnable_jobs(
                conn,
                limit=1,
            )
        if not jobs:
            stop_event.wait(interval)
            continue
        job = jobs[0]
        try:
            commands, boundaries, next_cursor, completed = _plan_continuation_batch(
                job,
                limit,
            )
            activity_lifecycle_service.recover_continuation_batch(
                job_id=int(job["id"]),
                commands=commands,
                boundaries=boundaries,
                next_cursor=next_cursor,
                completed=completed,
            )
        except Exception as exc:
            code = _classify_recovery_failure(exc)
            logging.exception(
                "startup recovery continuation failed job_id=%s code=%s",
                job.get("id"),
                code.value,
            )
            _record_recovery_failure_safely(int(job["id"]), code)
            stop_event.wait(interval)
    logging.info("startup recovery continuation worker stop")


def _plan_cross_midnight_row(
    row,
    end_dt: datetime,
) -> tuple[list[dict], list[dict[str, str]], dict | None]:
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
    segment_count = (end_dt.date() - start_dt.date()).days
    if segment_count > _SYNC_SEGMENT_LIMIT:
        continuation = {
            "source_activity_id": int(row["id"]),
            "cursor_time": first_midnight.strftime(TIME_FORMAT),
            "end_time": end_dt.strftime(TIME_FORMAT),
            "source": row["source"],
            "activity_status": row["status"],
            "app_name": row["app_name"],
            "process_name": row["process_name"],
            "window_title": row["window_title"],
            "file_path_hint": row["file_path_hint"],
            "project_id": original_project_id,
        }
        return commands, [], continuation

    boundaries: list[dict[str, str]] = []
    current_start = first_midnight
    while current_start < end_dt:
        next_midnight = datetime.combine(
            current_start.date() + timedelta(days=1),
            datetime_time.min,
        )
        current_end = min(end_dt, next_midnight)
        commands.append(
            _segment_command(
                start_dt=current_start,
                end_dt=current_end,
                source=str(row["source"]),
                status=str(row["status"]),
                app_name=str(row["app_name"] or ""),
                process_name=str(row["process_name"] or ""),
                window_title=str(row["window_title"] or ""),
                file_path_hint=row["file_path_hint"],
                project_id=original_project_id,
            )
        )
        boundaries.append(
            {
                "occurred_at": current_start.strftime(TIME_FORMAT),
                "reason": "midnight",
            }
        )
        current_start = current_end
    return commands, boundaries, None


def _plan_continuation_batch(
    job: dict[str, object],
    limit: int,
) -> tuple[list[dict], list[dict[str, str]], str, bool]:
    current = _parse_time(str(job.get("cursor_time") or ""))
    end_dt = _parse_time(str(job.get("end_time") or ""))
    if current is None or end_dt is None or current >= end_dt:
        raise ValueError("startup_recovery_job_invalid")

    commands: list[dict] = []
    boundaries: list[dict[str, str]] = []
    for _ in range(max(1, int(limit))):
        if current >= end_dt:
            break
        next_midnight = datetime.combine(
            current.date() + timedelta(days=1),
            datetime_time.min,
        )
        current_end = min(end_dt, next_midnight)
        commands.append(
            _segment_command(
                start_dt=current,
                end_dt=current_end,
                source=str(job.get("source") or ""),
                status=str(job.get("activity_status") or ""),
                app_name=str(job.get("app_name") or ""),
                process_name=str(job.get("process_name") or ""),
                window_title=str(job.get("window_title") or ""),
                file_path_hint=job.get("file_path_hint"),
                project_id=job.get("project_id"),
            )
        )
        boundaries.append(
            {
                "occurred_at": current.strftime(TIME_FORMAT),
                "reason": "midnight",
            }
        )
        current = current_end

    completed = current >= end_dt
    if completed:
        boundaries.append(
            {
                "occurred_at": end_dt.strftime(TIME_FORMAT),
                "reason": "recovered",
            }
        )
    return commands, boundaries, current.strftime(TIME_FORMAT), completed


def _segment_command(
    *,
    start_dt: datetime,
    end_dt: datetime,
    source: str,
    status: str,
    app_name: str,
    process_name: str,
    window_title: str,
    file_path_hint,
    project_id,
) -> dict:
    return {
        "kind": "segment",
        "start_time": start_dt.strftime(TIME_FORMAT),
        "end_time": end_dt.strftime(TIME_FORMAT),
        "source": source,
        "status": status,
        "payload": {
            "app_name": app_name,
            "process_name": process_name,
            "window_title": window_title,
            "file_path_hint": file_path_hint,
        },
        "project_id": project_id,
    }


def _classify_recovery_failure(
    exc: BaseException,
) -> startup_recovery_job_repository.RecoveryFailureCode:
    if isinstance(exc, sqlite3.OperationalError):
        sqlite_code = getattr(exc, "sqlite_errorcode", None)
        message = str(exc).strip().lower()
        if sqlite_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED} or message in {
            "database is locked",
            "database table is locked",
            "database is busy",
        }:
            return startup_recovery_job_repository.RecoveryFailureCode.DATABASE_BUSY
        if message == "secure_import_in_progress":
            return startup_recovery_job_repository.RecoveryFailureCode.SECURE_IMPORT_IN_PROGRESS
        if message == "database_generation_changed":
            return startup_recovery_job_repository.RecoveryFailureCode.DATABASE_GENERATION_CHANGED
    return startup_recovery_job_repository.RecoveryFailureCode.UNEXPECTED_FAILURE


def _record_recovery_failure_safely(
    job_id: int,
    code: startup_recovery_job_repository.RecoveryFailureCode,
) -> None:
    try:
        with DomainUnitOfWork() as uow:
            startup_recovery_job_repository.record_failure(
                uow.connection,
                job_id=int(job_id),
                error_code=code,
            )
    except Exception:
        logging.exception(
            "startup recovery failure state could not be persisted job_id=%s",
            job_id,
        )


def record_restart_boundary_if_needed() -> None:
    candidate = _latest_known_shutdown_boundary()
    if not candidate:
        return
    if session_boundary_service.has_boundary_between(candidate, candidate):
        return
    activity_lifecycle_service.close_at_boundary(candidate, "restart")


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


__all__ = [
    "detect_time_jump",
    "mark_record_error",
    "record_restart_boundary_if_needed",
    "recover_unclosed_records",
    "run_startup_recovery_worker",
]
