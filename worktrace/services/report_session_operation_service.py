"""Persistence and command boundary for Timeline report-session operations."""

from __future__ import annotations

import json
import uuid

from ..db import get_connection, now_str
from . import report_session_operation_engine as engine
from . import project_lifecycle_policy

ACTIVE = "active"
SUPERSEDED = "superseded"


def edit_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str | None,
    current_session: dict | None = None,
    *,
    project_id: int | None,
    adjusted_duration_seconds: int | None,
    note: str,
) -> int | None:
    session = current_session or _resolve(report_date, projection_instance_key, expected_projection_revision)
    if expected_projection_revision:
        _require_revision(session, expected_projection_revision)
    _require(session, "editable", "not_project_activity")
    payload = _edit_payload(session, project_id=project_id, adjusted_duration_seconds=adjusted_duration_seconds, note=note)
    if not any(key in payload for key in ("project", "duration", "note")):
        return None
    return _insert_operation(
        report_date,
        "edit_session",
        session,
        roles={"edit_target": _members(session)},
        payload=payload,
    )


def hide_session(report_date: str, projection_instance_key: str, expected_projection_revision: str | None = None) -> None:
    session = _resolve(report_date, projection_instance_key, expected_projection_revision)
    _require(session, "can_hide", "not_project_activity")
    _insert_operation(report_date, "hide_session", session, roles={"origin": _members(session)})


def merge_session(
    report_date: str,
    projection_instance_key: str,
    direction: str,
    *,
    expected_projection_revision: str | None = None,
    target_projection_instance_key: str | None = None,
    target_expected_projection_revision: str | None = None,
) -> None:
    if direction not in {"previous", "next"}:
        raise ValueError("invalid_direction")
    sessions = _sessions(report_date)
    session = engine.resolve_projection_instance(sessions, projection_instance_key)
    if not session:
        raise ValueError("session_identity_conflict")
    _require_revision(session, expected_projection_revision)
    _require(session, f"can_merge_{direction}", "not_mergeable")
    index = sessions.index(session)
    target = (
        engine.resolve_projection_instance(sessions, target_projection_instance_key)
        if target_projection_instance_key
        else sessions[index - 1 if direction == "previous" else index + 1]
    )
    if not target:
        raise ValueError("session_identity_conflict")
    _require_revision(target, target_expected_projection_revision)
    if str(target.get("projection_kind") or "base") == "copy" or str(session.get("projection_kind") or "base") == "copy":
        raise ValueError("copy_session_not_mergeable")
    group = str(target.get("operation_group_key") or session.get("operation_group_key") or uuid.uuid4().hex)
    _insert_operation(
        report_date,
        "merge_sessions",
        session,
        target=target,
        direction=direction,
        operation_group_key=group,
        roles={"source": _members(session), "target": _members(target), "origin": _members(session) + _members(target)},
    )


def split_session(report_date: str, projection_instance_key: str, expected_projection_revision: str | None = None) -> None:
    session = _resolve(report_date, projection_instance_key, expected_projection_revision)
    _require(session, "can_split", "not_merge_session")
    group = str(session.get("operation_group_key") or "")
    if not group:
        raise ValueError("session_identity_conflict")
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ts = now_str()
        conn.execute(
            """
            UPDATE report_session_operation
            SET match_state = ?, updated_at = ?
            WHERE report_date = ? AND match_state = ?
              AND (operation_group_key = ? OR base_instance_key = ? OR target_instance_key = ?)
            """,
            (SUPERSEDED, ts, report_date, ACTIVE, group, f"merge:{group}", f"merge:{group}"),
        )


def copy_session(report_date: str, projection_instance_key: str, expected_projection_revision: str | None = None) -> None:
    session = _resolve(report_date, projection_instance_key, expected_projection_revision)
    _require(session, "can_copy", "not_project_activity")
    _insert_operation(report_date, "copy_session", session, roles={"copy_origin": _members(session)})


def hide_session_activity(
    report_date: str,
    projection_instance_key: str,
    summary_id: str,
    expected_projection_revision: str | None = None,
) -> None:
    session = _resolve(report_date, projection_instance_key, expected_projection_revision)
    _require(session, "can_hide_activity", "not_project_activity")
    from . import project_activity_summary_service

    summaries = project_activity_summary_service.build_activity_summary_rows(
        list(session.get("_projection_contributions") or []), report_date, projection_instance_key
    )
    summary = next((item for item in summaries if str(item.get("summary_id")) == str(summary_id)), None)
    if not summary:
        raise ValueError("session_identity_conflict")
    identity = str(summary.get("activity_identity_key") or "")
    members = [
        _member_from_row(row)
        for row in session.get("_projection_contributions") or []
        if project_activity_summary_service._activity_group_key(row) == identity
    ]
    if not members:
        raise ValueError("session_identity_conflict")
    _insert_operation(
        report_date,
        "hide_activity",
        session,
        roles={"hidden_activity": members},
        payload={"activity_identity_key": identity},
    )


