"""Transactional unit of work for immutable report mutations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from ..db import get_connection, now_str
from . import project_lifecycle_policy
from .report_projection_identity import member_identity_key, stable_json_hash
from .report_projection_model import (
    DatabaseBusyError,
    InvalidInputError,
    MutationResult,
    OperationNotAllowedError,
    ProjectNotSelectableError,
    RequestIdConflictError,
    RevisionConflictError,
    SessionNotAdjacentError,
    StaleSelectionError,
    TargetRevisionConflictError,
)
from .report_session_operation_engine import APPLIED, OPERATION_PAYLOAD_VERSION


def edit_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str, *, project_id: int | None, adjusted_duration_seconds: int | None, note: str) -> MutationResult:
    return _run_uow(
        report_date, request_id, "edit_session", projection_instance_key,
        expected_projection_revision,
        payload_input={"project_id": project_id, "adjusted_duration_seconds": adjusted_duration_seconds, "note": note},
    )


def hide_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str) -> MutationResult:
    return _run_uow(report_date, request_id, "hide_session", projection_instance_key, expected_projection_revision)


def merge_session(report_date: str, projection_instance_key: str, direction: str, request_id: str, *, expected_projection_revision: str, target_projection_instance_key: str, target_expected_projection_revision: str) -> MutationResult:
    return _run_uow(
        report_date, request_id, "merge_sessions", projection_instance_key,
        expected_projection_revision,
        target_instance_key=target_projection_instance_key,
        target_expected_revision=target_expected_projection_revision,
        direction=direction,
    )


def split_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str) -> MutationResult:
    return _run_uow(report_date, request_id, "split_session", projection_instance_key, expected_projection_revision)


def copy_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str) -> MutationResult:
    return _run_uow(report_date, request_id, "copy_session", projection_instance_key, expected_projection_revision)


def hide_session_activity(report_date: str, projection_instance_key: str, summary_id: str, expected_projection_revision: str, request_id: str) -> MutationResult:
    return _run_uow(
        report_date, request_id, "hide_activity", projection_instance_key,
        expected_projection_revision, payload_input={"summary_id": summary_id},
    )


def load_operations(report_date: str, *, conn=None) -> list[dict[str, Any]]:
    if conn is None:
        with get_connection() as read_conn:
            return load_operations(report_date, conn=read_conn)
    rows = conn.execute(
        "SELECT * FROM report_session_operation WHERE report_date = ? ORDER BY sequence, id",
        (report_date,),
    ).fetchall()
    return [_inflate_operation(conn, dict(row)) for row in rows]


def _run_uow(
    report_date: str,
    request_id: str,
    operation_type: str,
    source_instance_key: str,
    source_expected_revision: str,
    *,
    target_instance_key: str | None = None,
    target_expected_revision: str | None = None,
    direction: str | None = None,
    payload_input: Mapping[str, Any] | None = None,
) -> MutationResult:
    if not request_id or not report_date or not source_instance_key or not source_expected_revision:
        raise InvalidInputError()
    intent = {
        "report_date": report_date,
        "operation_type": operation_type,
        "source_instance_key": source_instance_key,
        "source_expected_revision": source_expected_revision,
        "target_instance_key": target_instance_key,
        "target_expected_revision": target_expected_revision,
        "direction": direction,
        "payload_input": dict(payload_input or {}),
    }
    input_signature = stable_json_hash(intent)
    with get_connection() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            receipt = _find_request(conn, request_id)
            if receipt is not None:
                if str(receipt["input_signature"]) != input_signature:
                    raise RequestIdConflictError()
                result = _mutation_result_from_receipt(receipt)
                conn.commit()
                return result

            from .report_projection_snapshot_service import build_visible_snapshot

            before = build_visible_snapshot(report_date, report_date, conn=conn)
            source = _find_entry(before.final_sessions, source_instance_key)
            if source is None:
                raise StaleSelectionError()
            if str(source.get("projection_revision") or "") != source_expected_revision:
                raise RevisionConflictError()
            target = None
            if operation_type == "merge_sessions":
                if direction not in {"previous", "next"} or not target_instance_key or not target_expected_revision:
                    raise InvalidInputError()
                target = _find_entry(before.final_sessions, target_instance_key)
                if target is None:
                    raise StaleSelectionError()
                if str(target.get("projection_revision") or "") != target_expected_revision:
                    raise TargetRevisionConflictError()
                _require_adjacent(before.final_sessions, source, target, direction)
            _require_capability(operation_type, source, direction)

            payload, roles, undo_of = _operation_input(conn, operation_type, source, target, dict(payload_input or {}))
            sequence = _next_sequence(conn, report_date)
            conn.execute("SAVEPOINT report_operation")
            operation_id = _insert_operation(
                conn,
                report_date=report_date,
                sequence=sequence,
                operation_type=operation_type,
                source_instance_key=source_instance_key,
                source_expected_revision=source_expected_revision,
                target_instance_key=target_instance_key,
                target_expected_revision=target_expected_revision,
                direction=direction,
                undo_of_operation_id=undo_of,
                payload=payload,
            )
            _insert_members(conn, operation_id, roles)
            after = build_visible_snapshot(report_date, report_date, conn=conn)
            diagnostic = next(
                (item for item in after.operation_diagnostics if item.operation_id == operation_id),
                None,
            )
            effective = bool(diagnostic and diagnostic.state == APPLIED and _expected_effect(operation_type, operation_id, before, after, source))
            if not effective:
                conn.execute("ROLLBACK TO report_operation")
                conn.execute("RELEASE report_operation")
                current = _find_entry(before.final_sessions, source_instance_key)
                result = MutationResult(
                    request_id=request_id,
                    outcome_type="no_op",
                    operation_id=None,
                    report_date=report_date,
                    selection_hint=_selection_hint(current),
                    snapshot_revision=before.snapshot_revision,
                    error="operation_no_effect",
                    message="操作未产生变化",
                )
            else:
                conn.execute("RELEASE report_operation")
                result = MutationResult(
                    request_id=request_id,
                    outcome_type="operation_committed",
                    operation_id=operation_id,
                    report_date=report_date,
                    selection_hint=_post_selection(operation_type, operation_id, source_instance_key, after),
                    snapshot_revision=after.snapshot_revision,
                )
            _insert_receipt(conn, request_id, input_signature, result)
            conn.commit()
            return result
        except (sqlite3.OperationalError,) as exc:
            conn.rollback()
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise DatabaseBusyError() from exc
            raise
        except Exception:
            conn.rollback()
            raise


def _operation_input(conn, operation_type: str, source: dict, target: dict | None, values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, list[dict]], int | None]:
    payload: dict[str, Any] = {"payload_version": OPERATION_PAYLOAD_VERSION}
    roles = {"source": _members(source)}
    undo_of: int | None = None
    if operation_type == "edit_session":
        project_id = values.get("project_id")
        if project_id is not None:
            row = conn.execute("SELECT * FROM project WHERE id = ?", (int(project_id),)).fetchone()
            if not project_lifecycle_policy.project_selectable_for_editing(dict(row) if row else None):
                raise ProjectNotSelectableError()
            payload["project"] = {"mode": "set", "project_id": int(project_id)}
        elif bool(source.get("has_project_override")):
            payload["project"] = {"mode": "inherit"}
        duration = values.get("adjusted_duration_seconds")
        if duration is not None:
            payload["duration"] = {"mode": "set", "value": int(duration)}
        elif bool(source.get("has_duration_override")):
            payload["duration"] = {"mode": "inherit"}
        note = str(values.get("note") or "")
        if note:
            payload["note"] = {"mode": "set", "value": note}
        elif str(source.get("session_note") or ""):
            payload["note"] = {"mode": "inherit"}
    elif operation_type == "merge_sessions":
        if target is None:
            raise StaleSelectionError()
        roles["target"] = _members(target)
    elif operation_type == "hide_activity":
        summary_id = str(values.get("summary_id") or "")
        affected = _affected_members(source, summary_id)
        if not affected:
            raise StaleSelectionError()
        payload["summary_id"] = summary_id
        roles["affected"] = affected
    elif operation_type == "split_session":
        undo_of = _producer_operation_id(str(source.get("projection_instance_key") or ""), "merge")
        if undo_of is None:
            raise OperationNotAllowedError()
    return payload, roles, undo_of


def _affected_members(source: dict, summary_id: str) -> list[dict]:
    from . import project_activity_summary_service as summaries

    contributions = list(source.get("_projection_contributions") or [])
    result = summaries.build_activity_summary_rows(
        contributions,
        str(source.get("report_date") or ""),
        str(source.get("projection_instance_key") or ""),
        str(source.get("projection_revision") or ""),
    )
    summary = next((item for item in result if str(item.get("summary_id") or "") == summary_id), None)
    if summary is None:
        return []
    identity = str(summary.get("activity_identity_key") or "")
    return [
        _member(row)
        for row in contributions
        if summaries._activity_group_key(row) == identity
    ]


def _insert_operation(conn, **values) -> int:
    cur = conn.execute(
        """INSERT INTO report_session_operation(
            report_date, sequence, operation_type, source_instance_key,
            source_expected_revision, target_instance_key, target_expected_revision,
            direction, undo_of_operation_id, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            values["report_date"], values["sequence"], values["operation_type"],
            values["source_instance_key"], values["source_expected_revision"],
            values["target_instance_key"], values["target_expected_revision"],
            values["direction"], values["undo_of_operation_id"],
            json.dumps(values["payload"], ensure_ascii=False, sort_keys=True), now_str(),
        ),
    )
    return int(cur.lastrowid)


