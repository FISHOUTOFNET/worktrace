"""SQLite write unit of work for report-session operations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..db import get_connection, now_str
from . import project_lifecycle_policy
from . import report_session_operation_engine as engine
from .report_projection_model import MutationResult
from .report_projection_identity import member_identity_key, stable_json_hash

ACTIVE = "active"
SUPERSEDED = "superseded"
PAYLOAD_VERSION = 3


def edit_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
    *,
    project_id: int | None,
    adjusted_duration_seconds: int | None,
    note: str,
) -> MutationResult:
    return _run_uow(
        report_date,
        request_id,
        "edit_session",
        projection_instance_key,
        expected_projection_revision,
        payload_input={"project_id": project_id, "adjusted_duration_seconds": adjusted_duration_seconds, "note": note},
    )


def hide_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str) -> MutationResult:
    result = _run_uow(report_date, request_id, "hide_session", projection_instance_key, expected_projection_revision)
    return result


def merge_session(
    report_date: str,
    projection_instance_key: str,
    direction: str,
    request_id: str,
    *,
    expected_projection_revision: str,
    target_projection_instance_key: str,
    target_expected_projection_revision: str,
) -> MutationResult:
    if direction not in {"previous", "next"}:
        raise ValueError("invalid_direction")
    result = _run_uow(
        report_date,
        request_id,
        "merge_sessions",
        projection_instance_key,
        expected_projection_revision,
        target_projection_instance_key=target_projection_instance_key,
        target_expected_projection_revision=target_expected_projection_revision,
        direction=direction,
    )
    return result


def split_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str) -> MutationResult:
    result = _run_uow(report_date, request_id, "split_session", projection_instance_key, expected_projection_revision)
    return result


def copy_session(report_date: str, projection_instance_key: str, expected_projection_revision: str, request_id: str) -> MutationResult:
    result = _run_uow(report_date, request_id, "copy_session", projection_instance_key, expected_projection_revision)
    return result


def hide_session_activity(
    report_date: str,
    projection_instance_key: str,
    summary_id: str,
    expected_projection_revision: str,
    request_id: str,
) -> MutationResult:
    result = _run_uow(
        report_date,
        request_id,
        "hide_activity",
        projection_instance_key,
        expected_projection_revision,
        payload_input={"summary_id": summary_id},
    )
    return result


def load_operations(report_date: str, *, conn=None) -> list[dict]:
    if conn is None:
        with get_connection() as read_conn:
            return load_operations(report_date, conn=read_conn)
    rows = conn.execute(
        """SELECT * FROM report_session_operation
           WHERE report_date = ? AND match_state = ?
           ORDER BY replay_order ASC, id ASC""",
        (report_date, ACTIVE),
    ).fetchall()
    operations = [_inflate_operation(conn, dict(row)) for row in rows]
    for operation in operations:
        _refresh_edit_payload_project_lifecycle(operation["payload"], conn)
    return operations


def load_operation_lifecycle(report_date: str, *, conn=None) -> list[dict]:
    if conn is None:
        with get_connection() as read_conn:
            return load_operation_lifecycle(report_date, conn=read_conn)
    rows = conn.execute(
        """SELECT * FROM report_session_operation
           WHERE report_date = ?
           ORDER BY replay_order ASC, id ASC""",
        (report_date,),
    ).fetchall()
    operations = [_inflate_operation(conn, dict(row)) for row in rows]
    for operation in operations:
        _refresh_edit_payload_project_lifecycle(operation["payload"], conn)
    return operations


def persist_engine_match_states(operations: list[dict]) -> None:
    updates = [
        (str(item["_engine_match_state"]), now_str(), int(item["id"]))
        for item in operations
        if item.get("_engine_match_state") in {"conflict", "orphaned"}
    ]
    if not updates:
        return
    with get_connection() as conn:
        conn.executemany(
            """UPDATE report_session_operation SET match_state = ?, updated_at = ?
               WHERE id = ? AND match_state = ?""",
            [(state, ts, oid, ACTIVE) for state, ts, oid in updates],
        )


def _run_uow(
    report_date: str,
    request_id: str,
    operation_type: str,
    base_instance_key: str,
    base_expected_revision: str,
    *,
    target_projection_instance_key: str | None = None,
    target_expected_projection_revision: str | None = None,
    direction: str | None = None,
    payload_input: dict[str, Any] | None = None,
) -> MutationResult:
    if not request_id:
        raise ValueError("invalid_request_id")
    input_signature = stable_json_hash(
        {
            "report_date": report_date,
            "operation_type": operation_type,
            "base_instance_key": base_instance_key,
            "base_expected_revision": base_expected_revision,
            "target_instance_key": target_projection_instance_key,
            "target_expected_revision": target_expected_projection_revision,
            "direction": direction,
            "payload_input": payload_input or {},
        }
    )
    with get_connection() as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = _find_request(conn, request_id)
            if existing:
                if str(existing.get("input_signature") or "") != input_signature:
                    raise ValueError("request_id_conflict")
                conn.commit()
                return _mutation_result_from_ledger(existing)
            from .report_projection_snapshot_service import build_visible_snapshot

            snapshot = build_visible_snapshot(report_date, report_date, ensure_context=True, conn=conn)
            sessions = list(snapshot.final_sessions)
            source = engine.resolve_projection_instance(sessions, base_instance_key)
            if not source:
                raise ValueError("session_identity_conflict")
            _require_revision(source, base_expected_revision, "revision_conflict")
            target = None
            if operation_type == "merge_sessions":
                if not target_projection_instance_key or not target_expected_projection_revision:
                    raise ValueError("session_identity_conflict")
                target = engine.resolve_projection_instance(sessions, target_projection_instance_key)
                if not target:
                    raise ValueError("session_identity_conflict")
                _require_revision(target, target_expected_projection_revision, "target_revision_conflict")
                _require_adjacent(sessions, source, target, direction)
            _require_capability(operation_type, source, direction)
            payload, roles, reverts_operation_id = _build_payload_and_roles(
                conn,
                operation_type,
                source,
                target,
                payload_input or {},
            )
            signature = _request_signature(
                report_date,
                operation_type,
                base_instance_key,
                base_expected_revision,
                target_projection_instance_key,
                target_expected_projection_revision,
                direction,
                payload,
                roles,
            )
            if operation_type == "edit_session" and not _payload_changes_session(source, payload):
                result = MutationResult(
                    request_id=request_id,
                    outcome_type="no_op",
                    operation_id=None,
                    report_date=report_date,
                    selection_hint=_selection_hint(source),
                    snapshot_revision=str(snapshot.snapshot_revision or ""),
                )
                _insert_request_ledger(conn, request_id, input_signature, result)
                conn.commit()
                return result
            replay_order = _next_replay_order(conn, report_date)
            operation_id = _insert_operation(
                conn,
                report_date,
                operation_type,
                base_instance_key,
                base_expected_revision,
                target_projection_instance_key,
                target_expected_projection_revision,
                direction,
                replay_order,
                payload,
                signature,
                input_signature,
                reverts_operation_id=reverts_operation_id,
            )
            _insert_members(conn, operation_id, roles)
            _insert_dependencies(conn, operation_id, [base_instance_key, target_projection_instance_key])
            if operation_type == "split_session":
                _supersede_split_descendants(conn, operation_id, reverts_operation_id)
            candidate = _candidate_operations(conn, report_date)
            before_keys = {str(item.get("projection_instance_key") or "") for item in sessions}
            after = engine.apply_operations(_base_sessions_for_date(snapshot, report_date), candidate)
            if not _operation_effective(operation_id, operation_type, before_keys, after, candidate):
                raise ValueError("operation_no_effect")
            result = MutationResult(
                request_id=request_id,
                outcome_type="operation_committed",
                operation_id=operation_id,
                report_date=report_date,
                selection_hint=_deterministic_selection_hint(operation_type, operation_id, source),
                snapshot_revision=str(snapshot.snapshot_revision or ""),
            )
            _insert_request_ledger(conn, request_id, input_signature, result)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise


def _base_sessions_for_date(snapshot, report_date: str) -> list[dict]:
    return [dict(item) for item in snapshot.base_sessions if str(item.get("report_date") or "") == report_date]


def _candidate_operations(conn, report_date: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM report_session_operation
           WHERE report_date = ? AND match_state = ?
           ORDER BY replay_order ASC, id ASC""",
        (report_date, ACTIVE),
    ).fetchall()
    return [_inflate_operation(conn, dict(row)) for row in rows]


