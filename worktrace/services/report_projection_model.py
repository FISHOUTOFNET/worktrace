from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT


class FrozenDict(dict):
    """A JSON-compatible immutable mapping used at domain boundaries."""

    @staticmethod
    def _blocked(*_args, **_kwargs):
        raise TypeError("frozen mapping")

    __setitem__ = _blocked
    __delitem__ = _blocked
    clear = _blocked
    pop = _blocked
    popitem = _blocked
    setdefault = _blocked
    update = _blocked
    __ior__ = _blocked

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        memo[id(self)] = self
        return self

    def copy(self) -> dict:
        """Return an explicit mutable adapter copy."""
        return dict(self)


def freeze_value(value: Any) -> Any:
    if isinstance(value, FrozenDict):
        return value
    if isinstance(value, Mapping):
        return FrozenDict({str(key): freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(freeze_value(item) for item in value)
    return value


def thaw_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, frozenset)):
        return [thaw_value(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _freeze_record_tuple(values: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]]) -> tuple[Mapping[str, Any], ...]:
    return tuple(freeze_value(dict(value)) for value in values)


@dataclass(frozen=True, order=True)
class ReportMemberIdentity:
    report_date: str
    activity_id: int
    slice_start_time: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_date": self.report_date,
            "activity_id": self.activity_id,
            "slice_start_time": self.slice_start_time,
        }


@dataclass(frozen=True)
class ProjectState:
    project_id: int
    project_name: str
    project_description: str
    is_deleted: bool
    is_archived: bool
    is_enabled: bool
    is_system: bool
    is_special: bool
    is_report_project: bool
    is_report_classified: bool
    is_report_uncategorized: bool
    is_official_project: bool
    report_attribution_kind: str
    project_key: str
    report_project_key: str

    @property
    def reportable(self) -> bool:
        return self.is_report_project and not self.is_deleted

    @property
    def selectable(self) -> bool:
        return not self.is_deleted and not self.is_archived and self.is_enabled

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "project_description": self.project_description,
            "is_deleted": self.is_deleted,
            "is_archived": self.is_archived,
            "is_enabled": self.is_enabled,
            "is_system": self.is_system,
            "is_special": self.is_special,
            "is_report_project": self.is_report_project,
            "is_report_classified": self.is_report_classified,
            "is_report_uncategorized": self.is_report_uncategorized,
            "is_official_project": self.is_official_project,
            "report_attribution_kind": self.report_attribution_kind,
            "project_key": self.project_key,
            "report_project_key": self.report_project_key,
        }


@dataclass(frozen=True)
class ReportContribution:
    member_identity: ReportMemberIdentity
    duration_seconds: int
    status: str
    project: ProjectState | None
    activity_identity_key: str = ""
    is_in_progress: bool = False
    privacy_redacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_identity": self.member_identity.to_dict(),
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "project": self.project.to_dict() if self.project else None,
            "activity_identity_key": self.activity_identity_key,
            "is_in_progress": self.is_in_progress,
            "privacy_redacted": self.privacy_redacted,
        }


@dataclass(frozen=True)
class ReportSessionEntry:
    report_date: str
    projection_instance_key: str
    projection_revision: str
    member_identities: tuple[ReportMemberIdentity, ...]
    contributions: tuple[ReportContribution, ...]
    project: ProjectState | None
    duration_seconds: int
    start_time: str = ""
    end_time: str | None = None
    note: str = ""
    is_in_progress: bool = False
    projection_kind: str = "base"


@dataclass(frozen=True)
class StandaloneStatusEntry:
    report_date: str
    projection_instance_key: str
    projection_revision: str
    member_identity: ReportMemberIdentity
    status: str
    duration_seconds: int
    start_time: str = ""
    end_time: str | None = None
    is_in_progress: bool = False
    privacy_redacted: bool = True


@dataclass(frozen=True)
class OperationRecord:
    id: int
    report_date: str
    sequence: int
    operation_type: str
    source_instance_key: str
    source_expected_revision: str
    target_instance_key: str | None = None
    target_expected_revision: str | None = None
    direction: str | None = None
    undo_of_operation_id: int | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    members: Mapping[str, tuple[ReportMemberIdentity, ...]] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", freeze_value(self.payload))
        normalized = {
            str(role): tuple(
                member
                if isinstance(member, ReportMemberIdentity)
                else ReportMemberIdentity(
                    str(member.get("report_date") or "")[:10],
                    int(member.get("activity_id") or member.get("id") or 0),
                    str(member.get("slice_start_time") or member.get("start_time") or ""),
                )
                for member in identities
            )
            for role, identities in self.members.items()
        }
        object.__setattr__(self, "members", FrozenDict(normalized))

    def members_for(self, role: str) -> tuple[ReportMemberIdentity, ...]:
        return self.members.get(role, ())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "report_date": self.report_date,
            "sequence": self.sequence,
            "operation_type": self.operation_type,
            "source_instance_key": self.source_instance_key,
            "source_expected_revision": self.source_expected_revision,
            "target_instance_key": self.target_instance_key,
            "target_expected_revision": self.target_expected_revision,
            "direction": self.direction,
            "undo_of_operation_id": self.undo_of_operation_id,
            "payload": thaw_value(self.payload),
            "members": {
                role: [member.to_dict() for member in identities]
                for role, identities in self.members.items()
            },
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class OperationDiagnostic:
    operation_id: int
    sequence: int
    operation_type: str
    state: str
    reason: str = ""
    source_instance_key: str = ""
    target_instance_key: str | None = None
    undo_operation_id: int | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", freeze_value(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "sequence": self.sequence,
            "operation_type": self.operation_type,
            "state": self.state,
            "reason": self.reason,
            "source_instance_key": self.source_instance_key,
            "target_instance_key": self.target_instance_key,
            "undo_operation_id": self.undo_operation_id,
            "details": thaw_value(self.details),
        }


