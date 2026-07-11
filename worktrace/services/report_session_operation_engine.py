"""Pure, in-memory projection of user report-session operations.

The engine deliberately knows nothing about SQLite or the WebView.  It only
applies already-resolved operation records to the final automatic sessions.
"""

from __future__ import annotations

from copy import deepcopy

from .report_projection_identity import (
    base_projection_key,
    copy_projection_key,
    member_identity_key,
    merge_projection_key,
    projection_revision,
)


ACTIVE = "active"
CONFLICT = "conflict"
ORPHANED = "orphaned"


def apply_operations(base_sessions: list[dict], operations: list[dict]) -> list[dict]:
    """Apply active operations in stable creation order.

    Operation dictionaries are annotated with ``_engine_match_state`` when
    their persisted identity no longer resolves.  The caller may persist that
    state; this module itself never writes anything.
    """
    sessions = []
    for session in base_sessions:
        item = deepcopy(session)
        item.setdefault("_applied_commands", [])
        finalize_projected_session(item)
        sessions.append(item)
    known_members = {
        _member_key(member)
        for session in base_sessions
        for member in session.get("member_slices") or []
    }
    for operation in sorted(
        operations,
        key=lambda item: (
            int(item.get("replay_order") or item.get("id") or 0),
            int(item.get("id") or 0),
        ),
    ):
        if str(operation.get("match_state") or ACTIVE) != ACTIVE:
            continue
        operation_type = str(operation.get("operation_type") or "")
        source = resolve_projection_instance(sessions, str(operation.get("base_instance_key") or ""))
        target = resolve_projection_instance(sessions, str(operation.get("target_instance_key") or ""))
        if operation_type == "edit_session":
            if source is None:
                _mark_unresolved(operation, known_members)
                continue
            _apply_edit_session(source, operation)
            _record_command(source, operation)
            finalize_projected_session(source)
            continue
        if operation_type == "merge_sessions":
            if source is None or target is None or source is target:
                _mark_unresolved(operation, known_members)
                continue
            merged = _merge_sessions(source, target, operation)
            source_index = sessions.index(source)
            target_index = sessions.index(target)
            # Preserve the target's list position; this is the UI neighbour
            # the user explicitly selected rather than a reconstructed time
            # ordering.
            sessions[target_index] = merged
            sessions.pop(source_index)
            _record_command(merged, operation)
            finalize_projected_session(merged)
            continue
        if source is None:
            _mark_unresolved(operation, known_members)
            continue
        if operation_type == "hide_session":
            _record_command(source, operation)
            sessions.remove(source)
        elif operation_type == "copy_session":
            copy = deepcopy(source)
            operation_id = int(operation.get("id") or 0)
            copy.update(
                {
                    "projection_instance_key": copy_projection_key(operation_id),
                    "projection_kind": "copy",
                    "operation_id": operation_id,
                    "operation_group_key": None,
                    "can_merge_previous": False,
                    "can_merge_next": False,
                }
            )
            _record_command(copy, operation)
            finalize_projected_session(copy)
            sessions.insert(sessions.index(source) + 1, copy)
        elif operation_type == "hide_activity":
            _hide_activity_members(source, operation)
            _record_command(source, operation)
            finalize_projected_session(source)
            if int(source.get("duration_seconds") or 0) <= 0:
                sessions.remove(source)
        else:
            operation["_engine_match_state"] = CONFLICT
    _refresh_capabilities(sessions)
    for session in sessions:
        session["projection_revision"] = projection_revision(session)
        session["session_detail_revision"] = session["projection_revision"]
    return sessions


def resolve_projection_instance(projected_sessions: list[dict], projection_instance_key: str) -> dict | None:
    for session in projected_sessions:
        if str(session.get("projection_instance_key") or "") == str(projection_instance_key or ""):
            return session
    return None


def build_projected_activity_contributions(projected_sessions: list[dict]) -> list[dict]:
    """Return display-safe contribution slices scaled to projected duration."""
    contributions: list[dict] = []
    for session in projected_sessions:
        rows = [dict(row) for row in session.get("_projection_contributions") or []]
        if not rows or int(session.get("duration_seconds") or 0) <= 0:
            continue
        display_total = max(0, int(session.get("duration_seconds") or 0))
        durations = allocate_duration(display_total, rows)
        for row, duration in zip(rows, durations):
            row["duration_seconds"] = duration
            row["projection_instance_key"] = session.get("projection_instance_key")
            row["projection_kind"] = session.get("projection_kind")
            row["project_id"] = session.get("project_id")
            row["project_name"] = session.get("project_name")
            row["project_description"] = session.get("project_description")
            row["is_report_project"] = session.get("is_report_project")
            row["is_report_classified"] = session.get("is_report_classified")
            row["is_report_uncategorized"] = session.get("is_report_uncategorized")
            contributions.append(row)
    return contributions