def _operation_effective(operation_id: int, operation_type: str, before_keys: set[str], after: list[dict], operations: list[dict]) -> bool:
    operation = next((item for item in operations if int(item.get("id") or 0) == operation_id), None)
    if not operation or operation.get("_engine_match_state"):
        return False
    after_keys = {str(item.get("projection_instance_key") or "") for item in after}
    if operation_type == "copy_session":
        return f"copy:{operation_id}" in after_keys
    if operation_type == "merge_sessions":
        return f"merge:{operation_id}" in after_keys
    if operation_type == "hide_session":
        return after_keys != before_keys
    if operation_type == "hide_activity":
        return True
    if operation_type == "split_session":
        return True
    return any(
        any(int(command.get("id") or 0) == operation_id for command in session.get("_applied_commands") or [])
        for session in after
    )


def _insert_operation(
    conn,
    report_date: str,
    operation_type: str,
    base_instance_key: str,
    base_expected_revision: str,
    target_instance_key: str | None,
    target_expected_revision: str | None,
    direction: str | None,
    replay_order: int,
    payload: dict,
    signature: str,
    input_signature: str,
    *,
    reverts_operation_id: int | None = None,
) -> int:
    ts = now_str()
    payload_to_store = dict(payload)
    payload_to_store["request_signature"] = signature
    payload_to_store["request_input_signature"] = input_signature
    cur = conn.execute(
        """INSERT INTO report_session_operation(
            report_date, operation_type, base_instance_key, base_expected_revision,
            target_instance_key, target_expected_revision, direction, replay_order, match_state,
            reverts_operation_id, payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            report_date,
            operation_type,
            base_instance_key,
            base_expected_revision,
            target_instance_key,
            target_expected_revision,
            direction,
            replay_order,
            ACTIVE,
            reverts_operation_id,
            json.dumps(payload_to_store, ensure_ascii=False, sort_keys=True),
            ts,
            ts,
        ),
    )
    return int(cur.lastrowid)


def _insert_members(conn, operation_id: int, roles: dict[str, list[dict]]) -> None:
    for role, members in roles.items():
        for order, member in enumerate(members):
            conn.execute(
                """INSERT INTO report_session_operation_member(
                    operation_id, role, activity_id, report_date, slice_start_time, display_order
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    operation_id,
                    role,
                    int(member["activity_id"]),
                    str(member["report_date"]),
                    str(member["slice_start_time"]),
                    order,
                ),
            )


