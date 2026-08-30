"""Versioned, restartable repair of durable activity-resource facts."""

from __future__ import annotations

import logging
import threading
from typing import Any

from ..constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED
from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..platforms.base import ActiveWindow
from ..resources.detectors import detect_resource
from ..resources.resource_builders import make_system_resource
from ..resources.types import DetectedResource
from ..retry_state import RetryEpisode
from ..worker_health import WorkerHealthReporter
from ..write_gate import DATABASE_WRITE_GATE
from .resource_service import create_or_update_activity_resource

DEFAULT_BATCH_SIZE = 200
REPAIR_POLICY_VERSION = 2
_WORKER_IDLE_SECONDS = 1.0
_VALID_STATUSES = {"pending", "running", "completed", "failed"}


def _default_state() -> dict[str, Any]:
    return {
        "policy_version": REPAIR_POLICY_VERSION,
        "status": "pending",
        "cursor_activity_id": 0,
        "processed_count": 0,
        "repaired_count": 0,
        "unknown_count": 0,
        "failed_count": 0,
        "last_error": "",
        "started_at": "",
        "completed_at": "",
        "updated_at": "",
    }


def get_activity_fact_repair_state(*, conn=None) -> dict[str, Any]:
    """Return validated durable repair progress for diagnostics and runtime gates."""

    if conn is None:
        with get_connection() as read_conn:
            return get_activity_fact_repair_state(conn=read_conn)
    row = conn.execute(
        "SELECT * FROM activity_resource_repair_job WHERE singleton_id = 1",
    ).fetchone()
    if row is None:
        return _default_state()
    if int(row["policy_version"] or 0) != REPAIR_POLICY_VERSION:
        return _default_state()
    status = str(row["status"] or "")
    if status not in _VALID_STATUSES:
        raise ValueError("data_repair_state_invalid")
    state = _default_state()
    state.update(
        {
            "status": status,
            "cursor_activity_id": max(0, int(row["cursor_activity_id"] or 0)),
            "processed_count": max(0, int(row["processed_count"] or 0)),
            "repaired_count": max(0, int(row["repaired_count"] or 0)),
            "unknown_count": max(0, int(row["unknown_count"] or 0)),
            "failed_count": max(0, int(row["failed_count"] or 0)),
            "last_error": str(row["last_error"] or ""),
            "started_at": str(row["started_at"] or ""),
            "completed_at": str(row["completed_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }
    )
    return state


def repair_missing_activity_resources(batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Repair at most one deterministic batch and persist its durable cursor."""

    size = max(1, int(batch_size))
    try:
        state = get_activity_fact_repair_state()
    except ValueError:
        logging.exception("activity resource repair state was invalid; restarting policy")
        state = _default_state()

    # Once the current policy sweep is complete, only genuinely missing durable
    # facts are eligible. This keeps future detector changes from rewriting
    # history while still repairing newly missing rows.
    if state["status"] == "completed":
        rows = _load_missing_rows_after(0, size)
        if not rows:
            return 0
        return _repair_rows(rows, state, policy_sweep=False)

    cursor = int(state["cursor_activity_id"])
    rows = _load_policy_rows_after(cursor, size)
    if not rows:
        _mark_state_completed(state)
        return 0
    return _repair_rows(rows, state, policy_sweep=True)


def _repair_rows(
    rows: list[dict[str, Any]],
    state: dict[str, Any],
    *,
    policy_sweep: bool,
) -> int:
    if not rows:
        return 0

    if policy_sweep:
        state["status"] = "running"
        state["started_at"] = str(state["started_at"] or now_str())
        state["completed_at"] = ""
    state["last_error"] = ""

    try:
        prepared: list[
            tuple[int, DetectedResource, bool, bool, bool]
        ] = []
        for row in rows:
            resource, detection_failed = _resource_for_row(row)
            has_existing = _has_persisted_resource(row)
            should_write = (
                not has_existing
                or (
                    not detection_failed
                    and _resource_identity_changed(row, resource)
                )
            )
            prepared.append(
                (
                    int(row["id"]),
                    resource,
                    should_write and resource.resource_kind == "unknown",
                    detection_failed,
                    should_write,
                )
            )

        changed_count = sum(
            1
            for _activity_id, _resource, _is_unknown, _failed, should_write
            in prepared
            if should_write
        )

        with DomainUnitOfWork(
            (DataGenerationNamespace.REPORT_STRUCTURE,)
        ) as uow:
            conn = uow.connection
            for activity_id, resource, _is_unknown, _failed, should_write in prepared:
                if should_write:
                    create_or_update_activity_resource(
                        activity_id,
                        resource,
                        conn=conn,
                    )
            if policy_sweep:
                state["cursor_activity_id"] = int(prepared[-1][0])
            state["processed_count"] = int(state["processed_count"]) + len(prepared)
            state["repaired_count"] = int(state["repaired_count"]) + changed_count
            state["unknown_count"] = int(state["unknown_count"]) + sum(
                1
                for _activity_id, _resource, is_unknown, _failed, _should_write
                in prepared
                if is_unknown
            )
            state["failed_count"] = int(state["failed_count"]) + sum(
                1
                for _activity_id, _resource, _is_unknown, failed, _should_write
                in prepared
                if failed
            )
            _write_state(conn, state)
            if changed_count:
                uow.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)

        if policy_sweep and not _load_policy_rows_after(
            int(state["cursor_activity_id"]),
            1,
        ):
            _mark_state_completed(state)

        logging.info(
            "activity resource repair committed policy=%s batch=%s changed=%s total=%s cursor=%s status=%s",
            REPAIR_POLICY_VERSION,
            len(prepared),
            changed_count,
            state["repaired_count"],
            state["cursor_activity_id"],
            state["status"],
        )
        return len(prepared)
    except Exception as exc:
        state["status"] = "failed"
        state["last_error"] = _failure_code(exc)
        try:
            _persist_state(state)
        except Exception:
            logging.exception("activity resource repair failure state could not be persisted")
        raise


def _mark_state_completed(state: dict[str, Any]) -> None:
    state["status"] = "completed"
    state["completed_at"] = now_str()
    state["last_error"] = ""
    _persist_state(state)


def run_activity_resource_repair_worker(
    stop_event: threading.Event,
    *,
    health: WorkerHealthReporter,
    batch_size: int = DEFAULT_BATCH_SIZE,
    poll_seconds: float = _WORKER_IDLE_SECONDS,
) -> None:
    """Run iterations only; AppRuntime owns thread started/stopped state."""

    size = max(1, int(batch_size))
    interval = max(0.1, float(poll_seconds))
    retry_episode = RetryEpisode()
    logging.info("activity resource repair worker loop enter")
    while not stop_event.is_set():
        if DATABASE_WRITE_GATE.writes_blocked():
            health.maintenance_paused(True)
            stop_event.wait(interval)
            continue
        health.maintenance_paused(False)
        try:
            repaired = repair_missing_activity_resources(size)
        except Exception:
            retry = retry_episode.failed("activity_resource_repair_iteration_failed")
            health.failed("activity_resource_repair_iteration_failed")
            if retry.detail_log_due:
                logging.warning(
                    "activity resource repair worker iteration failed",
                    exc_info=True,
                )
            elif retry.summary_log_due:
                logging.warning(
                    "activity resource repair worker failure continues consecutive=%s elapsed_seconds=%.1f",
                    retry.attempt,
                    retry.elapsed_seconds,
                )
            stop_event.wait(max(interval, retry.delay_seconds))
            continue
        recovery = retry_episode.succeeded()
        health.succeeded()
        if recovery.recovered:
            logging.info(
                "activity resource repair worker recovered attempts=%s elapsed_seconds=%.1f",
                recovery.attempts,
                recovery.elapsed_seconds,
            )
        if repaired >= size:
            continue
        stop_event.wait(interval)
    logging.info("activity resource repair worker loop exit")


def require_activity_fact_repair_complete() -> dict[str, Any]:
    """Fail closed while durable resource facts or their repair state are incomplete."""

    state = get_activity_fact_repair_state()
    if state["status"] != "completed" or _first_unrepaired_activity_id() is not None:
        raise ValueError("data_repair_required")
    return state


def clear_all_jobs_in_transaction(conn) -> int:
    """Clear repair progress without committing the caller-owned transaction."""

    cursor = conn.execute("DELETE FROM activity_resource_repair_job")
    return max(0, int(cursor.rowcount or 0))


def _failure_code(exc: BaseException) -> str:
    if (
        isinstance(exc, RuntimeError)
        and str(exc) == "activity_resource_repair_cursor_inconsistent"
    ):
        return "cursor_inconsistent"
    return "repair_failed"


def _persist_state(state: dict[str, Any]) -> None:
    # Worker progress is durable operational state, not a user-visible report
    # semantic effect. The transaction commits without publishing a generation.
    with DomainUnitOfWork() as uow:
        _write_state(uow.connection, state)


def _write_state(conn, state: dict[str, Any]) -> None:
    state["updated_at"] = now_str()
    conn.execute(
        """
        INSERT INTO activity_resource_repair_job(
            singleton_id, policy_version, status, cursor_activity_id,
            processed_count, repaired_count, failed_count, unknown_count,
            last_error, started_at, completed_at, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton_id) DO UPDATE SET
            policy_version = excluded.policy_version,
            status = excluded.status,
            cursor_activity_id = excluded.cursor_activity_id,
            processed_count = excluded.processed_count,
            repaired_count = excluded.repaired_count,
            failed_count = excluded.failed_count,
            unknown_count = excluded.unknown_count,
            last_error = excluded.last_error,
            started_at = excluded.started_at,
            completed_at = excluded.completed_at,
            updated_at = excluded.updated_at
        """,
        (
            REPAIR_POLICY_VERSION,
            state["status"],
            int(state["cursor_activity_id"]),
            int(state["processed_count"]),
            int(state["repaired_count"]),
            int(state["failed_count"]),
            int(state["unknown_count"]),
            str(state["last_error"]),
            str(state["started_at"]),
            str(state["completed_at"]),
            state["updated_at"],
        ),
    )


def _first_unrepaired_activity_id() -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT MIN(a.id) AS activity_id
            FROM activity_log a
            LEFT JOIN activity_resource ar ON ar.activity_id = a.id
            WHERE ar.activity_id IS NULL
               OR TRIM(COALESCE(ar.identity_key, '')) = ''
            """
        ).fetchone()
    if row is None or row["activity_id"] is None:
        return None
    return int(row["activity_id"])


def _load_policy_rows_after(
    cursor_activity_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Load one policy-v2 sweep batch.

    Policy v2 re-evaluates existing Edge browser resources exactly once so
    browser-owned profile suffixes can be removed from durable identity. Other
    already-persisted resource kinds are not revisited.
    """

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.app_name, a.process_name, a.window_title,
                   a.file_path_hint, a.start_time, a.status,
                   ar.activity_id AS existing_resource_activity_id,
                   ar.resource_kind AS existing_resource_kind,
                   ar.resource_subtype AS existing_resource_subtype,
                   ar.display_name AS existing_display_name,
                   ar.identity_key AS existing_identity_key
            FROM activity_log a
            LEFT JOIN activity_resource ar ON ar.activity_id = a.id
            WHERE a.id > ?
              AND (
                    ar.activity_id IS NULL
                 OR TRIM(COALESCE(ar.identity_key, '')) = ''
                 OR (
                        LOWER(TRIM(COALESCE(a.process_name, ''))) IN ('msedge.exe', 'msedge')
                    AND ar.resource_kind = 'browser_tab'
                 )
              )
            ORDER BY a.id
            LIMIT ?
            """,
            (max(0, int(cursor_activity_id)), int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def _load_missing_rows_after(
    cursor_activity_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.app_name, a.process_name, a.window_title,
                   a.file_path_hint, a.start_time, a.status,
                   ar.activity_id AS existing_resource_activity_id,
                   ar.resource_kind AS existing_resource_kind,
                   ar.resource_subtype AS existing_resource_subtype,
                   ar.display_name AS existing_display_name,
                   ar.identity_key AS existing_identity_key
            FROM activity_log a
            LEFT JOIN activity_resource ar ON ar.activity_id = a.id
            WHERE (ar.activity_id IS NULL OR TRIM(COALESCE(ar.identity_key, '')) = '')
              AND a.id > ?
            ORDER BY a.id
            LIMIT ?
            """,
            (max(0, int(cursor_activity_id)), int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def _has_persisted_resource(row: dict[str, Any]) -> bool:
    return bool(
        row.get("existing_resource_activity_id") is not None
        and str(row.get("existing_identity_key") or "").strip()
    )


def _resource_identity_changed(
    row: dict[str, Any],
    resource: DetectedResource,
) -> bool:
    return any(
        (
            str(row.get("existing_resource_kind") or "") != resource.resource_kind,
            str(row.get("existing_resource_subtype") or "") != resource.resource_subtype,
            str(row.get("existing_display_name") or "") != resource.display_name,
            str(row.get("existing_identity_key") or "") != resource.identity_key,
        )
    )


def _resource_for_row(row: dict[str, Any]) -> tuple[DetectedResource, bool]:
    status = str(row.get("status") or "")
    app_name = str(row.get("app_name") or "")
    process_name = str(row.get("process_name") or "")
    window_title = str(row.get("window_title") or "")
    if status == STATUS_EXCLUDED:
        return make_system_resource(STATUS_EXCLUDED), False
    if status in {STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR}:
        return make_system_resource(status, app_name, process_name, window_title), False
    try:
        resource = detect_resource(
            ActiveWindow(
                app_name=app_name,
                process_name=process_name,
                window_title=window_title,
                file_path_hint=row.get("file_path_hint"),
                activity_start_time=str(row.get("start_time") or "") or None,
            )
        )
        if not str(resource.identity_key or "").strip():
            logging.warning(
                "activity resource repair produced empty identity activity_id=%s policy=%s",
                int(row.get("id") or 0),
                REPAIR_POLICY_VERSION,
            )
            return _unknown_resource(row), True
        return resource, False
    except Exception:
        logging.exception(
            "activity resource repair detection failed activity_id=%s policy=%s",
            int(row.get("id") or 0),
            REPAIR_POLICY_VERSION,
        )
        return _unknown_resource(row), True


def _unknown_resource(row: dict[str, Any]) -> DetectedResource:
    activity_id = int(row.get("id") or 0)
    app_name = str(row.get("app_name") or "")
    process_name = str(row.get("process_name") or "")
    display_name = app_name or process_name or "未知"
    return DetectedResource(
        resource_kind="unknown",
        resource_subtype="unknown",
        display_name=display_name,
        identity_key=f"activity:{activity_id}",
        is_anchor=False,
        confidence=0,
        source=f"repair_v{REPAIR_POLICY_VERSION}_unknown",
        app_name=app_name,
        process_name=process_name,
        window_title="",
    )


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "REPAIR_POLICY_VERSION",
    "clear_all_jobs_in_transaction",
    "get_activity_fact_repair_state",
    "repair_missing_activity_resources",
    "require_activity_fact_repair_complete",
    "run_activity_resource_repair_worker",
]