def allocate_duration(display_total: int, rows: list[dict]) -> list[int]:
    """Deterministically allocate a session duration across contribution rows."""
    total = max(0, int(display_total or 0))
    bases = [max(0, int(row.get("_basis_duration_seconds") or row.get("duration_seconds") or 0)) for row in rows]
    basis_total = sum(bases)
    if not rows:
        return []
    if total <= 0:
        return [0 for _ in rows]
    if basis_total <= 0:
        result = [0 for _ in rows]
        result[0] = total
        return result
    floors = [(total * basis) // basis_total for basis in bases]
    remainder = total - sum(floors)
    ranked = sorted(
        range(len(rows)),
        key=lambda index: (
            -((total * bases[index]) % basis_total),
            _member_key(rows[index]),
        ),
    )
    for index in ranked[:remainder]:
        floors[index] += 1
    return floors


def finalize_projected_session(session: dict) -> dict:
    """Rebuild all aggregate fields from members, edits and contributions."""
    rows = [dict(row) for row in session.get("_projection_contributions") or []]
    for row in rows:
        row.setdefault("_basis_duration_seconds", int(row.get("duration_seconds") or 0))
    members = _sorted_members(session.get("member_slices") or rows)
    session["member_slices"] = members
    session["activity_ids"] = _ordered_unique([int(member.get("activity_id") or 0) for member in members if int(member.get("activity_id") or 0) > 0])
    if members:
        session["anchor_activity_id"] = int(members[0].get("activity_id") or 0)
        session["first_activity_id"] = session["anchor_activity_id"] or None
    start_values = [str(member.get("slice_start_time") or member.get("start_time") or "") for member in members]
    end_values = [str(member.get("slice_end_time") or member.get("end_time") or "") for member in members]
    if start_values:
        session["start_time"] = min(value for value in start_values if value)
    if end_values:
        session["end_time"] = max(value for value in end_values if value)
    raw_duration = sum(max(0, int(row.get("_basis_duration_seconds") or row.get("duration_seconds") or 0)) for row in rows)
    session["raw_duration_seconds"] = raw_duration
    if bool(session.get("has_duration_override")) and session.get("adjusted_duration_seconds") is not None:
        final_duration = max(0, int(session.get("adjusted_duration_seconds") or 0))
    else:
        final_duration = raw_duration
        session["adjusted_duration_seconds"] = None
        session["has_duration_override"] = False
    allocated = allocate_duration(final_duration, rows)
    for row, duration in zip(rows, allocated):
        row["duration_seconds"] = duration
        row["projection_instance_key"] = session.get("projection_instance_key")
        row["projection_kind"] = session.get("projection_kind")
        row["project_id"] = session.get("project_id")
        row["project_name"] = session.get("project_name")
        row["project_description"] = session.get("project_description")
        row["report_project_id"] = session.get("project_id")
        row["report_project_name"] = session.get("project_name")
        row["report_project_description"] = session.get("project_description")
        row["is_report_project"] = session.get("is_report_project")
        row["is_report_classified"] = session.get("is_report_classified")
        row["is_report_uncategorized"] = session.get("is_report_uncategorized")
    session["_projection_contributions"] = rows
    session["event_count"] = len(rows)
    session["duration_seconds"] = final_duration
    session["display_duration_seconds"] = final_duration
    session["closed_duration_seconds"] = 0 if bool(session.get("is_in_progress")) else final_duration
    session["activity_member_hash"] = base_projection_key(str(session.get("report_date") or ""), members).split(":", 1)[1]
    if not str(session.get("projection_instance_key") or ""):
        session["projection_instance_key"] = base_projection_key(str(session.get("report_date") or ""), members)
    session["editable"] = bool(session.get("editable", True)) and not bool(session.get("is_in_progress"))
    session["exportable"] = bool(session.get("exportable", True)) and not bool(session.get("is_in_progress"))
    session["projection_revision"] = projection_revision(session)
    session["session_detail_revision"] = session["projection_revision"]
    return session


def _merge_sessions(source: dict, target: dict, operation: dict) -> dict:
    merged = deepcopy(target)
    operation_id = int(operation.get("id") or 0)
    group = str(operation.get("operation_group_key") or f"operation:{operation_id}")
    members = _sorted_members([*(source.get("member_slices") or []), *(target.get("member_slices") or [])])
    origins = _ordered_unique([*(source.get("origin_activity_member_hashes") or []), *(target.get("origin_activity_member_hashes") or [])])
    merged.update(
        {
            "projection_instance_key": f"merge:{group}",
            "projection_instance_key": merge_projection_key(group),
            "projection_kind": "merge",
            "operation_id": operation_id,
            "operation_group_key": group,
            "member_slices": members,
            "activity_ids": _ordered_unique([*(source.get("activity_ids") or []), *(target.get("activity_ids") or [])]),
            "origin_activity_member_hashes": origins,
            "_projection_contributions": [*(source.get("_projection_contributions") or []), *(target.get("_projection_contributions") or [])],
            "has_duration_override": False,
            "adjusted_duration_seconds": None,
            "_applied_commands": [*(source.get("_applied_commands") or []), *(target.get("_applied_commands") or [])],
        }
    )
    return merged


def _hide_activity_members(session: dict, operation: dict) -> None:
    hidden = {_member_key(member) for member in operation.get("members", {}).get("hidden_activity", [])}
    if not hidden:
        operation["_engine_match_state"] = CONFLICT
        return
    contributions = list(session.get("_projection_contributions") or [])
    current_allocated = build_projected_activity_contributions([session])
    current_by_member = {_member_key(row): row for row in current_allocated}
    session["_projection_contributions"] = [
        dict(current_by_member.get(_member_key(row), row))
        for row in contributions
        if _member_key(row) not in hidden
    ]
    session["member_slices"] = [member for member in session.get("member_slices") or [] if _member_key(member) not in hidden]
    hidden_ids = {int(member[1]) for member in hidden}
    session["activity_ids"] = [aid for aid in session.get("activity_ids") or [] if int(aid) not in hidden_ids or any(int(item.get("activity_id") or 0) == int(aid) for item in session["member_slices"])]
    if bool(session.get("has_duration_override")):
        session["adjusted_duration_seconds"] = sum(int(row.get("duration_seconds") or 0) for row in session["_projection_contributions"])


def _mark_unresolved(operation: dict, known_members: set[tuple]) -> None:
    members = [member for role in (operation.get("members") or {}).values() for member in role]
    found = any(_member_key(member) in known_members for member in members)
    operation["_engine_match_state"] = CONFLICT if found else ORPHANED


def _refresh_capabilities(sessions: list[dict]) -> None:
    for index, session in enumerate(sessions):
        kind = str(session.get("projection_kind") or "base")
        normal = str(session.get("row_kind") or "project_session") == "project_session" and not bool(session.get("is_in_progress"))
        session["can_hide"] = normal
        session["can_copy"] = normal
        session["can_hide_activity"] = normal and bool(session.get("_projection_contributions"))
        session["can_split"] = kind == "merge"
        session["can_merge_previous"] = normal and kind != "copy" and index > 0 and _mergeable_neighbour(sessions[index - 1])
        session["can_merge_next"] = normal and kind != "copy" and index + 1 < len(sessions) and _mergeable_neighbour(sessions[index + 1])
        session["projection_revision"] = projection_revision(session)
        session["session_detail_revision"] = session["projection_revision"]


def _mergeable_neighbour(session: dict) -> bool:
    return str(session.get("row_kind") or "project_session") == "project_session" and not bool(session.get("is_in_progress")) and str(session.get("projection_kind") or "base") != "copy"


def _member_key(member: dict) -> tuple[str, int, str]:
    return member_identity_key(member)


def _sorted_members(members: list[dict]) -> list[dict]:
    unique = {_member_key(member): dict(member) for member in members}
    return [unique[key] for key in sorted(unique)]


def _ordered_unique(values: list) -> list:
    seen: set = set()
    result = []
    for value in values:
        marker = str(value)
        if marker not in seen:
            seen.add(marker)
            result.append(value)
    return result


def _apply_edit_session(session: dict, operation: dict) -> None:
    payload = operation.get("payload") or {}
    if int(payload.get("payload_version") or 1) != 1:
        operation["_engine_match_state"] = CONFLICT
        return
    project = payload.get("project") if isinstance(payload.get("project"), dict) else None
    if project:
        mode = str(project.get("mode") or "unchanged")
        if mode == "set":
            session["project_id"] = int(project.get("project_id") or 0)
            session["project_name"] = str(project.get("project_name") or session.get("project_name") or "")
            session["project_description"] = str(project.get("project_description") or "")
            session["project_is_deleted"] = bool(project.get("project_is_deleted"))
            session["project_is_archived"] = bool(project.get("project_is_archived"))
            session["has_project_override"] = True
            session["is_report_project"] = bool(project.get("is_report_project", True))
            session["is_report_classified"] = bool(project.get("is_report_classified", True))
            session["is_report_uncategorized"] = bool(project.get("is_report_uncategorized", False))
        elif mode == "inherit":
            session["project_id"] = session.get("raw_assignment_project_id") or session.get("project_id")
            session["project_name"] = session.get("raw_assignment_project_name") or session.get("project_name")
            session["project_description"] = session.get("raw_assignment_project_description") or ""
            session["has_project_override"] = False
    duration = payload.get("duration") if isinstance(payload.get("duration"), dict) else None
    if duration:
        mode = str(duration.get("mode") or "unchanged")
        if mode == "set":
            session["adjusted_duration_seconds"] = max(0, int(duration.get("value") or 0))
            session["has_duration_override"] = True
        elif mode == "inherit":
            session["adjusted_duration_seconds"] = None
            session["has_duration_override"] = False
    note = payload.get("note") if isinstance(payload.get("note"), dict) else None
    if note:
        mode = str(note.get("mode") or "unchanged")
        if mode == "set":
            session["session_note"] = str(note.get("value") or "")
        elif mode == "inherit":
            session["session_note"] = ""


def _record_command(session: dict, operation: dict) -> None:
    commands = list(session.get("_applied_commands") or [])
    commands.append(
        {
            "id": int(operation.get("id") or 0),
            "replay_order": int(operation.get("replay_order") or operation.get("id") or 0),
            "operation_type": str(operation.get("operation_type") or ""),
            "payload": operation.get("payload") or {},
        }
    )
    session["_applied_commands"] = commands