def load_operations(report_date: str, *, conn=None) -> list[dict]:
    if conn is None:
        with get_connection() as read_conn:
            return load_operations(report_date, conn=read_conn)
    rows = conn.execute(
            """SELECT * FROM report_session_operation
               WHERE report_date = ? AND match_state = ? ORDER BY replay_order ASC, id ASC""",
            (report_date, ACTIVE),
    ).fetchall()
    operations = [dict(row) for row in rows]
    for operation in operations:
            member_rows = conn.execute(
                """SELECT role, activity_id, report_date, slice_start_time, slice_end_time, display_order
                   FROM report_session_operation_member WHERE operation_id = ?
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
            if operation.get("operation_type") == "edit_session":
                _refresh_edit_payload_project_lifecycle(operation["payload"], conn)
    return operations


def _refresh_edit_payload_project_lifecycle(payload: dict, conn) -> None:
    project = payload.get("project") if isinstance(payload.get("project"), dict) else None
    if not project or str(project.get("mode") or "") != "set":
        return
    project_id = int(project.get("project_id") or 0)
    if project_id <= 0:
        return
    row = conn.execute("SELECT name, description, is_deleted, is_archived FROM project WHERE id = ?", (project_id,)).fetchone()
    if not row:
        project["project_is_deleted"] = True
        return
    project["project_name"] = str(row["name"] or "")
    project["project_description"] = str(row["description"] or "")
    project["project_is_deleted"] = bool(row["is_deleted"])
    project["project_is_archived"] = bool(row["is_archived"])


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


def _sessions(report_date: str) -> list[dict]:
    from .report_session_projection_service import get_report_sessions_for_operations

    return get_report_sessions_for_operations(report_date, report_date, include_hidden=False, ensure_context=True)


def _resolve(report_date: str, projection_instance_key: str, expected_projection_revision: str | None = None) -> dict:
    if not isinstance(report_date, str) or not report_date or not isinstance(projection_instance_key, str) or not projection_instance_key:
        raise ValueError("invalid_session_identity")
    session = engine.resolve_projection_instance(_sessions(report_date), projection_instance_key)
    if not session:
        raise ValueError("session_identity_conflict")
    _require_revision(session, expected_projection_revision)
    return session


def _require_revision(session: dict, expected_projection_revision: str | None) -> None:
    if not expected_projection_revision:
        return
    current = str(session.get("projection_revision") or session.get("session_detail_revision") or "")
    if current != str(expected_projection_revision):
        raise ValueError("revision_conflict")


def _require(session: dict, field: str, error: str) -> None:
    if not bool(session.get(field)):
        if bool(session.get("is_in_progress")):
            raise ValueError("in_progress")
        raise ValueError(error)


def _insert_operation(
    report_date: str,
    operation_type: str,
    session: dict,
    *,
    target: dict | None = None,
    direction: str | None = None,
    operation_group_key: str | None = None,
    roles: dict[str, list[dict]],
    payload: dict | None = None,
) -> int:
    ts = now_str()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        replay_order = _next_replay_order(conn, report_date)
        cur = conn.execute(
            """INSERT INTO report_session_operation(
                report_date, operation_type, base_instance_key, target_instance_key,
                direction, operation_group_key, replay_order, match_state, payload_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_date, operation_type, str(session.get("projection_instance_key") or ""),
                str(target.get("projection_instance_key") or "") if target else None,
                direction, operation_group_key, replay_order, ACTIVE, json.dumps(payload or {}, ensure_ascii=False, sort_keys=True), ts, ts,
            ),
        )
        operation_id = int(cur.lastrowid)
        for role, members in roles.items():
            for order, member in enumerate(members):
                conn.execute(
                    """INSERT OR IGNORE INTO report_session_operation_member(
                        operation_id, role, activity_id, report_date, slice_start_time, slice_end_time, display_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (operation_id, role, int(member["activity_id"]), str(member["report_date"]), str(member["slice_start_time"]), str(member["slice_end_time"]), order),
                )
    return operation_id


def _next_replay_order(conn, report_date: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(replay_order), 0) + 1 AS next_order FROM report_session_operation WHERE report_date = ?",
        (report_date,),
    ).fetchone()
    return int(row["next_order"] or 1)


def _edit_payload(
    session: dict,
    *,
    project_id: int | None,
    adjusted_duration_seconds: int | None,
    note: str,
) -> dict:
    payload: dict = {"payload_version": 1}
    with get_connection() as conn:
        if project_id is not None:
            row = conn.execute("SELECT * FROM project WHERE id = ?", (int(project_id),)).fetchone()
            project = dict(row) if row else None
            if not project_lifecycle_policy.project_selectable_for_editing(project):
                raise ValueError("project_not_selectable")
            if int(session.get("project_id") or 0) != int(project_id) or not bool(session.get("has_project_override")):
                payload["project"] = {
                    "mode": "set",
                    "project_id": int(project_id),
                    "project_name": str(project.get("name") or ""),
                    "project_description": str(project.get("description") or ""),
                    "project_is_deleted": bool(project.get("is_deleted")),
                    "project_is_archived": bool(project.get("is_archived")),
                }
        elif bool(session.get("has_project_override")):
            payload["project"] = {"mode": "inherit"}
    if adjusted_duration_seconds is not None:
        if (
            not bool(session.get("has_duration_override"))
            or int(session.get("adjusted_duration_seconds") or 0) != int(adjusted_duration_seconds)
        ):
            payload["duration"] = {"mode": "set", "value": int(adjusted_duration_seconds)}
    elif bool(session.get("has_duration_override")):
        payload["duration"] = {"mode": "inherit"}
    text = str(note or "")
    if text:
        if str(session.get("session_note") or "") != text:
            payload["note"] = {"mode": "set", "value": text}
    elif str(session.get("session_note") or ""):
        payload["note"] = {"mode": "inherit"}
    return payload


def _members(session: dict) -> list[dict]:
    return [dict(member) for member in session.get("member_slices") or []]


def _member_from_row(row: dict) -> dict:
    return {
        "activity_id": int(row.get("activity_id") or row.get("id") or 0),
        "report_date": str(row.get("report_date") or ""),
        "slice_start_time": str(row.get("slice_start_time") or row.get("start_time") or ""),
        "slice_end_time": str(row.get("slice_end_time") or row.get("end_time") or ""),
    }


__all__ = [
    "copy_session", "edit_session", "hide_session", "hide_session_activity", "load_operations",
    "merge_session", "persist_engine_match_states", "split_session",
]