def _insert_dependencies(conn, operation_id: int, keys: list[str | None]) -> None:
    for key in keys:
        parent = _operation_id_from_projection_key(key)
        if parent is None:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO report_session_operation_dependency(parent_operation_id, child_operation_id)
               VALUES (?, ?)""",
            (parent, operation_id),
        )


def _supersede_split_descendants(conn, split_operation_id: int, reverted_operation_id: int | None) -> None:
    if not reverted_operation_id:
        raise ValueError("session_identity_conflict")
    rows = conn.execute(
        """
        WITH RECURSIVE descendants(id) AS (
            SELECT ?
            UNION
            SELECT d.child_operation_id
            FROM report_session_operation_dependency d
            JOIN descendants x ON x.id = d.parent_operation_id
        )
        SELECT id FROM descendants
        """,
        (reverted_operation_id,),
    ).fetchall()
    ids = [int(row["id"]) for row in rows if int(row["id"]) != split_operation_id]
    if not ids:
        return
    ts = now_str()
    for operation_id in ids:
        conn.execute(
            """INSERT OR IGNORE INTO report_session_operation_supersession(
                superseded_operation_id, superseding_operation_id, reason, created_at
            ) VALUES (?, ?, ?, ?)""",
            (operation_id, split_operation_id, "split_revert", ts),
        )
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        f"""UPDATE report_session_operation
            SET match_state = ?, updated_at = ?
            WHERE match_state = ? AND id IN ({placeholders})""",
        (SUPERSEDED, ts, ACTIVE, *ids),
    )


def _build_payload_and_roles(conn, operation_type: str, source: dict, target: dict | None, payload_input: dict) -> tuple[dict, dict[str, list[dict]], int | None]:
    if operation_type == "edit_session":
        payload = _edit_payload(conn, source, payload_input)
        return payload, {"source": _members(source)}, None
    if operation_type == "hide_session":
        return {"payload_version": PAYLOAD_VERSION}, {"source": _members(source)}, None
    if operation_type == "copy_session":
        return {"payload_version": PAYLOAD_VERSION}, {"source": _members(source)}, None
    if operation_type == "merge_sessions":
        if target is None:
            raise ValueError("session_identity_conflict")
        return {"payload_version": PAYLOAD_VERSION}, {"source": _members(source), "target": _members(target)}, None
    if operation_type == "hide_activity":
        members = _affected_members_for_summary(source, str(payload_input.get("summary_id") or ""))
        if not members:
            raise ValueError("session_identity_conflict")
        return {"payload_version": PAYLOAD_VERSION, "summary_id": str(payload_input.get("summary_id") or "")}, {"affected": members}, None
    if operation_type == "split_session":
        reverted = _operation_id_from_projection_key(str(source.get("projection_instance_key") or ""))
        if not reverted:
            raise ValueError("session_identity_conflict")
        return {"payload_version": PAYLOAD_VERSION}, {"source": _members(source)}, reverted
    raise ValueError("unsupported_operation_type")


def _edit_payload(conn, session: dict, payload_input: dict) -> dict:
    payload: dict[str, Any] = {"payload_version": PAYLOAD_VERSION}
    project_id = payload_input.get("project_id")
    if project_id is not None:
        row = conn.execute("SELECT * FROM project WHERE id = ?", (int(project_id),)).fetchone()
        project = dict(row) if row else None
        if not project_lifecycle_policy.project_selectable_for_editing(project):
            raise ValueError("project_not_selectable")
        payload["project"] = {"mode": "set", "project_id": int(project_id)}
    elif bool(session.get("has_project_override")):
        payload["project"] = {"mode": "inherit"}
    if "adjusted_duration_seconds" in payload_input:
        value = payload_input.get("adjusted_duration_seconds")
        if value is not None:
            payload["duration"] = {"mode": "set", "value": int(value)}
        elif bool(session.get("has_duration_override")):
            payload["duration"] = {"mode": "inherit"}
    text = str(payload_input.get("note") or "")
    if text:
        payload["note"] = {"mode": "set", "value": text}
    elif str(session.get("session_note") or ""):
        payload["note"] = {"mode": "inherit"}
    return payload


def _payload_changes_session(session: dict, payload: dict) -> bool:
    project = payload.get("project") if isinstance(payload.get("project"), dict) else None
    if project:
        if str(project.get("mode")) == "inherit" and bool(session.get("has_project_override")):
            return True
        if str(project.get("mode")) == "set" and (
            int(project.get("project_id") or 0) != int(session.get("project_id") or 0)
            or not bool(session.get("has_project_override"))
        ):
            return True
    duration = payload.get("duration") if isinstance(payload.get("duration"), dict) else None
    if duration:
        if str(duration.get("mode")) == "inherit" and bool(session.get("has_duration_override")):
            return True
        if str(duration.get("mode")) == "set" and (
            int(duration.get("value") or 0) != int(session.get("adjusted_duration_seconds") or 0)
            or not bool(session.get("has_duration_override"))
        ):
            return True
    note = payload.get("note") if isinstance(payload.get("note"), dict) else None
    if note:
        value = "" if str(note.get("mode")) == "inherit" else str(note.get("value") or "")
        return value != str(session.get("session_note") or "")
    return False


def _affected_members_for_summary(session: dict, summary_id: str) -> list[dict]:
    if not summary_id:
        return []
    from . import project_activity_summary_service

    summaries = project_activity_summary_service.build_activity_summary_rows(
        list(session.get("_projection_contributions") or []),
        str(session.get("report_date") or ""),
        str(session.get("projection_instance_key") or ""),
    )
    summary = next((item for item in summaries if str(item.get("summary_id")) == summary_id), None)
    if not summary:
        return []
    identity = str(summary.get("activity_identity_key") or "")
    return [
        _member_from_row(row)
        for row in session.get("_projection_contributions") or []
        if project_activity_summary_service._activity_group_key(row) == identity
    ]


def _find_request(conn, request_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM report_mutation_request WHERE request_id = ?", (request_id,)).fetchone()
    return dict(row) if row else None


def _insert_request_ledger(conn, request_id: str, input_signature: str, result: MutationResult) -> None:
    ts = now_str()
    conn.execute(
        """INSERT INTO report_mutation_request(
            request_id, input_signature, outcome_type, operation_id, result_json, created_at, committed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            request_id,
            input_signature,
            result.outcome_type,
            result.operation_id,
            json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True),
            ts,
            ts,
        ),
    )


