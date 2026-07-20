"""Single transactional unit of work for immutable report mutations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping, Sequence

from ..constants import STATUS_NORMAL
from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from . import (
    assignment_command_service,
    project_lifecycle_policy,
    report_operation_repository,
)
from . import report_session_operation_engine as engine
from .report_fact_query_service import get_uncategorized_project_id
from .report_projection_identity import member_identity_key, stable_json_hash
from .report_projection_model import (
    DatabaseBusyError,
    InvalidInputError,
    MutationResult,
    OperationNoEffectError,
    OperationNotAllowedError,
    ProjectNotSelectableError,
    RequestIdConflictError,
    RevisionConflictError,
    SessionNotAdjacentError,
    StaleSelectionError,
    TargetRevisionConflictError,
    project_state_from_row,
)
from .report_replay_binding import ReplayBinding
from .report_session_operation_engine import APPLIED, OPERATION_PAYLOAD_VERSION


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
        payload_input={
            "project_id": project_id,
            "adjusted_duration_seconds": adjusted_duration_seconds,
            "note": note,
        },
    )


def hide_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
) -> MutationResult:
    return _run_uow(
        report_date,
        request_id,
        "hide_session",
        projection_instance_key,
        expected_projection_revision,
    )


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
    return _run_uow(
        report_date,
        request_id,
        "merge_sessions",
        projection_instance_key,
        expected_projection_revision,
        target_instance_key=target_projection_instance_key,
        target_expected_revision=target_expected_projection_revision,
        direction=direction,
    )


def split_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
) -> MutationResult:
    return _run_uow(
        report_date,
        request_id,
        "split_session",
        projection_instance_key,
        expected_projection_revision,
    )


def copy_session(
    report_date: str,
    projection_instance_key: str,
    expected_projection_revision: str,
    request_id: str,
) -> MutationResult:
    return _run_uow(
        report_date,
        request_id,
        "copy_session",
        projection_instance_key,
        expected_projection_revision,
    )


def hide_session_activity(
    report_date: str,
    projection_instance_key: str,
    summary_id: str,
    expected_projection_revision: str,
    request_id: str,
) -> MutationResult:
    return _run_uow(
        report_date,
        request_id,
        "hide_activity",
        projection_instance_key,
        expected_projection_revision,
        payload_input={"summary_id": summary_id},
    )


def load_operations(
    report_date: str,
    *,
    conn=None,
) -> list[dict[str, Any]]:
    if conn is None:
        with get_connection() as read_conn:
            return report_operation_repository.load_operations(
                read_conn,
                report_date,
            )
    return report_operation_repository.load_operations(conn, report_date)


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
    if (
        not request_id
        or not report_date
        or not source_instance_key
        or not source_expected_revision
    ):
        raise InvalidInputError()
    values = dict(payload_input or {})
    intent = {
        "report_date": report_date,
        "operation_type": operation_type,
        "source_instance_key": source_instance_key,
        "source_expected_revision": source_expected_revision,
        "target_instance_key": target_instance_key,
        "target_expected_revision": target_expected_revision,
        "direction": direction,
        "payload_input": values,
    }
    input_signature = stable_json_hash(intent)

    try:
        with DomainUnitOfWork(
            (DataGenerationNamespace.REPORT_STRUCTURE,)
        ) as uow:
            conn = uow.connection
            receipt = _find_request(conn, request_id)
            if receipt is not None:
                if str(receipt["input_signature"]) != input_signature:
                    raise RequestIdConflictError()
                return _mutation_result_from_receipt(receipt)

            from .report_projection_snapshot_service import build_visible_snapshot

            before = build_visible_snapshot(report_date, report_date, conn=conn)
            source = _find_entry(before.final_sessions, source_instance_key)
            if source is None:
                raise StaleSelectionError()
            if (
                str(source.get("projection_revision") or "")
                != source_expected_revision
            ):
                raise RevisionConflictError()

            target = None
            if operation_type == "merge_sessions":
                if (
                    direction not in {"previous", "next"}
                    or not target_instance_key
                    or not target_expected_revision
                ):
                    raise InvalidInputError()
                target = _find_entry(
                    before.final_sessions,
                    target_instance_key,
                )
                if target is None:
                    raise StaleSelectionError()
                if (
                    str(target.get("projection_revision") or "")
                    != target_expected_revision
                ):
                    raise TargetRevisionConflictError()
                _require_adjacent(
                    before.final_sessions,
                    source,
                    target,
                    direction,
                )

            _require_capability(operation_type, source, direction)
            payload, roles, undo_of = _operation_input(
                conn,
                operation_type,
                source,
                target,
                values,
            )
            if bool(source.get("is_in_progress")) and "duration" in payload:
                raise OperationNotAllowedError()

            sequence = _next_sequence(conn, report_date)
            operation_id = _next_operation_id(conn)
            candidate = _candidate_operation(
                operation_id=operation_id,
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
                roles=roles,
            )
            existing = report_operation_repository.load_operations(
                conn,
                report_date,
            )
            preview = engine.replay_operations(
                before.base_sessions,
                [*existing, candidate],
                _project_states(conn),
            )
            diagnostic = next(
                (
                    item
                    for item in preview.operation_diagnostics
                    if item.operation_id == operation_id
                ),
                None,
            )
            effective = bool(
                diagnostic
                and diagnostic.state == APPLIED
                and _expected_effect(
                    operation_type,
                    operation_id,
                    before.final_sessions,
                    preview.final_entries,
                    source,
                )
            )
            if not effective:
                current = _find_entry(
                    before.final_sessions,
                    source_instance_key,
                )
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
                _insert_receipt(conn, request_id, input_signature, result)
                return result

            committed_candidate = candidate
            committed_roles = roles
            committed_source_key = source_instance_key
            if bool(source.get("is_in_progress")):
                open_activity_id = _persist_open_edit_assignment(
                    conn,
                    source,
                    values.get("project_id"),
                )
                current_snapshot = build_visible_snapshot(
                    report_date,
                    report_date,
                    conn=conn,
                )
                current_source = _find_open_activity_entry(
                    current_snapshot.final_sessions,
                    open_activity_id,
                )
                if current_source is None or not bool(
                    current_source.get("is_in_progress")
                ):
                    raise OperationNotAllowedError()
                current_payload, current_roles, current_undo = _operation_input(
                    conn,
                    operation_type,
                    current_source,
                    None,
                    values,
                )
                if "duration" in current_payload:
                    raise OperationNotAllowedError()
                committed_source_key = str(
                    current_source.get("projection_instance_key") or ""
                )
                current_revision = str(
                    current_source.get("projection_revision") or ""
                )
                if not committed_source_key or not current_revision:
                    raise StaleSelectionError()
                committed_roles = current_roles
                committed_candidate = _candidate_operation(
                    operation_id=operation_id,
                    report_date=report_date,
                    sequence=sequence,
                    operation_type=operation_type,
                    source_instance_key=committed_source_key,
                    source_expected_revision=current_revision,
                    target_instance_key=None,
                    target_expected_revision=None,
                    direction=None,
                    undo_of_operation_id=current_undo,
                    payload=current_payload,
                    roles=current_roles,
                )

            _insert_operation(conn, committed_candidate)
            _insert_members(conn, operation_id, committed_roles)

            after = build_visible_snapshot(report_date, report_date, conn=conn)
            applied = next(
                (
                    item
                    for item in after.operation_diagnostics
                    if item.operation_id == operation_id
                ),
                None,
            )
            if applied is None or applied.state != APPLIED:
                reason = (
                    applied.reason if applied is not None else "missing_diagnostic"
                )
                raise OperationNoEffectError(reason)
            result = MutationResult(
                request_id=request_id,
                outcome_type="operation_committed",
                operation_id=operation_id,
                report_date=report_date,
                selection_hint=_post_selection(
                    operation_type,
                    operation_id,
                    committed_source_key,
                    after.final_sessions,
                ),
                snapshot_revision=after.snapshot_revision,
            )
            _insert_receipt(conn, request_id, input_signature, result)
            return result
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower() or "busy" in str(exc).lower():
            raise DatabaseBusyError() from exc
        raise


def _operation_input(
    conn,
    operation_type: str,
    source: dict,
    target: dict | None,
    values: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, list[dict]], int | None]:
    payload: dict[str, Any] = {
        "payload_version": OPERATION_PAYLOAD_VERSION,
        "replay_binding": ReplayBinding.MEMBERS.value,
    }
    roles = {"source": _members(source)}
    undo_of: int | None = None
    if operation_type == "edit_session":
        project_id = values.get("project_id")
        if project_id is not None:
            row = conn.execute(
                "SELECT * FROM project WHERE id = ?",
                (int(project_id),),
            ).fetchone()
            if not project_lifecycle_policy.project_selectable_for_editing(
                dict(row) if row else None
            ):
                raise ProjectNotSelectableError()
            payload["project"] = {
                "mode": "set",
                "project_id": int(project_id),
            }
        elif bool(source.get("has_project_override")):
            payload["project"] = {"mode": "inherit"}

        duration = _duration_edit_payload(
            source,
            values.get("adjusted_duration_seconds"),
        )
        if duration is not None:
            payload["duration"] = duration

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
        undo_of = _producer_operation_id(
            str(source.get("projection_instance_key") or ""),
            "merge",
        )
        if undo_of is None:
            raise OperationNotAllowedError()
    return payload, roles, undo_of


def _duration_edit_payload(
    source: Mapping[str, Any],
    requested_value: Any,
) -> dict[str, Any] | None:
    has_override = bool(source.get("has_duration_override"))
    if requested_value is None:
        return {"mode": "inherit"} if has_override else None
    requested = int(requested_value)
    current = int(
        source.get("adjusted_duration_seconds")
        if has_override
        and source.get("adjusted_duration_seconds") is not None
        else source.get("duration_seconds")
        or 0
    )
    if requested == current or requested == _rounded_editor_seconds(current):
        return None
    return {"mode": "set", "value": requested}


def _rounded_editor_seconds(seconds: int) -> int:
    value = max(0, int(seconds or 0))
    return ((value + 30) // 60) * 60


def _affected_members(source: dict, summary_id: str) -> list[dict]:
    from . import project_activity_summary_service as summaries

    contributions = list(source.get("_projection_contributions") or [])
    result = summaries.build_activity_summary_rows(
        contributions,
        str(source.get("report_date") or ""),
        str(source.get("projection_instance_key") or ""),
        str(source.get("projection_revision") or ""),
    )
    summary = next(
        (
            item
            for item in result
            if str(item.get("summary_id") or "") == summary_id
        ),
        None,
    )
    if summary is None:
        return []
    identity = str(summary.get("activity_identity_key") or "")
    return [
        _member(row)
        for row in contributions
        if summaries.activity_group_key(row) == identity
    ]


def _candidate_operation(**values: Any) -> dict[str, Any]:
    return {
        "id": int(values["operation_id"]),
        "report_date": str(values["report_date"]),
        "sequence": int(values["sequence"]),
        "operation_type": str(values["operation_type"]),
        "source_instance_key": str(values["source_instance_key"]),
        "source_expected_revision": str(values["source_expected_revision"]),
        "target_instance_key": values.get("target_instance_key"),
        "target_expected_revision": values.get("target_expected_revision"),
        "direction": values.get("direction"),
        "undo_of_operation_id": values.get("undo_of_operation_id"),
        "payload": dict(values["payload"]),
        "members": {
            str(role): [dict(member) for member in members]
            for role, members in values["roles"].items()
        },
        "created_at": now_str(),
    }


def _insert_operation(conn, operation: Mapping[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO report_session_operation(
            id, report_date, sequence, operation_type, source_instance_key,
            source_expected_revision, target_instance_key,
            target_expected_revision, direction, undo_of_operation_id,
            payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(operation["id"]),
            operation["report_date"],
            int(operation["sequence"]),
            operation["operation_type"],
            operation["source_instance_key"],
            operation["source_expected_revision"],
            operation.get("target_instance_key"),
            operation.get("target_expected_revision"),
            operation.get("direction"),
            operation.get("undo_of_operation_id"),
            json.dumps(
                dict(operation["payload"]),
                ensure_ascii=False,
                sort_keys=True,
            ),
            operation["created_at"],
        ),
    )


def _insert_members(
    conn,
    operation_id: int,
    roles: Mapping[str, list[dict]],
) -> None:
    for role, members in roles.items():
        for order, member in enumerate(members):
            conn.execute(
                """
                INSERT INTO report_session_operation_member(
                    operation_id, role, activity_id, report_date,
                    slice_start_time, display_order
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(operation_id),
                    role,
                    member["activity_id"],
                    member["report_date"],
                    member["slice_start_time"],
                    order,
                ),
            )