def _insert_members(conn, operation_id: int, roles: Mapping[str, list[dict]]) -> None:
    for role, members in roles.items():
        for order, member in enumerate(members):
            conn.execute(
                """INSERT INTO report_session_operation_member(
                    operation_id, role, activity_id, report_date, slice_start_time, display_order
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (operation_id, role, member["activity_id"], member["report_date"], member["slice_start_time"], order),
            )


def _inflate_operation(conn, operation: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(operation.get("payload_json") or "{}"))
    except json.JSONDecodeError as exc:
        raise InvalidInputError("操作负载损坏") from exc
    roles: dict[str, list[dict]] = {}
    for row in conn.execute(
        """SELECT role, activity_id, report_date, slice_start_time
           FROM report_session_operation_member WHERE operation_id = ?
           ORDER BY role, display_order, activity_id""",
        (int(operation["id"]),),
    ).fetchall():
        item = dict(row)
        roles.setdefault(str(item.pop("role")), []).append(item)
    operation["payload"] = payload
    operation["members"] = roles
    return operation


def _find_request(conn, request_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM report_mutation_request WHERE request_id = ?", (request_id,)).fetchone()
    return dict(row) if row else None


def _insert_receipt(conn, request_id: str, signature: str, result: MutationResult) -> None:
    timestamp = now_str()
    conn.execute(
        """INSERT INTO report_mutation_request(
            request_id, input_signature, outcome_type, operation_id, result_json, created_at, committed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            request_id, signature, result.outcome_type, result.operation_id,
            json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True), timestamp, timestamp,
        ),
    )