ReportEntry = ReportSessionEntry | StandaloneStatusEntry


@dataclass(frozen=True)
class ReportProjectionSnapshot:
    """Recursively immutable canonical snapshot with mapping-compatible records."""

    start_date: str
    end_date: str
    base_sessions: tuple[Mapping[str, Any], ...]
    final_entries: tuple[Mapping[str, Any], ...]
    final_sessions: tuple[Mapping[str, Any], ...]
    standalone_status_entries: tuple[Mapping[str, Any], ...]
    final_contributions: tuple[Mapping[str, Any], ...]
    operation_diagnostics: tuple[OperationDiagnostic, ...]
    snapshot_revision: str

    def __post_init__(self) -> None:
        for field_name in (
            "base_sessions",
            "final_entries",
            "final_sessions",
            "standalone_status_entries",
            "final_contributions",
        ):
            object.__setattr__(self, field_name, _freeze_record_tuple(getattr(self, field_name)))
        object.__setattr__(self, "operation_diagnostics", tuple(self.operation_diagnostics))


@dataclass(frozen=True)
class MutationResult:
    request_id: str
    outcome_type: str
    operation_id: int | None
    report_date: str
    selection_hint: Mapping[str, Any] | None
    snapshot_revision: str | None = None
    error: str | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.selection_hint is not None:
            object.__setattr__(self, "selection_hint", freeze_value(self.selection_hint))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "outcome_type": self.outcome_type,
            "operation_id": self.operation_id,
            "report_date": self.report_date,
            "selection_hint": thaw_value(self.selection_hint),
            "snapshot_revision": self.snapshot_revision,
            "error": self.error,
            "message": self.message,
        }


class ReportDomainError(Exception):
    code = "operation_failed"
    default_message = "操作失败"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.code)


def _error_type(name: str, code: str, message: str) -> type[ReportDomainError]:
    return type(name, (ReportDomainError,), {"code": code, "default_message": message})


InvalidInputError = _error_type("InvalidInputError", "invalid_input", "输入无效")
StaleSelectionError = _error_type("StaleSelectionError", "stale_selection", "所选记录已变化，请刷新后重试")
RevisionConflictError = _error_type("RevisionConflictError", "revision_conflict", "记录已变化，请刷新后重试")
TargetRevisionConflictError = _error_type("TargetRevisionConflictError", "target_revision_conflict", "目标记录已变化，请刷新后重试")
SessionNotAdjacentError = _error_type("SessionNotAdjacentError", "session_not_adjacent", "只能合并相邻记录")
RequestIdConflictError = _error_type("RequestIdConflictError", "request_id_conflict", "请求标识已用于其他操作")
ProjectNotSelectableError = _error_type("ProjectNotSelectableError", "project_not_selectable", "该项目当前不可选择")
OperationNotAllowedError = _error_type("OperationNotAllowedError", "operation_not_allowed", "当前记录不允许此操作")
OperationNoEffectError = _error_type("OperationNoEffectError", "operation_no_effect", "操作未产生变化")
DatabaseBusyError = _error_type("DatabaseBusyError", "database_busy", "数据库正忙，请稍后重试")


def project_state_from_row(
    row: Mapping[str, Any], *, prefix: str = "", uncategorized_id: int | None = None
) -> ProjectState:
    def value(name: str, default: Any = None) -> Any:
        return row.get(f"{prefix}{name}", row.get(name, default))

    project_id = int(value("project_id", value("id", uncategorized_id or 0)) or 0)
    project_name = str(value("project_name", value("name", "")) or "")
    description = str(value("project_description", value("description", "")) or "")
    deleted = bool(value("is_deleted", value("project_is_deleted", False)))
    archived = bool(value("is_archived", value("project_is_archived", False)))
    enabled = bool(value("is_enabled", value("enabled", True)))
    uncategorized = bool(value("is_report_uncategorized", False))
    if not project_name and uncategorized_id is not None and project_id == int(uncategorized_id):
        project_name, uncategorized = UNCATEGORIZED_PROJECT, True
    report_project = bool(value("is_report_project", not uncategorized and project_id > 0))
    project_key = str(value("project_key", "") or (f"project:{project_id}" if project_id else "project:none"))
    report_key = str(value("report_project_key", "") or "")
    if not report_key:
        report_key = f"uncategorized:{project_id}" if uncategorized else f"project:{project_id}"
    return ProjectState(
        project_id=project_id,
        project_name=project_name,
        project_description=description,
        is_deleted=deleted,
        is_archived=archived,
        is_enabled=enabled,
        is_system=str(value("created_by", "") or "") == "system",
        is_special=project_name in {UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT},
        is_report_project=report_project,
        is_report_classified=bool(value("is_report_classified", report_project)),
        is_report_uncategorized=uncategorized,
        is_official_project=bool(value("is_official_project", report_project)),
        report_attribution_kind=str(value("report_attribution_kind", "none") or "none"),
        project_key=project_key,
        report_project_key=report_key,
    )


__all__ = [
    "DatabaseBusyError", "FrozenDict", "InvalidInputError", "MutationResult", "OperationDiagnostic",
    "OperationNoEffectError", "OperationNotAllowedError", "OperationRecord", "ProjectNotSelectableError",
    "ProjectState", "ReportContribution", "ReportDomainError", "ReportMemberIdentity",
    "ReportProjectionSnapshot", "ReportSessionEntry", "RequestIdConflictError", "RevisionConflictError",
    "SessionNotAdjacentError", "StandaloneStatusEntry", "StaleSelectionError", "TargetRevisionConflictError",
    "freeze_value", "project_state_from_row", "thaw_value",
]