def _persist_open_edit_assignment(
    conn,
    source: Mapping[str, Any],
    project_id: Any,
) -> int:
    activity_id = _open_activity_id(source)
    if activity_id <= 0:
        raise OperationNotAllowedError()
    if project_id is None:
        return activity_id
    if not assignment_command_service.upsert_assignment(
        conn,
        activity_id=activity_id,
        project_id=int(project_id),
        confidence=100,
        source="manual",
        is_manual=True,
    ):
        raise OperationNotAllowedError()
    return activity_id


def _find_open_activity_entry(
    entries: Sequence[Mapping[str, Any]],
    activity_id: int,
) -> dict | None:
    for entry in entries:
        if int(entry.get("open_activity_id") or 0) == int(activity_id):
            return dict(entry)
        if int(activity_id) in {
            int(value or 0) for value in entry.get("activity_ids") or []
        }:
            return dict(entry)
    return None


def _find_request(conn, request_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM report_mutation_request WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    return dict(row) if row else None


def _insert_receipt(
    conn,
    request_id: str,
    signature: str,
    result: MutationResult,
) -> None:
    timestamp = now_str()
    conn.execute(
        """
        INSERT INTO report_mutation_request(
            request_id, input_signature, outcome_type, operation_id,
            result_json, created_at, committed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id,
            signature,
            result.outcome_type,
            result.operation_id,
            json.dumps(
                result.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
            ),
            timestamp,
            timestamp,
        ),
    )


def _mutation_result_from_receipt(
    row: Mapping[str, Any],
) -> MutationResult:
    try:
        value = json.loads(str(row.get("result_json") or "{}"))
        return MutationResult(**value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RequestIdConflictError("请求回执损坏") from exc


def _next_sequence(conn, report_date: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(sequence), 0) + 1
        FROM report_session_operation
        WHERE report_date = ?
        """,
        (report_date,),
    ).fetchone()
    return int(row[0])


def _next_operation_id(conn) -> int:
    maximum = int(
        conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM report_session_operation"
        ).fetchone()[0]
        or 0
    )
    sequence = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'report_session_operation'"
    ).fetchone()
    allocated = int(sequence[0] or 0) if sequence else 0
    return max(maximum, allocated) + 1


