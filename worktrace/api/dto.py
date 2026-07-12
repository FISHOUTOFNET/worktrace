"""Data Transfer Object type aliases for the API boundary.

These ``TypedDict`` definitions document the shape of the plain ``dict`` values
returned by the service layer and re-exposed through the API facades. They are
kept ``total=False`` so the facades can pass service dicts through without
construction overhead or behaviour change.
"""

from __future__ import annotations

from typing import Any, TypedDict


class Session(TypedDict, total=False):
    projection_instance_key: str
    projection_revision: str
    project_id: int
    project_name: str
    project_description: str
    start_time: str | None
    end_time: str | None
    report_date: str
    duration_seconds: int
    activity_ids: list[int]
    first_activity_id: int | None
    session_note: str
    event_count: int
    status: str
    status_summary: str
    is_uncategorized: bool
    is_suggested_project: bool


class ActivityDetail(TypedDict, total=False):
    id: int
    start_time: str | None
    end_time: str | None
    duration_seconds: int
    status: str
    app_name: str
    process_name: str
    window_title: str
    activity_display_name: str
    project_id: int
    project_name: str
    project_description: str
    official_project_name: str
    note: str
    resource_kind: str
    resource_subtype: str
    resource_display_name: str
    resource_is_anchor: bool
    resource_path_hint: str


class Project(TypedDict, total=False):
    id: int
    name: str
    description: str
    enabled: int
    created_by: str


class ProjectBinding(TypedDict, total=False):
    id: int
    name: str
    description: str
    enabled: int
    created_by: str
    folder_rules: list[dict]
    keyword_rules: list[dict]


class FolderRule(TypedDict, total=False):
    id: int
    folder_path: str
    project_id: int
    enabled: int
    recursive: int


class KeywordRule(TypedDict, total=False):
    id: int
    keyword: str
    project_id: int
    enabled: int


class Summary(TypedDict, total=False):
    total_duration: int
    effective_duration: int
    classified_duration: int
    uncategorized_duration: int
    idle_duration: int
    paused_duration: int
    excluded_duration: int


class ProjectStat(TypedDict, total=False):
    project: str
    project_description: str
    total_duration: int
    record_count: int


class ActivitySnapshot(TypedDict, total=False):
    activity_display_name: str
    app_name: str
    process_name: str
    inferred_project_name: str
    status: str
    start_time: str
    elapsed_seconds: int
    extra_seconds: int
    is_persisted: bool
    persisted_activity_id: int
    resource_display_name: str


class SessionProjectPreview(TypedDict, total=False):
    folder_rule_conflicts: list[dict]
    unassigned_anchor_files: list[dict]


class FolderRuleConflictPreview(TypedDict, total=False):
    child_folder_rule_conflicts: int
    other_project_activity_count: int
    manual_activity_count: int


class BackfillResult(TypedDict, total=False):
    updated_activity_count: int


class AnchorPreviewItem(TypedDict, total=False):
    activity_id: int
    display_name: str
    full_path: str
    parent_dir: str
    current_project_name: str


# Re-export Any for convenience in facade signatures.
__all__ = [
    "Any",
    "ActivityDetail",
    "ActivitySnapshot",
    "AnchorPreviewItem",
    "BackfillResult",
    "FolderRule",
    "FolderRuleConflictPreview",
    "KeywordRule",
    "Project",
    "ProjectBinding",
    "ProjectStat",
    "Session",
    "SessionProjectPreview",
    "Summary",
]
