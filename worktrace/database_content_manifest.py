"""Static current-schema table membership for backup and maintenance owners."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatabaseTableContent:
    name: str
    delete_rank: int | None
    backup_rank: int | None = None
    derived: bool = False
    internal: bool = False
    rebuilt_after_clear: bool = False


DATABASE_CONTENT: tuple[DatabaseTableContent, ...] = (
    DatabaseTableContent("project", 190, 10, rebuilt_after_clear=True),
    DatabaseTableContent("settings", 180, 20, rebuilt_after_clear=True),
    DatabaseTableContent("session_boundary", 170, 30),
    DatabaseTableContent("activity_log", 160, 40),
    DatabaseTableContent("folder_project_rule", 150, 50),
    DatabaseTableContent("project_rule", 140, 60),
    DatabaseTableContent("folder_rule_index_state", 100, 70, derived=True),
    DatabaseTableContent("activity_project_assignment", 70, 80),
    DatabaseTableContent("activity_clipboard_event", 60, 90),
    DatabaseTableContent("report_session_operation", 40, 100),
    DatabaseTableContent("report_session_operation_member", 20, 110),
    DatabaseTableContent("report_mutation_request", 30, 120),
    DatabaseTableContent("activity_resource", 10, 130),
    DatabaseTableContent("folder_rule_file_index", 90, derived=True),
    DatabaseTableContent("history_mutation_job", 120, derived=True, internal=True),
    DatabaseTableContent("history_mutation_job_rule", 110, derived=True, internal=True),
    DatabaseTableContent("data_generation_state", None, derived=True, internal=True),
    DatabaseTableContent("activity_inference_job", 80, derived=True, internal=True),
    DatabaseTableContent("activity_resource_repair_job", 130, derived=True, internal=True),
    DatabaseTableContent("startup_recovery_job", 50, derived=True, internal=True),
)

TABLE_NAMES = tuple(item.name for item in DATABASE_CONTENT)
DELETE_ORDER = tuple(
    item.name
    for item in sorted(
        (item for item in DATABASE_CONTENT if item.delete_rank is not None),
        key=lambda item: int(item.delete_rank or 0),
    )
)
BACKUP_TABLES = tuple(
    item.name
    for item in sorted(
        (item for item in DATABASE_CONTENT if item.backup_rank is not None),
        key=lambda item: int(item.backup_rank or 0),
    )
)
DERIVED_TABLES = frozenset(item.name for item in DATABASE_CONTENT if item.derived)
INTERNAL_TABLES = frozenset(item.name for item in DATABASE_CONTENT if item.internal)
REBUILT_AFTER_CLEAR_TABLES = frozenset(
    item.name for item in DATABASE_CONTENT if item.rebuilt_after_clear
)


__all__ = [
    "BACKUP_TABLES",
    "DATABASE_CONTENT",
    "DELETE_ORDER",
    "DERIVED_TABLES",
    "DatabaseTableContent",
    "INTERNAL_TABLES",
    "REBUILT_AFTER_CLEAR_TABLES",
    "TABLE_NAMES",
]
