"""Deterministic, side-effect-free replay of immutable report operations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .report_projection_identity import (
    base_projection_key,
    copy_projection_key,
    member_identity_key,
    merge_projection_key,
    projection_revision,
    snapshot_revision,
)
from .report_projection_model import (
    OperationDiagnostic,
    OperationRecord,
    ProjectState,
    ReportMemberIdentity,
    freeze_value,
    thaw_value,
)
from .report_operation_contract import (
    OPERATION_PAYLOAD_VERSION,
    allowed_payload_keys,
    expected_roles,
)
from .report_replay_binding import ReplayBinding

APPLIED = "applied"
CONFLICT = "conflict"
ORPHANED = "orphaned"
SUPERSEDED_BY_UNDO = "superseded_by_undo"

_freeze_value = freeze_value
_mutable_value = thaw_value


@dataclass(frozen=True)
class ReplayResult:
    final_entries: tuple[Mapping[str, Any], ...]
    final_contributions: tuple[Mapping[str, Any], ...]
    operation_diagnostics: tuple[OperationDiagnostic, ...]
    snapshot_revision: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "final_entries",
            tuple(_freeze_value(item) for item in self.final_entries),
        )
        object.__setattr__(
            self,
            "final_contributions",
            tuple(_freeze_value(item) for item in self.final_contributions),
        )
        object.__setattr__(
            self,
            "operation_diagnostics",
            tuple(self.operation_diagnostics),
        )


def replay_operations(
    base_sessions: Sequence[Mapping[str, Any]],
    operation_records: Sequence[OperationRecord | Mapping[str, Any]],
    project_states: Sequence[ProjectState] | Mapping[int, ProjectState] = (),
) -> ReplayResult:
    """Replay records without modifying sessions, records, payloads or members."""

    projects = _project_map(project_states)
    sessions = [_prepare_session(item, projects) for item in base_sessions]
    records = tuple(
        sorted(
            (_coerce_operation(item) for item in operation_records),
            key=lambda operation: (operation.sequence, operation.id),
        )
    )
    valid_splits, invalid_split_reasons = _validate_splits(
        sessions,
        records,
        projects,
    )
    superseded, undo_by_operation = _undo_closure(records, valid_splits)
    diagnostics: list[OperationDiagnostic] = []

    for operation in records:
        if operation.operation_type == "split_session":
            reason = invalid_split_reasons.get(operation.id)
            diagnostics.append(
                _diagnostic(
                    operation,
                    CONFLICT if reason else APPLIED,
                    reason or "undo_applied",
                )
            )
            continue
        if operation.id in superseded:
            diagnostics.append(
                _diagnostic(
                    operation,
                    SUPERSEDED_BY_UNDO,
                    "superseded_by_undo",
                    undo_operation_id=undo_by_operation.get(operation.id),
                )
            )
            continue
        sessions, diagnostic = _apply_one(sessions, operation, projects)
        diagnostics.append(diagnostic)

    sessions = _ordered_sessions(sessions)
    _refresh_capabilities(sessions)
    contributions = tuple(build_projected_activity_contributions(sessions))
    result_diagnostics = tuple(
        sorted(
            diagnostics,
            key=lambda item: (item.sequence, item.operation_id),
        )
    )
    return ReplayResult(
        final_entries=tuple(sessions),
        final_contributions=contributions,
        operation_diagnostics=result_diagnostics,
        snapshot_revision=snapshot_revision(sessions, result_diagnostics),
    )


def build_projected_activity_contributions(
    projected_sessions: Sequence[Mapping[str, Any]],
) -> list[dict]:
    contributions: list[dict] = []
    for session in projected_sessions:
        rows = [
            _mutable_value(row)
            for row in session.get("_projection_contributions") or []
        ]
        allocations = allocate_duration(
            int(session.get("duration_seconds") or 0),
            rows,
        )
        for row, duration in zip(rows, allocations):
            row["duration_seconds"] = duration
            row["projection_instance_key"] = str(
                session.get("projection_instance_key") or ""
            )
            row["projection_revision"] = str(
                session.get("projection_revision") or ""
            )
            row["project_id"] = int(
                session.get("project_id") or row.get("project_id") or 0
            )
            row["project_name"] = str(
                session.get("project_name") or row.get("project_name") or ""
            )
            row["project_description"] = str(
                session.get("project_description") or ""
            )
            row["is_in_progress"] = bool(session.get("is_in_progress"))
            contributions.append(row)
    return contributions


def allocate_duration(
    display_total: int,
    rows: Sequence[Mapping[str, Any]],
) -> list[int]:
    if not rows:
        return []
    total = max(0, int(display_total))
    bases = [
        max(
            0,
            int(
                row.get(
                    "_basis_duration_seconds",
                    row.get("duration_seconds", 0),
                )
                or 0
            ),
        )
        for row in rows
    ]
    basis_total = sum(bases)
    if basis_total <= 0:
        quotient, remainder = divmod(total, len(rows))
        return [
            quotient + (1 if index < remainder else 0)
            for index in range(len(rows))
        ]
    raw = [total * basis / basis_total for basis in bases]
    result = [int(value) for value in raw]
    remainder = total - sum(result)
    order = sorted(
        range(len(rows)),
        key=lambda index: (
            -(raw[index] - result[index]),
            _member_key(rows[index]),
        ),
    )
    for index in order[:remainder]:
        result[index] += 1
    return result


def finalize_projected_session(
    session: dict[str, Any],
    project_state: ProjectState | None = None,
) -> dict[str, Any]:
    members = _sorted_members(session.get("member_slices") or [])
    session["member_slices"] = members
    session["activity_ids"] = sorted(
        {
            int(member.get("activity_id") or member.get("id") or 0)
            for member in members
        }
    )
    basis = sum(
        max(
            0,
            int(
                row.get(
                    "_basis_duration_seconds",
                    row.get("duration_seconds", 0),
                )
                or 0
            ),
        )
        for row in session.get("_projection_contributions") or []
    )
    if bool(session.get("has_duration_override")):
        duration = max(0, int(session.get("adjusted_duration_seconds") or 0))
    else:
        duration = basis
    session["duration_seconds"] = duration
    report_date = str(session.get("report_date") or "")
    session["activity_member_hash"] = base_projection_key(
        report_date,
        members,
    ).split(":", 1)[1]
    if not str(session.get("projection_instance_key") or ""):
        session["projection_instance_key"] = base_projection_key(
            report_date,
            members,
        )
    session["editable"] = bool(session.get("editable", True)) and not bool(
        session.get("is_in_progress")
    )
    session["exportable"] = bool(session.get("exportable", True)) and not bool(
        session.get("is_in_progress")
    )
    session["projection_revision"] = projection_revision(
        session,
        project_state=project_state,
    )
    return session


def _binding(operation: OperationRecord) -> ReplayBinding | None:
    try:
        return ReplayBinding(str(operation.payload.get("replay_binding") or ""))
    except ValueError:
        return None


def _apply_one(
    sessions: list[dict[str, Any]],
    operation: OperationRecord,
    projects: Mapping[int, ProjectState],
) -> tuple[list[dict[str, Any]], OperationDiagnostic]:
    if not _payload_is_valid(operation):
        return sessions, _diagnostic(operation, CONFLICT, "invalid_payload")
    source, source_reason = _resolve_bound_input(
        sessions,
        operation,
        "source",
        operation.source_instance_key,
    )
    if source is None:
        return sessions, _diagnostic(
            operation,
            source_reason,
            "source_" + source_reason,
        )

    operation_type = operation.operation_type
    if operation_type == "edit_session":
        edited = deepcopy(source)
        if not _apply_edit(edited, operation.payload, projects):
            return sessions, _diagnostic(
                operation,
                CONFLICT,
                "invalid_edit_payload",
            )
        finalize_projected_session(
            edited,
            projects.get(int(edited.get("project_id") or 0)),
        )
        return _replace_session(sessions, source, edited), _diagnostic(
            operation,
            APPLIED,
            "",
        )
    if operation_type == "hide_session":
        return _remove_sessions(sessions, source), _diagnostic(
            operation,
            APPLIED,
            "",
        )
    if operation_type == "copy_session":
        copied = deepcopy(source)
        copied["projection_instance_key"] = copy_projection_key(operation.id)
        copied["projection_kind"] = "copy"
        copied["operation_id"] = operation.id
        finalize_projected_session(
            copied,
            projects.get(int(copied.get("project_id") or 0)),
        )
        return _ordered_sessions([*sessions, copied]), _diagnostic(
            operation,
            APPLIED,
            "",
        )
    if operation_type == "hide_activity":
        affected = {
            _identity_tuple(member)
            for member in operation.members_for("affected")
        }
        current = {
            _member_key(member)
            for member in source.get("member_slices") or []
        }
        removed = affected & current
        if not affected or removed != affected:
            return sessions, _diagnostic(
                operation,
                CONFLICT,
                "hide_activity_member_contract_invalid",
            )
        edited = deepcopy(source)
        edited["member_slices"] = [
            member
            for member in edited.get("member_slices") or []
            if _member_key(member) not in removed
        ]
        edited["_projection_contributions"] = [
            row
            for row in edited.get("_projection_contributions") or []
            if _member_key(row) not in removed
        ]
        if not edited["member_slices"]:
            return _remove_sessions(sessions, source), _diagnostic(
                operation,
                APPLIED,
                "",
            )
        if bool(edited.get("has_duration_override")):
            old_rows = list(source.get("_projection_contributions") or [])
            allocated = allocate_duration(
                int(source.get("duration_seconds") or 0),
                old_rows,
            )
            edited["adjusted_duration_seconds"] = sum(
                value
                for row, value in zip(old_rows, allocated)
                if _member_key(row) not in removed
            )
        finalize_projected_session(
            edited,
            projects.get(int(edited.get("project_id") or 0)),
        )
        return _replace_session(sessions, source, edited), _diagnostic(
            operation,
            APPLIED,
            "",
        )
    if operation_type == "merge_sessions":
        target, target_reason = _resolve_bound_input(
            sessions,
            operation,
            "target",
            operation.target_instance_key or "",
        )
        if target is None:
            return sessions, _diagnostic(
                operation,
                target_reason,
                "target_" + target_reason,
            )
        if target is source:
            return sessions, _diagnostic(
                operation,
                CONFLICT,
                "same_merge_input",
            )
        ordered = _ordered_sessions(sessions)
        source_index = ordered.index(source)
        target_index = ordered.index(target)
        expected_index = (
            source_index - 1
            if operation.direction == "previous"
            else source_index + 1
        )
        if (
            operation.direction not in {"previous", "next"}
            or expected_index != target_index
        ):
            return sessions, _diagnostic(
                operation,
                CONFLICT,
                "session_not_adjacent",
            )
        if (
            str(source.get("projection_kind") or "base") == "copy"
            or str(target.get("projection_kind") or "base") == "copy"
        ):
            return sessions, _diagnostic(
                operation,
                CONFLICT,
                "copy_cannot_merge",
            )
        merged = _merge_sessions(source, target, operation.id)
        finalize_projected_session(
            merged,
            projects.get(int(merged.get("project_id") or 0)),
        )
        return _ordered_sessions(
            [
                item
                for item in sessions
                if item is not source and item is not target
            ]
            + [merged]
        ), _diagnostic(operation, APPLIED, "")
    return sessions, _diagnostic(
        operation,
        CONFLICT,
        "unknown_operation_type",
    )


def _validate_splits(
    base_sessions: list[dict[str, Any]],
    records: tuple[OperationRecord, ...],
    projects: Mapping[int, ProjectState],
) -> tuple[set[int], dict[int, str]]:
    """Validate split operations while simulating restored session state."""

    sessions = deepcopy(base_sessions)
    records_by_id = {operation.id: operation for operation in records}
    before_operation: dict[int, list[dict[str, Any]]] = {}
    valid: set[int] = set()
    invalid: dict[int, str] = {}
    seen_merge: set[int] = set()
    for operation in records:
        if operation.operation_type != "split_session":
            before_operation[operation.id] = deepcopy(sessions)
            sessions, _ = _apply_one(sessions, operation, projects)
            continue
        if not _payload_is_valid(operation):
            invalid[operation.id] = "invalid_payload"
            continue
        original = records_by_id.get(int(operation.undo_of_operation_id or 0))
        if (
            original is None
            or original.operation_type != "merge_sessions"
            or original.sequence >= operation.sequence
        ):
            invalid[operation.id] = "invalid_undo_target"
            continue
        if original.id in seen_merge:
            invalid[operation.id] = "duplicate_split"
            continue
        source, reason = _resolve_bound_input(
            sessions,
            operation,
            "source",
            operation.source_instance_key,
        )
        if source is None:
            invalid[operation.id] = "split_source_" + reason
            continue
        if str(source.get("projection_instance_key")) != merge_projection_key(
            original.id
        ):
            invalid[operation.id] = "split_requires_merge_output"
            continue
        pre_merge = before_operation.get(original.id)
        if pre_merge is None:
            invalid[operation.id] = "split_missing_merge_inputs"
            continue
        restored_source, _ = _resolve_bound_input(
            pre_merge,
            original,
            "source",
            original.source_instance_key,
        )
        restored_target, _ = _resolve_bound_input(
            pre_merge,
            original,
            "target",
            original.target_instance_key or "",
        )
        if restored_source is None or restored_target is None:
            invalid[operation.id] = "split_missing_merge_inputs"
            continue
        restored_members = {
            _member_key(member)
            for restored in (restored_source, restored_target)
            for member in restored.get("member_slices") or []
        }
        survivors = [
            item
            for item in sessions
            if not restored_members.intersection(
                {
                    _member_key(member)
                    for member in item.get("member_slices") or []
                }
            )
        ]
        sessions = _ordered_sessions(
            [
                *survivors,
                deepcopy(restored_source),
                deepcopy(restored_target),
            ]
        )
        seen_merge.add(original.id)
        valid.add(operation.id)
    return valid, invalid


def _undo_closure(
    records: tuple[OperationRecord, ...],
    valid_splits: set[int],
) -> tuple[set[int], dict[int, int]]:
    children: dict[int, set[int]] = {}
    for operation in records:
        for key in (operation.source_instance_key, operation.target_instance_key):
            parent = _producer_operation_id(key)
            if parent is not None:
                children.setdefault(parent, set()).add(operation.id)
    superseded: set[int] = set()
    undo_by_operation: dict[int, int] = {}
    for split in (item for item in records if item.id in valid_splits):
        pending = [int(split.undo_of_operation_id or 0)]
        while pending:
            operation_id = pending.pop()
            if operation_id in superseded:
                continue
            superseded.add(operation_id)
            undo_by_operation[operation_id] = split.id
            pending.extend(
                sorted(children.get(operation_id, ()), reverse=True)
            )
    return superseded, undo_by_operation


def _members_are_valid(operation: OperationRecord) -> bool:
    expected = expected_roles(operation.operation_type)
    if expected is None:
        return False
    roles = set(operation.members)
    if _binding(operation) is not ReplayBinding.MEMBERS or roles != expected:
        return False
    for role in expected:
        members = operation.members_for(role)
        identities = [_identity_tuple(member) for member in members]
        if not identities or len(identities) != len(set(identities)):
            return False
        if any(
            report_date != operation.report_date
            or activity_id <= 0
            or not slice_start_time
            for report_date, activity_id, slice_start_time in identities
        ):
            return False
    if operation.operation_type == "hide_activity":
        source = set(
            _identity_tuple(member)
            for member in operation.members_for("source")
        )
        affected = set(
            _identity_tuple(member)
            for member in operation.members_for("affected")
        )
        if not affected.issubset(source):
            return False
    return True


def _payload_is_valid(operation: OperationRecord) -> bool:
    payload = operation.payload
    if int(payload.get("payload_version") or 0) != OPERATION_PAYLOAD_VERSION:
        return False
    if _binding(operation) is None or not _members_are_valid(operation):
        return False
    allowed = allowed_payload_keys(operation.operation_type)
    if allowed is None:
        return False
    return set(payload) <= allowed


def _apply_edit(
    session: dict[str, Any],
    payload: Mapping[str, Any],
    projects: Mapping[int, ProjectState],
) -> bool:
    project = payload.get("project")
    if project is not None:
        if not isinstance(project, Mapping) or set(project) - {
            "mode",
            "project_id",
        }:
            return False
        mode = str(project.get("mode") or "")
        if mode == "set":
            state = projects.get(int(project.get("project_id") or 0))
            if state is None:
                return False
            _apply_project_state(session, state)
            session["has_project_override"] = True
        elif mode == "inherit":
            base_state = projects.get(int(session.get("_base_project_id") or 0))
            if base_state is None:
                return False
            _apply_project_state(session, base_state)
            session["has_project_override"] = False
        else:
            return False
    duration = payload.get("duration")
    if duration is not None:
        if not isinstance(duration, Mapping) or set(duration) - {
            "mode",
            "value",
        }:
            return False
        mode = str(duration.get("mode") or "")
        if (
            mode == "set"
            and isinstance(duration.get("value"), int)
            and int(duration["value"]) >= 0
        ):
            session["adjusted_duration_seconds"] = int(duration["value"])
            session["has_duration_override"] = True
        elif mode == "inherit":
            session["adjusted_duration_seconds"] = None
            session["has_duration_override"] = False
        else:
            return False
    note = payload.get("note")
    if note is not None:
        if not isinstance(note, Mapping) or set(note) - {"mode", "value"}:
            return False
        mode = str(note.get("mode") or "")
        if mode == "set" and isinstance(note.get("value"), str):
            session["session_note"] = str(note["value"])
        elif mode == "inherit":
            session["session_note"] = ""
        else:
            return False
    return any(key in payload for key in ("project", "duration", "note"))


def _apply_project_state(session: dict[str, Any], state: ProjectState) -> None:
    session.update(
        {
            "project_id": state.project_id,
            "project_name": state.project_name,
            "project_description": state.project_description,
            "project_is_deleted": state.is_deleted,
            "project_is_archived": state.is_archived,
            "project_is_enabled": state.is_enabled,
            "project_is_system": state.is_system,
            "project_is_special": state.is_special,
            "is_report_project": state.is_report_project,
            "is_report_classified": state.is_report_classified,
            "is_report_uncategorized": state.is_report_uncategorized,
            "is_official_project": state.is_official_project,
            "report_attribution_kind": state.report_attribution_kind,
            "project_key": state.project_key,
            "report_project_key": state.report_project_key,
        }
    )


def _merge_sessions(
    source: dict[str, Any],
    target: dict[str, Any],
    operation_id: int,
) -> dict[str, Any]:
    merged = deepcopy(target)
    contributions = []
    for row in build_projected_activity_contributions((source, target)):
        item = dict(row)
        item["_basis_duration_seconds"] = int(
            item.get("duration_seconds") or 0
        )
        contributions.append(item)
    merged.update(
        {
            "projection_instance_key": merge_projection_key(operation_id),
            "projection_kind": "merge",
            "operation_id": operation_id,
            "member_slices": _sorted_members(
                [
                    *(source.get("member_slices") or []),
                    *(target.get("member_slices") or []),
                ]
            ),
            "_projection_contributions": contributions,
            "has_duration_override": False,
            "adjusted_duration_seconds": None,
        }
    )
    return merged


def _resolve_bound_input(
    sessions: Sequence[dict[str, Any]],
    operation: OperationRecord,
    role: str,
    key: str,
) -> tuple[dict[str, Any] | None, str]:
    if _binding(operation) is not ReplayBinding.MEMBERS:
        return None, CONFLICT
    by_key = [
        item
        for item in sessions
        if str(item.get("projection_instance_key") or "") == key
    ]
    expected_members = operation.members_for(role)
    expected = tuple(
        sorted(_identity_tuple(member) for member in expected_members)
    )
    if not expected:
        return None, CONFLICT
    if len(by_key) > 1:
        return None, CONFLICT
    if len(by_key) == 1:
        keyed_members = tuple(
            sorted(
                _member_key(member)
                for member in by_key[0].get("member_slices") or []
            )
        )
        if keyed_members == expected:
            return by_key[0], ""
        return None, CONFLICT
    exact = [
        item
        for item in sessions
        if tuple(
            sorted(
                _member_key(member)
                for member in item.get("member_slices") or []
            )
        )
        == expected
    ]
    if len(exact) == 1:
        return exact[0], ""
    expected_set = set(expected)
    present = expected_set.intersection(
        {
            _member_key(member)
            for item in sessions
            for member in item.get("member_slices") or []
        }
    )
    return None, CONFLICT if present or exact else ORPHANED


def _prepare_session(
    value: Mapping[str, Any],
    projects: Mapping[int, ProjectState],
) -> dict[str, Any]:
    session = _mutable_value(value)
    session.setdefault("projection_kind", "base")
    session.setdefault("_projection_contributions", [])
    session.setdefault("_base_project_id", int(session.get("project_id") or 0))
    state = projects.get(int(session.get("project_id") or 0))
    if state is not None:
        _apply_project_state(session, state)
    return finalize_projected_session(session, state)


def _coerce_operation(
    value: OperationRecord | Mapping[str, Any],
) -> OperationRecord:
    if isinstance(value, OperationRecord):
        return value
    members = (
        value.get("members")
        if isinstance(value.get("members"), Mapping)
        else {}
    )
    payload = (
        dict(value.get("payload"))
        if isinstance(value.get("payload"), Mapping)
        else {}
    )
    return OperationRecord(
        id=int(value.get("id") or 0),
        report_date=str(value.get("report_date") or ""),
        sequence=int(value.get("sequence") or 0),
        operation_type=str(value.get("operation_type") or ""),
        source_instance_key=str(value.get("source_instance_key") or ""),
        source_expected_revision=str(
            value.get("source_expected_revision") or ""
        ),
        target_instance_key=(
            str(value.get("target_instance_key"))
            if value.get("target_instance_key") is not None
            else None
        ),
        target_expected_revision=(
            str(value.get("target_expected_revision"))
            if value.get("target_expected_revision") is not None
            else None
        ),
        direction=(
            str(value.get("direction"))
            if value.get("direction") is not None
            else None
        ),
        undo_of_operation_id=(
            int(value["undo_of_operation_id"])
            if value.get("undo_of_operation_id") is not None
            else None
        ),
        payload=payload,
        members=members,
        created_at=str(value.get("created_at") or ""),
    )


def _project_map(
    values: Sequence[ProjectState] | Mapping[int, ProjectState],
) -> dict[int, ProjectState]:
    if isinstance(values, Mapping):
        return {int(key): value for key, value in values.items()}
    return {state.project_id: state for state in values}


def _ordered_sessions(
    sessions: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(sessions, key=_session_sort_key)


def _session_sort_key(
    session: Mapping[str, Any],
) -> tuple[str, str, str]:
    members = _sorted_members(session.get("member_slices") or [])
    first = (
        str(members[0].get("slice_start_time") or "")
        if members
        else str(session.get("start_time") or "")
    )
    return (
        str(session.get("report_date") or ""),
        first,
        str(session.get("projection_instance_key") or ""),
    )


def _replace_session(
    sessions: list[dict[str, Any]],
    old: dict[str, Any],
    new: dict[str, Any],
) -> list[dict[str, Any]]:
    return _ordered_sessions([new if item is old else item for item in sessions])


def _remove_sessions(
    sessions: list[dict[str, Any]],
    *removed: dict[str, Any],
) -> list[dict[str, Any]]:
    removed_ids = {id(item) for item in removed}
    return _ordered_sessions(
        item for item in sessions if id(item) not in removed_ids
    )


def _refresh_capabilities(sessions: list[dict[str, Any]]) -> None:
    ordered = _ordered_sessions(sessions)
    for index, session in enumerate(ordered):
        normal = (
            str(session.get("row_kind") or "project_session")
            == "project_session"
            and not bool(session.get("is_in_progress"))
        )
        kind = str(session.get("projection_kind") or "base")
        session["can_hide"] = normal
        session["can_copy"] = normal
        session["can_hide_activity"] = normal and bool(
            session.get("member_slices")
        )
        session["can_split"] = kind == "merge"
        session["can_merge_previous"] = (
            normal
            and kind != "copy"
            and index > 0
            and str(ordered[index - 1].get("projection_kind") or "base")
            != "copy"
        )
        session["can_merge_next"] = (
            normal
            and kind != "copy"
            and index + 1 < len(ordered)
            and str(ordered[index + 1].get("projection_kind") or "base")
            != "copy"
        )
        session["projection_revision"] = projection_revision(session)


def _diagnostic(
    operation: OperationRecord,
    state: str,
    reason: str,
    *,
    undo_operation_id: int | None = None,
) -> OperationDiagnostic:
    return OperationDiagnostic(
        operation_id=operation.id,
        sequence=operation.sequence,
        operation_type=operation.operation_type,
        state=state,
        reason=reason,
        source_instance_key=operation.source_instance_key,
        target_instance_key=operation.target_instance_key,
        undo_operation_id=undo_operation_id,
    )


def _member_key(member: Mapping[str, Any]) -> tuple[str, int, str]:
    return member_identity_key(dict(member))


def _identity_tuple(member: ReportMemberIdentity) -> tuple[str, int, str]:
    return (
        member.report_date,
        member.activity_id,
        member.slice_start_time,
    )


def _sorted_members(
    members: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    unique = {
        _member_key(member): _mutable_value(member)
        for member in members
    }
    return [unique[key] for key in sorted(unique)]


def _producer_operation_id(key: str | None) -> int | None:
    if not key or ":" not in key:
        return None
    prefix, value = key.split(":", 1)
    if prefix not in {"copy", "merge"}:
        return None
    try:
        result = int(value)
    except ValueError:
        return None
    return result if result > 0 else None


__all__ = [
    "APPLIED",
    "CONFLICT",
    "OPERATION_PAYLOAD_VERSION",
    "ORPHANED",
    "ReplayResult",
    "SUPERSEDED_BY_UNDO",
    "allocate_duration",
    "build_projected_activity_contributions",
    "finalize_projected_session",
    "replay_operations",
]
