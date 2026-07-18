"""Recoverable, cursor-based history mutations for project rules.

A job row is committed before any history scan begins. Single-rule jobs apply
bounded cursor batches. Multi-rule jobs use durable bounded planning, retain at
most the configured number of winners, and apply the final ordered plan in one
transaction. Rule catalog mutations are delegated to their canonical owner.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import (
    assignment_command_service,
    rule_catalog_command_service as catalog,
    rule_planning_service as planner,
)

_BATCH_SIZE = 100
_BATCH_PLAN_SIZE = 101
_BATCH_MODE = "ordered_rule_batch"
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
    """Commit one durable job before running any bounded history scan."""

    if kind not in {"rule_backfill", "rule_remove", "rule_delete"}:
        raise ValueError("invalid_history_job_kind")
    if rule_type not in {"folder", "keyword"} or type(rule_id) is not int or rule_id <= 0:
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
            estimated: int | None = None
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
        cutoff = _activity_cutoff(read_conn)

    timestamp = now_str()
    restore_enabled = bool(int(rule.get("enabled") or 0))
    payload = {
        "rule_type": rule_type,
        "rule_id": int(rule_id),
        "restore_enabled": restore_enabled,
        "estimated_count": estimated,
    }
    with DomainUnitOfWork() as uow:
        conn = uow.connection
        if kind in {"rule_remove", "rule_delete"} and restore_enabled:
            if not catalog.set_rule_enabled_in_transaction(
                uow,
                conn,
                rule_type,
                int(rule_id),
                False,
                timestamp=timestamp,
            ):
                raise ValueError("not_found")
            rule_version = timestamp
        else:
            current = planner.resolve_rule(conn, rule_type, int(rule_id))
            if not current:
                raise ValueError("not_found")
            rule_version = str(current.get("updated_at") or "")
        job_id = _insert_job(
            conn,
            kind=kind,
            payload=payload,
            cutoff=cutoff,
            timestamp=timestamp,
        )
        _insert_job_rule(
            conn,
            job_id=job_id,
            rule_type=rule_type,
            rule_id=int(rule_id),
            rule_version=rule_version,
        )

    limit = max(0, int(synchronous_limit))
    if limit:
        run_job_batch(job_id, batch_size=min(_BATCH_SIZE, limit))
    return job_result(job_id)


def submit_rule_batch_job(
    rules: list[dict[str, Any]],
    *,
    max_updates: int = 100,
    synchronous_scan_limit: int = _BATCH_PLAN_SIZE,
) -> dict[str, Any]:
    """Commit an ordered batch plan before scanning candidate activities."""

    normalized = _normalize_rule_refs(rules)
    maximum = max(1, int(max_updates))
    with get_connection() as read_conn:
        resolved: list[dict[str, Any]] = []
        for entry in normalized:
            rule = planner.resolve_rule(
                read_conn,
                entry["rule_type"],
                entry["rule_id"],
            )
            if not rule:
                raise ValueError("not_found")
            if not int(rule.get("enabled") or 0):
                raise ValueError("rule_disabled")
            if not planner.project_available(rule):
                raise ValueError("project_not_available")
            resolved.append(rule)
        cutoff = _activity_cutoff(read_conn)

    payload: dict[str, Any] = {
        "mode": _BATCH_MODE,
        "plan_state": "planning",
        "rules": normalized,
        "max_updates": maximum,
        "winners": [],
        "rule_counts": [planner.zero_counts() for _ in normalized],
        "collision_counts": [0 for _ in normalized],
        "updated_by_rule": [0 for _ in normalized],
        "estimated_count": None,
    }
    timestamp = now_str()
    with DomainUnitOfWork() as uow:
        conn = uow.connection
        job_id = _insert_job(
            conn,
            kind="rule_backfill",
            payload=payload,
            cutoff=cutoff,
            timestamp=timestamp,
        )
        for entry, rule in zip(normalized, resolved, strict=True):
            _insert_job_rule(
                conn,
                job_id=job_id,
                rule_type=entry["rule_type"],
                rule_id=entry["rule_id"],
                rule_version=str(rule.get("updated_at") or ""),
            )

    scan_limit = max(0, int(synchronous_scan_limit))
    if scan_limit:
        run_job_batch(job_id, batch_size=scan_limit)
    return batch_job_result(job_id)


def compensate_failed_synchronous_job(job_id: int) -> bool:
    """Remove an unstarted failed job and restore its disabled source rule."""

    if int(job_id) <= 0:
        return False
    with DomainUnitOfWork() as uow:
        conn = uow.connection
        row = conn.execute(
            """
            SELECT kind, payload_json, processed_count
            FROM history_mutation_job
            WHERE id = ? AND status = 'failed'
            """,
            (int(job_id),),
        ).fetchone()
        if row is None or int(row["processed_count"] or 0) != 0:
            return False
        payload = json.loads(str(row["payload_json"] or "{}"))
        if not isinstance(payload, dict) or payload.get("mode") == _BATCH_MODE:
            return False
        rule_type = str(payload.get("rule_type") or "")
        rule_id = int(payload.get("rule_id") or 0)
        if row["kind"] in {"rule_remove", "rule_delete"} and bool(
            payload.get("restore_enabled")
        ):
            if not catalog.set_rule_enabled_in_transaction(
                uow,
                conn,
                rule_type,
                rule_id,
                True,
            ):
                return False
        conn.execute(
            "DELETE FROM history_mutation_job WHERE id = ?",
            (int(job_id),),
        )
    return True


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
    """Run one bounded batch; progress and durable facts commit together."""

    with _JOB_EXECUTION_LOCK:
        job = _load_job(job_id)
        if job is None:
            raise ValueError("history_job_not_found")
        payload = _payload(job)
        if job["status"] not in {"pending", "running"}:
            return _result_for_job(job_id, payload)
        try:
            if payload.get("mode") == _BATCH_MODE:
                _run_ordered_batch_plan(job, payload, batch_size)
            elif job["kind"] == "rule_backfill":
                _run_backfill_batch(job, batch_size)
            else:
                _run_reinference_batch(job, batch_size)
        except Exception as exc:
            logging.exception("history mutation job failed id=%s", job_id)
            _fail_job(job_id, str(exc))
        latest = _load_job(job_id)
        if latest is None:
            raise ValueError("history_job_not_found")
        return _result_for_job(job_id, _payload(latest))


def job_result(job_id: int) -> dict[str, Any]:
    job = _load_job(job_id)
    if job is None:
        raise ValueError("history_job_not_found")
    payload = _payload(job)
    if payload.get("mode") == _BATCH_MODE:
        return batch_job_result(job_id)
    estimated = payload.get("estimated_count")
    return {
        "job_id": int(job["id"]),
        "status": str(job["status"]),
        "queued": str(job["status"]) in {"pending", "running"},
        "updated_count": int(job["changed_count"] or 0),
        "matched_count": int(job["changed_count"] or 0),
        "skipped_count": int(job["skipped_count"] or 0),
        "processed_count": int(job["processed_count"] or 0),
        "estimated_count": int(estimated) if estimated is not None else None,
        "affected_dates": 0,
        "error": str(job["error_message"] or ""),
    }


def batch_job_result(job_id: int) -> dict[str, Any]:
    job = _load_job(job_id)
    if job is None:
        raise ValueError("history_job_not_found")
    payload = _payload(job)
    if payload.get("mode") != _BATCH_MODE:
        raise ValueError("history_job_not_batch")
    refs = list(payload.get("rules") or [])
    counts_list = _coerce_rule_counts(payload, len(refs))
    collisions = _coerce_int_list(payload.get("collision_counts"), len(refs))
    updated = _coerce_int_list(payload.get("updated_by_rule"), len(refs))
    rules_result: list[dict[str, Any]] = []
    with get_connection() as conn:
        for index, entry in enumerate(refs):
            rule = planner.resolve_rule(
                conn,
                str(entry["rule_type"]),
                int(entry["rule_id"]),
            )
            summary = (
                planner.rule_summary(
                    rule,
                    str(entry["rule_type"]),
                    available=planner.project_available(rule),
                )
                if rule
                else {
                    "kind": str(entry["rule_type"]),
                    "id": int(entry["rule_id"]),
                    "enabled": False,
                    "project_id": 0,
                    "project_name": "",
                    "target": "",
                    "project_available": False,
                    "version": "",
                }
            )
            counts = dict(counts_list[index])
            counts["collision_skipped_count"] = collisions[index]
            counts["updated_count"] = updated[index]
            rules_result.append({"rule": summary, "counts": counts})
    aggregate = planner.zero_counts()
    for counts in counts_list:
        for key in aggregate:
            aggregate[key] += int(counts.get(key) or 0)
    aggregate["would_update_count"] = len(payload.get("winners") or [])
    aggregate["collision_skipped_count"] = sum(collisions)
    aggregate["updated_count"] = int(job["changed_count"] or 0)
    error = str(job["error_message"] or "")
    return {
        "job_id": int(job["id"]),
        "status": str(job["status"]),
        "queued": str(job["status"]) in {"pending", "running"},
        "rules": rules_result,
        "counts": aggregate,
        "too_many_matches": error == "too_many_matches",
        "error": error,
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
    limit = max(1, int(batch_size))
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
            limit=limit,
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
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
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
        completed = len(activities) < limit or last_id >= int(
            job["cutoff_activity_id"] or 0
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


def _run_ordered_batch_plan(
    job: dict,
    payload: dict[str, Any],
    batch_size: int,
) -> None:
    refs = list(payload.get("rules") or [])
    if not refs:
        raise ValueError("invalid_history_job_payload")
    limit = max(1, int(batch_size))
    counts_list = _coerce_rule_counts(payload, len(refs))
    collision_counts = _coerce_int_list(payload.get("collision_counts"), len(refs))
    winners = {
        int(item[0]): int(item[1])
        for item in list(payload.get("winners") or [])
        if isinstance(item, list) and len(item) == 2
    }
    with get_connection() as read_conn:
        versions = _job_rule_versions(read_conn, int(job["id"]))
        resolved = _resolve_job_rules(read_conn, refs, versions)
        activities = planner.load_candidate_activities(
            read_conn,
            after_id=int(job["cursor_activity_id"] or 0),
            cutoff_id=int(job["cutoff_activity_id"] or 0),
            limit=limit,
        )
        classified_list = [
            planner.classify_activities(
                read_conn,
                activities,
                rule,
                str(entry["rule_type"]),
            )
            for entry, rule in zip(refs, resolved, strict=True)
        ]
    if not activities:
        _apply_ordered_batch_plan(
            job,
            payload,
            refs,
            versions,
            winners,
            counts_list,
            collision_counts,
            0,
            0,
        )
        return

    for index, classified in enumerate(classified_list):
        for key in planner.zero_counts():
            counts_list[index][key] += int(classified.get(key) or 0)
        for activity in list(classified.get("would_update") or []):
            activity_id = int(activity.get("id") or 0)
            if activity_id in winners:
                collision_counts[index] += 1
            else:
                winners[activity_id] = index
                if len(winners) > int(payload.get("max_updates") or 100):
                    raise ValueError("too_many_matches")

    last_id = max(int(item["id"]) for item in activities)
    completed = len(activities) < limit or last_id >= int(
        job["cutoff_activity_id"] or 0
    )
    if completed:
        _apply_ordered_batch_plan(
            job,
            payload,
            refs,
            versions,
            winners,
            counts_list,
            collision_counts,
            last_id,
            len(activities),
        )
        return

    payload["winners"] = [
        [activity_id, index] for activity_id, index in sorted(winners.items())
    ]
    payload["rule_counts"] = counts_list
    payload["collision_counts"] = collision_counts
    with DomainUnitOfWork() as uow:
        uow.connection.execute(
            """
            UPDATE history_mutation_job
            SET status = 'running', payload_json = ?, cursor_activity_id = ?,
                processed_count = processed_count + ?, error_message = NULL,
                updated_at = ?
            WHERE id = ? AND status IN ('pending', 'running')
            """,
            (
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                last_id,
                len(activities),
                now_str(),
                int(job["id"]),
            ),
        )


def _apply_ordered_batch_plan(
    job: dict,
    payload: dict[str, Any],
    refs: list[dict[str, Any]],
    versions: dict[tuple[str, int], str],
    winners: dict[int, int],
    counts_list: list[dict[str, int]],
    collision_counts: list[int],
    cursor: int,
    processed: int,
) -> None:
    updated_by_rule = [0 for _ in refs]
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        conn = uow.connection
        current_rules = _resolve_job_rules(conn, refs, versions)
        for activity_id, index in sorted(winners.items()):
            entry = refs[index]
            rule = current_rules[index]
            rule_type = str(entry["rule_type"])
            source = "folder_rule" if rule_type == "folder" else "keyword_rule"
            confidence = (
                planner.FOLDER_RULE_CONFIDENCE
                if rule_type == "folder"
                else planner.KEYWORD_RULE_CONFIDENCE
            )
            changed = assignment_command_service.upsert_assignment(
                conn,
                activity_id=int(activity_id),
                project_id=int(rule.get("project_id") or 0),
                confidence=confidence,
                source=source,
                source_rule_type=rule_type,
                source_rule_id=int(entry["rule_id"]),
                protect_manual=True,
            )
            if not changed:
                raise ValueError("operation_failed")
            updated_by_rule[index] += 1
        payload["plan_state"] = "completed"
        payload["winners"] = [
            [activity_id, index] for activity_id, index in sorted(winners.items())
        ]
        payload["rule_counts"] = counts_list
        payload["collision_counts"] = collision_counts
        payload["updated_by_rule"] = updated_by_rule
        conn.execute(
            """
            UPDATE history_mutation_job
            SET status = 'completed', payload_json = ?, cursor_activity_id = ?,
                processed_count = processed_count + ?, changed_count = ?,
                skipped_count = ?, error_message = NULL, updated_at = ?
            WHERE id = ? AND status IN ('pending', 'running')
            """,
            (
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                int(cursor),
                int(processed),
                sum(updated_by_rule),
                0,
                now_str(),
                int(job["id"]),
            ),
        )


def _run_reinference_batch(job: dict, batch_size: int) -> None:
    payload = _payload(job)
    rule_type = str(payload["rule_type"])
    rule_id = int(payload["rule_id"])
    limit = max(1, int(batch_size))
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
                limit,
            ),
        ).fetchall()
    if not rows:
        _finalize_reinference_job(job)
        return

    from .project_inference_service import assign_project_for_activity_in_transaction

    activity_ids = [int(row["activity_id"]) for row in rows]
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        conn = uow.connection
        for activity_id in activity_ids:
            assign_project_for_activity_in_transaction(
                conn,
                activity_id,
                exclude_rule=(rule_type, rule_id),
            )
        last_id = activity_ids[-1]
        completed = len(activity_ids) < limit or last_id >= int(
            job["cutoff_activity_id"] or 0
        )
        if completed:
            _finalize_rule_in_transaction(uow, conn, job, payload)
        _advance_job(
            conn,
            job_id=int(job["id"]),
            cursor=last_id,
            processed=len(activity_ids),
            changed=len(activity_ids),
            skipped=0,
            completed=completed,
        )


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
    with DomainUnitOfWork() as uow:
        conn = uow.connection
        _finalize_rule_in_transaction(uow, conn, job, payload)
        conn.execute(
            """
            UPDATE history_mutation_job
            SET status = 'completed', error_message = NULL, updated_at = ?
            WHERE id = ? AND status IN ('pending', 'running')
            """,
            (now_str(), int(job["id"])),
        )


def _finalize_rule_in_transaction(
    uow: DomainUnitOfWork,
    conn,
    job: dict,
    payload: dict[str, Any],
) -> None:
    rule_type = str(payload["rule_type"])
    rule_id = int(payload["rule_id"])
    if job["kind"] == "rule_delete":
        if rule_type == "folder":
            from .folder_index_service import delete_index_for_rule

            delete_index_for_rule(rule_id, conn=conn)
        if not catalog.delete_rule_in_transaction(
            uow,
            conn,
            rule_type,
            rule_id,
        ):
            raise ValueError("rule_delete_failed")
    elif bool(payload.get("restore_enabled")):
        if not catalog.set_rule_enabled_in_transaction(
            uow,
            conn,
            rule_type,
            rule_id,
            True,
        ):
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


def _fail_job(job_id: int, message: str) -> None:
    with DomainUnitOfWork() as uow:
        uow.connection.execute(
            """
            UPDATE history_mutation_job
            SET status = 'failed', error_message = ?, updated_at = ?
            WHERE id = ? AND status IN ('pending', 'running')
            """,
            (str(message)[:500], now_str(), int(job_id)),
        )


def _insert_job(
    conn,
    *,
    kind: str,
    payload: dict[str, Any],
    cutoff: int,
    timestamp: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO history_mutation_job(
            kind, status, payload_json, cutoff_activity_id,
            cursor_activity_id, processed_count, changed_count,
            skipped_count, error_message, created_at, updated_at
        ) VALUES (?, 'pending', ?, ?, 0, 0, 0, 0, NULL, ?, ?)
        """,
        (
            kind,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            int(cutoff),
            timestamp,
            timestamp,
        ),
    )
    return int(cursor.lastrowid)


