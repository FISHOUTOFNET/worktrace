"""Pure, in-memory projection of user report-session operations.

The engine deliberately knows nothing about SQLite or the WebView.  It only
applies already-resolved operation records to the final automatic sessions.
"""

from __future__ import annotations

from copy import deepcopy


ACTIVE = "active"
CONFLICT = "conflict"
ORPHANED = "orphaned"


def apply_operations(base_sessions: list[dict], operations: list[dict]) -> list[dict]:
    """Apply active operations in stable creation order.

    Operation dictionaries are annotated with ``_engine_match_state`` when
    their persisted identity no longer resolves.  The caller may persist that
    state; this module itself never writes anything.
    """
    sessions = [deepcopy(session) for session in base_sessions]
    known_members = {
        _member_key(member)
        for session in base_sessions
        for member in session.get("member_slices") or []
    }
    for operation in sorted(operations, key=lambda item: (int(item.get("id") or 0), str(item.get("created_at") or ""))):
        if str(operation.get("match_state") or ACTIVE) != ACTIVE:
            continue
        operation_type = str(operation.get("operation_type") or "")
        source = resolve_projection_instance(sessions, str(operation.get("base_instance_key") or ""))
        target = resolve_projection_instance(sessions, str(operation.get("target_instance_key") or ""))
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
            continue
        if source is None:
            _mark_unresolved(operation, known_members)
            continue
        if operation_type == "hide_session":
            sessions.remove(source)
        elif operation_type == "copy_session":
            copy = deepcopy(source)
            operation_id = int(operation.get("id") or 0)
            copy.update(
                {
                    "projection_instance_key": f"copy:{operation_id}",
                    "projection_kind": "copy",
                    "operation_id": operation_id,
                    "operation_group_key": None,
                    "can_merge_previous": False,
                    "can_merge_next": False,
                }
            )
            sessions.insert(sessions.index(source) + 1, copy)
        elif operation_type == "hide_activity":
            _hide_activity_members(source, operation)
            if int(source.get("duration_seconds") or 0) <= 0:
                sessions.remove(source)
        else:
            operation["_engine_match_state"] = CONFLICT
    _refresh_capabilities(sessions)
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
        raw_total = sum(max(0, int(row.get("duration_seconds") or 0)) for row in rows)
        display_total = max(0, int(session.get("duration_seconds") or 0))
        allocated = 0
        for index, row in enumerate(rows):
            raw_duration = max(0, int(row.get("duration_seconds") or 0))
            if index == len(rows) - 1:
                duration = max(0, display_total - allocated)
            elif raw_total:
                duration = (display_total * raw_duration) // raw_total
                allocated += duration
            else:
                duration = 0
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


def _merge_sessions(source: dict, target: dict, operation: dict) -> dict:
    merged = deepcopy(target)
    operation_id = int(operation.get("id") or 0)
    group = str(operation.get("operation_group_key") or f"operation:{operation_id}")
    members = _sorted_members([*(source.get("member_slices") or []), *(target.get("member_slices") or [])])
    origins = _ordered_unique([*(source.get("origin_activity_member_hashes") or []), *(target.get("origin_activity_member_hashes") or [])])
    merged.update(
        {
            "projection_instance_key": f"merge:{group}",
            "projection_kind": "merge",
            "operation_id": operation_id,
            "operation_group_key": group,
            "member_slices": members,
            "activity_ids": _ordered_unique([*(source.get("activity_ids") or []), *(target.get("activity_ids") or [])]),
            "origin_activity_member_hashes": origins,
            "duration_seconds": int(source.get("duration_seconds") or 0) + int(target.get("duration_seconds") or 0),
            "display_duration_seconds": int(source.get("display_duration_seconds") or source.get("duration_seconds") or 0) + int(target.get("display_duration_seconds") or target.get("duration_seconds") or 0),
            "closed_duration_seconds": int(source.get("closed_duration_seconds") or 0) + int(target.get("closed_duration_seconds") or 0),
            "_projection_contributions": [*(source.get("_projection_contributions") or []), *(target.get("_projection_contributions") or [])],
        }
    )
    return merged


def _hide_activity_members(session: dict, operation: dict) -> None:
    hidden = {_member_key(member) for member in operation.get("members", {}).get("hidden_activity", [])}
    if not hidden:
        operation["_engine_match_state"] = CONFLICT
        return
    contributions = list(session.get("_projection_contributions") or [])
    removed = sum(int(row.get("duration_seconds") or 0) for row in contributions if _member_key(row) in hidden)
    session["_projection_contributions"] = [row for row in contributions if _member_key(row) not in hidden]
    session["member_slices"] = [member for member in session.get("member_slices") or [] if _member_key(member) not in hidden]
    hidden_ids = {int(member[1]) for member in hidden}
    session["activity_ids"] = [aid for aid in session.get("activity_ids") or [] if int(aid) not in hidden_ids or any(int(item.get("activity_id") or 0) == int(aid) for item in session["member_slices"])]
    session["duration_seconds"] = max(0, int(session.get("duration_seconds") or 0) - removed)
    session["display_duration_seconds"] = session["duration_seconds"]
    session["closed_duration_seconds"] = max(0, int(session.get("closed_duration_seconds") or 0) - removed)


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


def _mergeable_neighbour(session: dict) -> bool:
    return str(session.get("row_kind") or "project_session") == "project_session" and not bool(session.get("is_in_progress")) and str(session.get("projection_kind") or "base") != "copy"


def _member_key(member: dict) -> tuple[str, int, str, str]:
    return (str(member.get("report_date") or ""), int(member.get("activity_id") or member.get("id") or 0), str(member.get("slice_start_time") or member.get("start_time") or ""), str(member.get("slice_end_time") or member.get("end_time") or ""))


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