def _mutation_result_from_ledger(row: dict) -> MutationResult:
    try:
        payload = json.loads(str(row.get("result_json") or "{}"))
    except json.JSONDecodeError:
        raise ValueError("request_id_conflict")
    return MutationResult(
        request_id=str(row.get("request_id") or payload.get("request_id") or ""),
        outcome_type=str(row.get("outcome_type") or payload.get("outcome_type") or ""),
        operation_id=payload.get("operation_id"),
        report_date=str(payload.get("report_date") or ""),
        selection_hint=payload.get("selection_hint") if isinstance(payload.get("selection_hint"), dict) else None,
        snapshot_revision=payload.get("snapshot_revision"),
    )


def _selection_hint(session: dict | None) -> dict | None:
    if not session:
        return None
    return {
        "projection_instance_key": str(session.get("projection_instance_key") or ""),
        "projection_revision": str(session.get("projection_revision") or ""),
    }


def _deterministic_selection_hint(operation_type: str, operation_id: int, source: dict) -> dict | None:
    if operation_type == "copy_session":
        return {"projection_instance_key": f"copy:{operation_id}", "projection_revision": ""}
    if operation_type == "merge_sessions":
        return {"projection_instance_key": f"merge:{operation_id}", "projection_revision": ""}
    if operation_type in {"hide_session", "split_session"}:
        return None
    return _selection_hint(source)