def _insert_job_rule(
    conn,
    *,
    job_id: int,
    rule_type: str,
    rule_id: int,
    rule_version: str,
) -> None:
    conn.execute(
        """
        INSERT INTO history_mutation_job_rule(
            job_id, rule_type, rule_id, rule_version
        ) VALUES (?, ?, ?, ?)
        """,
        (int(job_id), str(rule_type), int(rule_id), str(rule_version)),
    )


def _activity_cutoff(conn) -> int:
    return int(
        conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS value FROM activity_log"
        ).fetchone()["value"]
        or 0
    )


def _normalize_rule_refs(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs = catalog.normalize_rule_refs(rules)
    return [
        {"rule_type": rule_type, "rule_id": rule_id}
        for rule_type, rule_id in refs
    ]


def _resolve_job_rules(
    conn,
    refs: list[dict[str, Any]],
    versions: dict[tuple[str, int], str],
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for entry in refs:
        rule_type = str(entry["rule_type"])
        rule_id = int(entry["rule_id"])
        rule = planner.resolve_rule(conn, rule_type, rule_id)
        if not rule:
            raise ValueError("not_found")
        if str(rule.get("updated_at") or "") != versions.get((rule_type, rule_id), ""):
            raise ValueError("rule_changed_during_history_job")
        if not int(rule.get("enabled") or 0):
            raise ValueError("rule_disabled")
        if not planner.project_available(rule):
            raise ValueError("project_not_available")
        resolved.append(rule)
    return resolved


def _coerce_rule_counts(
    payload: dict[str, Any],
    length: int,
) -> list[dict[str, int]]:
    raw = list(payload.get("rule_counts") or [])
    result: list[dict[str, int]] = []
    for index in range(length):
        source = raw[index] if index < len(raw) and isinstance(raw[index], dict) else {}
        result.append(
            {key: int(source.get(key) or 0) for key in planner.zero_counts()}
        )
    return result


def _coerce_int_list(value: Any, length: int) -> list[int]:
    raw = list(value or []) if isinstance(value, list) else []
    return [int(raw[index] or 0) if index < len(raw) else 0 for index in range(length)]


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


def _job_rule_versions(conn, job_id: int) -> dict[tuple[str, int], str]:
    rows = conn.execute(
        """
        SELECT rule_type, rule_id, rule_version
        FROM history_mutation_job_rule
        WHERE job_id = ?
        """,
        (int(job_id),),
    ).fetchall()
    return {
        (str(row["rule_type"]), int(row["rule_id"])): str(row["rule_version"] or "")
        for row in rows
    }


def _payload(job: dict) -> dict[str, Any]:
    value = json.loads(str(job.get("payload_json") or "{}"))
    if not isinstance(value, dict):
        raise ValueError("invalid_history_job_payload")
    return value


def _result_for_job(job_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    return batch_job_result(job_id) if payload.get("mode") == _BATCH_MODE else job_result(job_id)


__all__ = [
    "batch_job_result",
    "compensate_failed_synchronous_job",
    "job_result",
    "run_job_batch",
    "run_job_to_completion",
    "run_pending_jobs",
    "start_history_worker",
    "submit_rule_batch_job",
    "submit_rule_job",
]