def _project_states(conn) -> list:
    uncategorized_id = get_uncategorized_project_id(conn)
    return [
        project_state_from_row(
            dict(row),
            uncategorized_id=uncategorized_id,
        )
        for row in conn.execute("SELECT * FROM project ORDER BY id").fetchall()
    ]


def _members(entry: Mapping[str, Any]) -> list[dict]:
    return [_member(item) for item in entry.get("member_slices") or []]


def _member(value: Mapping[str, Any]) -> dict[str, Any]:
    report_date, activity_id, start = member_identity_key(dict(value))
    return {
        "report_date": report_date,
        "activity_id": activity_id,
        "slice_start_time": start,
    }


def _find_entry(
    entries: Sequence[Mapping[str, Any]],
    key: str,
) -> dict | None:
    for item in entries:
        if str(item.get("projection_instance_key") or "") == key:
            return dict(item)
    return None


def _require_adjacent(
    entries: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
    target: Mapping[str, Any],
    direction: str,
) -> None:
    ordered = sorted(
        entries,
        key=lambda item: (
            str(item.get("start_time") or ""),
            str(item.get("projection_instance_key") or ""),
        ),
    )
    source_key = str(source.get("projection_instance_key") or "")
    target_key = str(target.get("projection_instance_key") or "")
    keys = [str(item.get("projection_instance_key") or "") for item in ordered]
    source_index = keys.index(source_key)
    target_index = keys.index(target_key)
    expected = source_index - 1 if direction == "previous" else source_index + 1
    if target_index != expected:
        raise SessionNotAdjacentError()


