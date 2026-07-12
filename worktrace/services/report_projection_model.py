from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_state_from_row(
    row: dict[str, Any],
    *,
    prefix: str = "",
    uncategorized_id: int | None = None,
) -> ProjectState:
    def field(name: str, default: Any = None) -> Any:
        return row.get(f"{prefix}{name}", row.get(name, default))

    project_id = int(field("project_id", field("id", uncategorized_id or 0)) or 0)
    project_name = str(field("project_name", field("name", "")) or "")
    description = str(field("project_description", field("description", "")) or "")
    is_deleted = bool(field("is_deleted", field("project_is_deleted", False)))
    is_archived = bool(field("is_archived", field("project_is_archived", False)))
    is_enabled = bool(field("is_enabled", field("enabled", True)))
    created_by = str(field("created_by", "") or "")
    is_special = project_name in {UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT}
    is_report_uncategorized = bool(field("is_report_uncategorized", False))
    if not project_name and uncategorized_id is not None and project_id == int(uncategorized_id):
        project_name = UNCATEGORIZED_PROJECT
        is_report_uncategorized = True
    is_report_project = bool(field("is_report_project", not is_report_uncategorized and project_id > 0))
    is_report_classified = bool(field("is_report_classified", is_report_project))
    is_official = bool(field("is_official_project", is_report_project))
    project_key = str(field("project_key", "") or "")
    if not project_key:
        project_key = f"project:{project_id}" if project_id else "project:none"
    report_key = str(field("report_project_key", "") or "")
    if not report_key:
        if is_report_uncategorized:
            report_key = f"uncategorized:{project_id or int(uncategorized_id or 0)}"
        elif is_deleted:
            report_key = f"deleted_project:{project_id}"
        else:
            report_key = f"project:{project_id}"
    return ProjectState(
        project_id=project_id,
        project_name=project_name,
        project_description=description,
        is_deleted=is_deleted,
        is_archived=is_archived,
        is_enabled=is_enabled,
        is_system=created_by == "system",
        is_special=is_special,
        is_report_project=is_report_project,
        is_report_classified=is_report_classified,
        is_report_uncategorized=is_report_uncategorized,
        is_official_project=is_official,
        report_attribution_kind=str(field("report_attribution_kind", "none") or "none"),
        project_key=project_key,
        report_project_key=report_key,
    )


@dataclass(frozen=True)
class MutationResult:
    request_id: str
    outcome_type: str
    operation_id: int | None
    report_date: str
    selection_hint: dict[str, Any] | None
    snapshot_revision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = ["MutationResult", "ProjectState", "project_state_from_row"]
