"""Recoverable, cursor-based history mutations for project rules."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from ..constants import EXCLUDED_PROJECT
from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import assignment_command_service, rule_planning_service as planner

_BATCH_SIZE = 100
_WORKER_IDLE_SECONDS = 2.0
_WORKER_LOCK = threading.Lock()
_JOB_EXECUTION_LOCK = threading.RLock()
_WORKER_THREAD: threading.Thread | None = None


def submit_rule_job(
    kind: str,
    rule_type: str,
    rule_id: int,
    *,
    synchronous_limit: int = 100,
) -> dict[str, Any]:
    """Create one durable job and finish small workloads immediately."""

    if kind not in {"rule_backfill", "rule_remove", "rule_delete"}:
        raise ValueError("invalid_history_job_kind")
    if rule_type not in {"folder", "keyword"} or int(rule_id) <= 0:
        raise ValueError("not_found")

    with get_connection() as read_conn:
        rule = planner.resolve_rule(read_conn, rule_type, int(rule_id))
        if not rule:
            raise ValueError("not_found")
        if kind == "rule_backfill":
            if not int(rule.get("enabled") or 0):
                raise ValueError("rule_disabled")
            if not planner.project_available(rule):
                raise ValueError("project_not_available")
            classified = planner.classify_activities(
                read_conn,
                planner.load_candidate_activities(read_conn),
                rule,
                rule_type,
            )
            estimated = int(classified.get("would_update_count") or 0)
        else:
            estimated = int(
                read_conn.execute(
                    """
                    SELECT COUNT(*) AS value
                    FROM activity_project_assignment
                    WHERE is_manual = 0
                      AND source_rule_type = ?
                      AND source_rule_id = ?
                    """,
                    (rule_type, int(rule_id)),
                ).fetchone()["value"]
                or 0
            )
        cutoff = int(
            read_conn.execute(
                "SELECT COALESCE(MAX(id), 0) AS value FROM activity_log"
            ).fetchone()["value"]
            or 0
        )

    timestamp = now_str()
    payload = {
        "rule_type": rule_type,
        "rule_id": int(rule_id),
        "restore_enabled": bool(int(rule.get("enabled") or 0)),
        "estimated_count": estimated,
    }
    with DomainUnitOfWork() as uow:
        conn = uow.connection
        if kind in {"rule_remove", "rule_delete"}:
            if int(rule.get("enabled") or 0):
                uow.add_effects(DataGenerationNamespace.CLASSIFICATION_CATALOG)
                if str(rule.get("project_name") or "") == EXCLUDED_PROJECT:
                    uow.add_effects(DataGenerationNamespace.PRIVACY_CATALOG)
            table, extra = _rule_table(rule_type)
            cursor = conn.execute(
                f"UPDATE {table} SET enabled = 0, updated_at = ? WHERE id = ?{extra}",
                (timestamp, int(rule_id)),
            )
            if cursor.rowcount != 1:
                raise ValueError("not_found")
            rule_version = timestamp
        else:
            rule_version = str(rule.get("updated_at") or "")
        cursor = conn.execute(
            """
            INSERT INTO history_mutation_job(
                kind, status, payload_json, cutoff_activity_id,
                cursor_activity_id, processed_count, changed_count,
                skipped_count, error_message, created_at, updated_at
            )
            VALUES (?, 'pending', ?, ?, 0, 0, 0, 0, NULL, ?, ?)
            """,
            (
                kind,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                cutoff,
                timestamp,
                timestamp,
            ),
        )
        job_id = int(cursor.lastrowid)
        conn.execute(
            """
            INSERT INTO history_mutation_job_rule(
                job_id, rule_type, rule_id, rule_version
            ) VALUES (?, ?, ?, ?)
            """,
            (job_id, rule_type, int(rule_id), rule_version),
        )

    _invalidate_rule_caches(rule_type)
    if estimated <= max(0, int(synchronous_limit)):
        run_job_to_completion(job_id)
    return job_result(job_id)


def run_pending_jobs(limit: int = 1) -> int:
    with get_connection() as conn:
        ids = [
            int(row["id"])
            for row in conn.execute(
                """
                SELECT id
                FROM history_mutation_job
                WHERE status IN ('pending', 'running')
                ORDER BY created_at, id
                LIMIT ?
                """,
                (max(0, int(limit)),),
            ).fetchall()
        ]
    for job_id in ids:
        run_job_batch(job_id)
    return len(ids)


def run_job_to_completion(
    job_id: int,
    max_batches: int = 10000,
) -> dict[str, Any]:
    for _ in range(max(1, int(max_batches))):
        result = run_job_batch(job_id)
        if result["status"] not in {"pending", "running"}:
            return result
    raise RuntimeError("history_job_batch_limit")


def run_job_batch(job_id: int, batch_size: int = _BATCH_SIZE) -> dict[str, Any]:
    """Run one bounded batch; progress and facts commit in one transaction."""

    with _JOB_EXECUTION_LOCK:
        job = _load_job(job_id)
        if job is None:
            raise ValueError("history_job_not_found")
        if job["status"] not in {"pending", "running"}:
            return job_result(job_id)
        try:
            if job["kind"] == "rule_backfill":
                _run_backfill_batch(job, batch_size)
            else:
                _run_reinference_batch(job, batch_size)
        except Exception as exc:
            logging.exception("history mutation job failed id=%s", job_id)
            with DomainUnitOfWork() as uow:
                uow.connection.execute(
                    """
                    UPDATE history_mutation_job
                    SET status = 'failed', error_message = ?, updated_at = ?
                    WHERE id = ? AND status IN ('pending', 'running')
                    """,
                    (str(exc)[:500], now_str(), int(job_id)),
                )
        return job_result(job_id)


def job_result(job_id: int) -> dict[str, Any]:
    job = _load_job(job_id)
    if job is None:
        raise ValueError("history_job_not_found")
    payload = _payload(job)
    return {
        "job_id": int(job["id"]),
        "status": str(job["status"]),
        "queued": str(job["status"]) in {"pending", "running"},
        "updated_count": int(job["changed_count"] or 0),
        "matched_count": int(job["changed_count"] or 0),
        "skipped_count": int(job["skipped_count"] or 0),
        "processed_count": int(job["processed_count"] or 0),
        "estimated_count": int(payload.get("estimated_count") or 0),
        "affected_dates": 0,
        "error": str(job["error_message"] or ""),
    }


def start_history_worker(stop_event: threading.Event) -> threading.Thread | None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is not None and _WORKER_THREAD.is_alive():
            return _WORKER_THREAD
        _WORKER_THREAD = threading.Thread(
            target=_worker_loop,
            args=(stop_event,),
            name="WorkTraceHistoryMutation",
            daemon=True,
        )
        _WORKER_THREAD.start()
        return _WORKER_THREAD


def _worker_loop(stop_event: threading.Event) -> None:
    logging.info("history mutation worker start")
    while not stop_event.is_set():
        try:
            from .secure_backup_service import is_secure_import_in_progress

            if not is_secure_import_in_progress() and run_pending_jobs(limit=1):
                continue
        except Exception:
            logging.exception("history mutation worker error")
        stop_event.wait(_WORKER_IDLE_SECONDS)
    logging.info("history mutation worker stop")


def _run_backfill_batch(job: dict, batch_size: int) -> None:
    payload = _payload(job)
    rule_type = str(payload["rule_type"])
    rule_id = int(payload["rule_id"])
    with get_connection() as read_conn:
        rule = planner.resolve_rule(read_conn, rule_type, rule_id)
        if not rule:
            raise ValueError("not_found")
        expected_version = _job_rule_version(read_conn, int(job["id"]))
        if str(rule.get("updated_at") or "") != expected_version:
            raise ValueError("rule_changed_during_history_job")
        activities = planner.load_candidate_activities(
            read_conn,
            after_id=int(job["cursor_activity_id"] or 0),
            cutoff_id=int(job["cutoff_activity_id"] or 0),
            limit=max(1, int(batch_size)),
        )
        classified = planner.classify_activities(
            read_conn,
            activities,
            rule,
            rule_type,
        )
    if not activities:
        _complete_job(int(job["id"]))
        return

    source = "folder_rule" if rule_type == "folder" else "keyword_rule"
    confidence = (
        planner.FOLDER_RULE_CONFIDENCE
        if rule_type == "folder"
        else planner.KEYWORD_RULE_CONFIDENCE
    )
    updates = list(classified.get("would_update") or [])
    last_id = max(int(item["id"]) for item in activities)
    changed = 0
    with DomainUnitOfWork(
        (DataGenerationNamespace.REPORT_STRUCTURE,)
    ) as uow:
        conn = uow.connection
        current = planner.resolve_rule(conn, rule_type, rule_id)
        if not current or str(current.get("updated_at") or "") != expected_version:
            raise ValueError("rule_changed_during_history_job")
        for activity in updates:
            if assignment_command_service.upsert_assignment(
                conn,
                activity_id=int(activity["id"]),
                project_id=int(rule.get("project_id") or 0),
                confidence=confidence,
                source=source,
                source_rule_type=rule_type,
                source_rule_id=rule_id,
                protect_manual=True,
            ):
                changed += 1
        completed = (
            len(activities) < max(1, int(batch_size))
            or last_id >= int(job["cutoff_activity_id"] or 0)
        )
        _advance_job(
            conn,
            job_id=int(job["id"]),
            cursor=last_id,
            processed=len(activities),
            changed=changed,
            skipped=max(0, len(activities) - changed),
            completed=completed,
        )


def _run_reinference_batch(job: dict, batch_size: int) -> None:
    payload = _payload(job)
    rule_type = str(payload["rule_type"])
    rule_id = int(payload["rule_id"])
    with get_connection() as read_conn:
        rows = read_conn.execute(
            """
            SELECT activity_id
            FROM activity_project_assignment
            WHERE is_manual = 0
              AND source_rule_type = ?
              AND source_rule_id = ?
              AND activity_id > ?
              AND activity_id <= ?
            ORDER BY activity_id
            LIMIT ?
            """,
            (
                rule_type,
                rule_id,
                int(job["cursor_activity_id"] or 0),
                int(job["cutoff_activity_id"] or 0),
                max(1, int(batch_size)),
            ),
        ).fetchall()
    if not rows:
        _finalize_reinference_job(job)
        return

    from .project_inference_service import assign_project_for_activity_in_transaction

    activity_ids = [int(row["activity_id"]) for row in rows]
    with DomainUnitOfWork(
        (DataGenerationNamespace.REPORT_STRUCTURE,)
    ) as uow:
        conn = uow.connection
        changed = 0
        for activity_id in activity_ids:
            assign_project_for_activity_in_transaction(
                conn,
                activity_id,
                exclude_rule=(rule_type, rule_id),
            )
            changed += 1
        last_id = activity_ids[-1]
        completed = (
            len(activity_ids) < max(1, int(batch_size))
            or last_id >= int(job["cutoff_activity_id"] or 0)
        )
        if completed:
            _add_finalization_effects(uow, conn, job, payload)
            _finalize_rule_in_transaction(conn, job, payload)
        _advance_job(
            conn,
            job_id=int(job["id"]),
            cursor=last_id,
            processed=len(activity_ids),
            changed=changed,
            skipped=0,
            completed=completed,
        )
    if completed:
        _invalidate_rule_caches(rule_type)


def _advance_job(
    conn,
    *,
    job_id: int,
    cursor: int,
    processed: int,
    changed: int,
    skipped: int,
    completed: bool,
) -> None:
    conn.execute(
        """
        UPDATE history_mutation_job
        SET status = ?, cursor_activity_id = ?,
            processed_count = processed_count + ?,
            changed_count = changed_count + ?,
            skipped_count = skipped_count + ?,
            error_message = NULL, updated_at = ?
        WHERE id = ? AND status IN ('pending', 'running')
        """,
        (
            "completed" if completed else "running",
            int(cursor),
            int(processed),
            int(changed),
            int(skipped),
            now_str(),
            int(job_id),
        ),
    )


def _finalize_reinference_job(job: dict) -> None:
    payload = _payload(job)
    rule_type = str(payload["rule_type"])
    with DomainUnitOfWork() as uow:
        conn = uow.connection
        _add_finalization_effects(uow, conn, job, payload)
        _finalize_rule_in_transaction(conn, job, payload)
        conn.execute(
            """
            UPDATE history_mutation_job
            SET status = 'completed', error_message = NULL, updated_at = ?
            WHERE id = ? AND status IN ('pending', 'running')
            """,
            (now_str(), int(job["id"])),
        )
    _invalidate_rule_caches(rule_type)


def _add_finalization_effects(
    uow: DomainUnitOfWork,
    conn,
    job: dict,
    payload: dict[str, Any],
) -> None:
    changes_rule = job["kind"] == "rule_delete" or bool(
        payload.get("restore_enabled")
    )
    if not changes_rule:
        return
    rule = planner.resolve_rule(
        conn,
        str(payload["rule_type"]),
        int(payload["rule_id"]),
    )
    uow.add_effects(DataGenerationNamespace.CLASSIFICATION_CATALOG)
    if rule and str(rule.get("project_name") or "") == EXCLUDED_PROJECT:
        uow.add_effects(DataGenerationNamespace.PRIVACY_CATALOG)


def _finalize_rule_in_transaction(conn, job: dict, payload: dict[str, Any]) -> None:
    rule_type = str(payload["rule_type"])
    rule_id = int(payload["rule_id"])
    table, extra = _rule_table(rule_type)
    if job["kind"] == "rule_delete":
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE id = ?{extra}",
            (rule_id,),
        )
        if cursor.rowcount != 1:
            raise ValueError("rule_delete_failed")
    elif bool(payload.get("restore_enabled")):
        cursor = conn.execute(
            f"UPDATE {table} SET enabled = 1, updated_at = ? WHERE id = ?{extra}",
            (now_str(), rule_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("rule_restore_failed")


def _complete_job(job_id: int) -> None:
    with DomainUnitOfWork() as uow:
        uow.connection.execute(
            """
            UPDATE history_mutation_job
            SET status = 'completed', error_message = NULL, updated_at = ?
            WHERE id = ? AND status IN ('pending', 'running')
            """,
            (now_str(), int(job_id)),
        )


def _load_job(job_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM history_mutation_job WHERE id = ?",
            (int(job_id),),
        ).fetchone()
    return dict(row) if row else None


def _job_rule_version(conn, job_id: int) -> str:
    row = conn.execute(
        "SELECT rule_version FROM history_mutation_job_rule WHERE job_id = ?",
        (int(job_id),),
    ).fetchone()
    return str(row["rule_version"] or "") if row else ""


def _payload(job: dict) -> dict[str, Any]:
    value = json.loads(str(job.get("payload_json") or "{}"))
    if not isinstance(value, dict):
        raise ValueError("invalid_history_job_payload")
    return value


def _rule_table(rule_type: str) -> tuple[str, str]:
    if rule_type == "folder":
        return "folder_project_rule", ""
    return "project_rule", " AND rule_type = 'keyword'"


def _invalidate_rule_caches(rule_type: str) -> None:
    if rule_type == "folder":
        from .folder_rule_service import invalidate_folder_rule_cache

        invalidate_folder_rule_cache()
    else:
        from .project_inference_service import invalidate_keyword_rule_cache

        invalidate_keyword_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()


__all__ = [
    "job_result",
    "run_job_batch",
    "run_job_to_completion",
    "run_pending_jobs",
    "start_history_worker",
    "submit_rule_job",
]