def _inflate_operation(conn, operation: dict) -> dict:
    member_rows = conn.execute(
        """SELECT role, activity_id, report_date, slice_start_time, display_order
           FROM report_session_operation_member
           WHERE operation_id = ?
           ORDER BY role, display_order, activity_id""",
        (int(operation["id"]),),
    ).fetchall()
    roles: dict[str, list[dict]] = {}
    for member in member_rows:
        item = dict(member)
        roles.setdefault(str(item.pop("role")), []).append(item)
    operation["members"] = roles
    try:
        operation["payload"] = json.loads(str(operation.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        operation["payload"] = {}
    return operation


def _refresh_edit_payload_project_lifecycle(payload: dict, conn) -> None:
    project = payload.get("project") if isinstance(payload.get("project"), dict) else None
    if not project or str(project.get("mode") or "") != "set":
        return
    project_id = int(project.get("project_id") or 0)
    row = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
    if not row:
        project["project_is_deleted"] = True
        return
    project.update(
        {
            "project_name": str(row["name"] or ""),
            "project_description": str(row["description"] or ""),
            "project_is_deleted": bool(row["is_deleted"]),
            "project_is_archived": bool(row["is_archived"]),
            "is_report_project": True,
            "is_report_classified": True,
            "is_report_uncategorized": False,
        }
    )


def _request_signature(
    report_date: str,
    operation_type: str,
    base_instance_key: str,
    base_expected_revision: str,
    target_instance_key: str | None,
    target_expected_revision: str | None,
    direction: str | None,
    payload: dict,
    roles: dict[str, list[dict]],
) -> str:
    return stable_json_hash(
        {
            "report_date": report_date,
            "operation_type": operation_type,
            "base_instance_key": base_instance_key,
            "base_expected_revision": base_expected_revision,
            "target_instance_key": target_instance_key,
            "target_expected_revision": target_expected_revision,
            "direction": direction,
            "payload": payload,
            "members": {
                role: [member_identity_key(member) for member in members]
                for role, members in sorted(roles.items())
            },
        }
    )


def _require_revision(session: dict, expected: str, error: str) -> None:
    if not expected:
        raise ValueError("invalid_session_identity")
    if str(session.get("projection_revision") or "") != str(expected):
        raise ValueError(error)


def _require_adjacent(sessions: list[dict], source: dict, target: dict, direction: str | None) -> None:
    if direction not in {"previous", "next"}:
        raise ValueError("invalid_direction")
    if source is target:
        raise ValueError("session_identity_conflict")
    source_index = sessions.index(source)
    target_index = sessions.index(target)
    expected_index = source_index - 1 if direction == "previous" else source_index + 1
    if target_index != expected_index:
        raise ValueError("session_not_adjacent")


def _require_capability(operation_type: str, source: dict, direction: str | None) -> None:
    if bool(source.get("is_in_progress")):
        raise ValueError("in_progress")
    if operation_type == "edit_session" and not bool(source.get("editable")):
        raise ValueError("not_project_activity")
    if operation_type == "hide_session" and not bool(source.get("can_hide")):
        raise ValueError("not_project_activity")
    if operation_type == "copy_session" and not bool(source.get("can_copy")):
        raise ValueError("not_project_activity")
    if operation_type == "hide_activity" and not bool(source.get("can_hide_activity")):
        raise ValueError("not_project_activity")
    if operation_type == "split_session" and not bool(source.get("can_split")):
        raise ValueError("not_merge_session")
    if operation_type == "merge_sessions":
        if str(source.get("projection_kind") or "base") == "copy":
            raise ValueError("not_mergeable")
        if not bool(source.get("can_merge_" + str(direction))):
            raise ValueError("not_mergeable")


def _next_replay_order(conn, report_date: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(replay_order), 0) + 1 AS next_order FROM report_session_operation WHERE report_date = ?",
        (report_date,),
    ).fetchone()
    return int(row["next_order"] or 1)


def _members(session: dict) -> list[dict]:
    return [_member_from_row(member) for member in session.get("member_slices") or []]


def _member_from_row(row: dict) -> dict:
    return {
        "activity_id": int(row.get("activity_id") or row.get("id") or 0),
        "report_date": str(row.get("report_date") or "")[:10],
        "slice_start_time": str(row.get("slice_start_time") or row.get("start_time") or ""),
    }


def _operation_id_from_projection_key(key: str | None) -> int | None:
    if not key or ":" not in key:
        return None
    prefix, value = str(key).split(":", 1)
    if prefix not in {"copy", "merge"}:
        return None
    try:
        result = int(value)
    except ValueError:
        return None
    return result if result > 0 else None


__all__ = [
    "copy_session",
    "edit_session",
    "hide_session",
    "hide_session_activity",
    "load_operation_lifecycle",
    "load_operations",
    "merge_session",
    "persist_engine_match_states",
    "split_session",
]