def _mutation_result_from_receipt(row: Mapping[str, Any]) -> MutationResult:
    try:
        value = json.loads(str(row.get("result_json") or "{}"))
        return MutationResult(**value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RequestIdConflictError("请求回执损坏") from exc


def _next_sequence(conn, report_date: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM report_session_operation WHERE report_date = ?",
        (report_date,),
    ).fetchone()
    return int(row[0])


def _members(entry: Mapping[str, Any]) -> list[dict]:
    return [_member(item) for item in entry.get("member_slices") or []]


def _member(value: Mapping[str, Any]) -> dict[str, Any]:
    report_date, activity_id, start = member_identity_key(dict(value))
    return {"report_date": report_date, "activity_id": activity_id, "slice_start_time": start}


def _find_entry(entries, key: str) -> dict | None:
    return next((item for item in entries if str(item.get("projection_instance_key") or "") == key), None)


def _require_adjacent(entries, source: dict, target: dict, direction: str) -> None:
    ordered = sorted(entries, key=lambda item: (str(item.get("start_time") or ""), str(item.get("projection_instance_key") or "")))
    source_index, target_index = ordered.index(source), ordered.index(target)
    expected = source_index - 1 if direction == "previous" else source_index + 1
    if target_index != expected:
        raise SessionNotAdjacentError()


def _require_capability(operation_type: str, source: dict, direction: str | None) -> None:
    if bool(source.get("is_in_progress")):
        raise OperationNotAllowedError()
    field = {
        "edit_session": "editable",
        "hide_session": "can_hide",
        "copy_session": "can_copy",
        "hide_activity": "can_hide_activity",
        "split_session": "can_split",
        "merge_sessions": f"can_merge_{direction}",
    }.get(operation_type)
    if not field or not bool(source.get(field)):
        raise OperationNotAllowedError()


def _producer_operation_id(key: str, expected_prefix: str) -> int | None:
    try:
        prefix, raw = key.split(":", 1)
        return int(raw) if prefix == expected_prefix and int(raw) > 0 else None
    except (ValueError, TypeError):
        return None


def _expected_effect(operation_type: str, operation_id: int, before, after, source: dict) -> bool:
    key = str(source.get("projection_instance_key") or "")
    if operation_type == "copy_session":
        return _find_entry(after.final_sessions, f"copy:{operation_id}") is not None
    if operation_type == "merge_sessions":
        return _find_entry(after.final_sessions, f"merge:{operation_id}") is not None
    if operation_type in {"hide_session", "split_session"}:
        return _find_entry(after.final_sessions, key) is None
    current = _find_entry(after.final_sessions, key)
    return current is None or str(current.get("projection_revision") or "") != str(source.get("projection_revision") or "")


def _post_selection(operation_type: str, operation_id: int, source_key: str, after) -> dict | None:
    if operation_type in {"hide_session", "split_session"}:
        return None
    key = f"copy:{operation_id}" if operation_type == "copy_session" else f"merge:{operation_id}" if operation_type == "merge_sessions" else source_key
    return _selection_hint(_find_entry(after.final_sessions, key))


def _selection_hint(entry: Mapping[str, Any] | None) -> dict[str, str] | None:
    if entry is None:
        return None
    return {
        "projection_instance_key": str(entry.get("projection_instance_key") or ""),
        "projection_revision": str(entry.get("projection_revision") or ""),
    }


__all__ = [
    "copy_session", "edit_session", "hide_session", "hide_session_activity",
    "load_operations", "merge_session", "split_session",
]