def _require_capability(
    operation_type: str,
    source: Mapping[str, Any],
    direction: str | None,
) -> None:
    if bool(source.get("is_in_progress")):
        safe_open_edit = (
            operation_type == "edit_session"
            and str(source.get("status_code") or source.get("status") or "")
            == STATUS_NORMAL
            and _open_activity_id(source) > 0
            and str(source.get("row_kind") or "project_session")
            == "project_session"
        )
        if not safe_open_edit:
            raise OperationNotAllowedError()
        return
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


def _open_activity_id(source: Mapping[str, Any]) -> int:
    value = int(source.get("open_activity_id") or 0)
    if value > 0:
        return value
    activity_ids = [int(item or 0) for item in source.get("activity_ids") or []]
    return activity_ids[-1] if activity_ids else 0


def _producer_operation_id(key: str, expected_prefix: str) -> int | None:
    try:
        prefix, raw = key.split(":", 1)
        value = int(raw)
        return value if prefix == expected_prefix and value > 0 else None
    except (ValueError, TypeError):
        return None


def _expected_effect(
    operation_type: str,
    operation_id: int,
    before_entries: Sequence[Mapping[str, Any]],
    after_entries: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any],
) -> bool:
    del before_entries
    key = str(source.get("projection_instance_key") or "")
    if operation_type == "copy_session":
        return _find_entry(after_entries, f"copy:{operation_id}") is not None
    if operation_type == "merge_sessions":
        return _find_entry(after_entries, f"merge:{operation_id}") is not None
    if operation_type in {"hide_session", "split_session"}:
        return _find_entry(after_entries, key) is None
    current = _find_entry(after_entries, key)
    return current is None or str(
        current.get("projection_revision") or ""
    ) != str(source.get("projection_revision") or "")


def _post_selection(
    operation_type: str,
    operation_id: int,
    source_key: str,
    entries: Sequence[Mapping[str, Any]],
) -> dict | None:
    if operation_type in {"hide_session", "split_session"}:
        return None
    if operation_type == "copy_session":
        key = f"copy:{operation_id}"
    elif operation_type == "merge_sessions":
        key = f"merge:{operation_id}"
    else:
        key = source_key
    return _selection_hint(_find_entry(entries, key))


def _selection_hint(
    entry: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    if entry is None:
        return None
    return {
        "projection_instance_key": str(
            entry.get("projection_instance_key") or ""
        ),
        "projection_revision": str(entry.get("projection_revision") or ""),
    }


__all__ = [
    "copy_session",
    "edit_session",
    "hide_session",
    "hide_session_activity",
    "load_operations",
    "merge_session",
    "split_session",
]
