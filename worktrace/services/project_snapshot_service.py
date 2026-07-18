from __future__ import annotations

from dataclasses import dataclass

from ..constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT


@dataclass(frozen=True)
class ActivityProjectSnapshot:
    project_id: int | None
    project_name: str
    project_description: str
    project_enabled: bool | None
    project_is_archived: bool
    project_is_deleted: bool
    assignment_source: str
    is_manual: bool
    confidence: int
    suggested_project_name: str
    source_rule_type: str
    source_rule_id: int | None
    display_project_id: int | None
    display_project_name: str
    display_project_description: str
    is_uncategorized: bool
    is_suggested_project: bool


def snapshot_from_activity_row(row: dict | None) -> ActivityProjectSnapshot:
    item = dict(row or {})
    project_id = _int_or_none(item.get("project_id"))
    project_name = str(item.get("project_name") or "")
    project_description = str(item.get("project_description") or "")
    project_enabled = _bool_or_none(item.get("project_enabled"))
    project_is_archived = bool(int(item.get("project_is_archived") or 0))
    project_is_deleted = bool(int(item.get("project_is_deleted") or 0))
    assignment_source = str(item.get("assignment_source") or "")
    is_manual = bool(int(item.get("is_manual") or 0))
    confidence = int(item.get("assignment_confidence") or 0)
    suggested_project_name = str(item.get("suggested_project_name") or "").strip()
    source_rule_type = str(item.get("source_rule_type") or "")
    source_rule_id = _int_or_none(item.get("source_rule_id"))

    display_project_id = project_id
    display_project_name = project_name
    display_project_description = project_description
    is_suggested = False
    is_uncategorized = project_name == UNCATEGORIZED_PROJECT
    if assignment_source == "suggested_project_name" and suggested_project_name:
        display_project_id = None
        display_project_name = suggested_project_name
        display_project_description = ""
        is_suggested = True
        is_uncategorized = False
    elif project_id is None and not project_name:
        display_project_id = None
        display_project_name = UNCATEGORIZED_PROJECT
        display_project_description = ""
        is_uncategorized = True
    elif not _is_project_displayable(
        project_id,
        project_name,
        project_enabled,
        project_is_archived,
        project_is_deleted,
    ):
        display_project_id = None
        display_project_name = UNCATEGORIZED_PROJECT
        display_project_description = ""
        is_uncategorized = True

    return ActivityProjectSnapshot(
        project_id=project_id,
        project_name=project_name,
        project_description=project_description,
        project_enabled=project_enabled,
        project_is_archived=project_is_archived,
        project_is_deleted=project_is_deleted,
        assignment_source=assignment_source,
        is_manual=is_manual,
        confidence=confidence,
        suggested_project_name=suggested_project_name,
        source_rule_type=source_rule_type,
        source_rule_id=source_rule_id,
        display_project_id=display_project_id,
        display_project_name=display_project_name,
        display_project_description=display_project_description,
        is_uncategorized=is_uncategorized,
        is_suggested_project=is_suggested,
    )


def serialize_project_snapshot(snapshot: ActivityProjectSnapshot) -> dict:
    return {
        "id": snapshot.display_project_id,
        "name": snapshot.display_project_name,
        "description": snapshot.display_project_description,
        "source": snapshot.assignment_source,
        "is_manual": snapshot.is_manual,
        "confidence": snapshot.confidence,
        "suggested_project_name": snapshot.suggested_project_name,
        "source_rule_type": snapshot.source_rule_type,
        "source_rule_id": snapshot.source_rule_id,
        "is_uncategorized": snapshot.is_uncategorized,
        "is_suggested_project": snapshot.is_suggested_project,
    }


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_project_displayable(
    project_id: int | None,
    project_name: str,
    project_enabled: bool | None,
    project_is_archived: bool,
    project_is_deleted: bool,
) -> bool:
    return bool(
        project_id is not None
        and project_name
        and project_name != EXCLUDED_PROJECT
        and project_enabled is not False
        and not project_is_archived
        and not project_is_deleted
    )


def _bool_or_none(value) -> bool | None:
    if value is None or value == "":
        return None
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return None


__all__ = [
    "ActivityProjectSnapshot",
    "serialize_project_snapshot",
    "snapshot_from_activity_row",
]
