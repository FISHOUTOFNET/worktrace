"""Static current-schema table membership for backup and maintenance owners.

The manifest is the single source of truth for current-schema content tables
across backup, restore, clear, privacy wipe, replacement validation, test
reset/drop and schema coverage governance. Every table is classified by a
``TableCategory`` enum so the role of each row is explicit; the legacy
``derived``/``internal`` flags are derived from that category rather than
being independent booleans.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TableCategory(StrEnum):
    """Functional role of a current-schema content table."""

    DURABLE_CONFIGURATION = "durable_configuration"
    LIVE_ACTIVITY_DATA = "live_activity_data"
    DERIVED_DATA = "derived_data"
    PROJECTION_OPERATIONS = "projection_operations"
    MUTATION_RECEIPTS = "mutation_receipts"
    MAINTENANCE_RECOVERY_STATE = "maintenance_recovery_state"
    GENERATION_STATE = "generation_state"
    WORKER_PROGRESS = "worker_progress"


_DERIVED_CATEGORIES: frozenset[TableCategory] = frozenset(
    {
        TableCategory.DERIVED_DATA,
        TableCategory.WORKER_PROGRESS,
        TableCategory.GENERATION_STATE,
        TableCategory.MAINTENANCE_RECOVERY_STATE,
    }
)
_INTERNAL_CATEGORIES: frozenset[TableCategory] = frozenset(
    {
        TableCategory.WORKER_PROGRESS,
        TableCategory.GENERATION_STATE,
        TableCategory.MAINTENANCE_RECOVERY_STATE,
    }
)


@dataclass(frozen=True)
class DatabaseTableContent:
    name: str
    category: TableCategory
    delete_rank: int | None
    backup_rank: int | None = None
    rebuilt_after_clear: bool = False

    @property
    def derived(self) -> bool:
        return self.category in _DERIVED_CATEGORIES

    @property
    def internal(self) -> bool:
        return self.category in _INTERNAL_CATEGORIES


DATABASE_CONTENT: tuple[DatabaseTableContent, ...] = (
    DatabaseTableContent(
        "project",
        TableCategory.DURABLE_CONFIGURATION,
        190,
        10,
        rebuilt_after_clear=True,
    ),
    DatabaseTableContent(
        "settings",
        TableCategory.DURABLE_CONFIGURATION,
        180,
        20,
        rebuilt_after_clear=True,
    ),
    DatabaseTableContent(
        "session_boundary",
        TableCategory.LIVE_ACTIVITY_DATA,
        170,
        30,
    ),
    DatabaseTableContent(
        "activity_log",
        TableCategory.LIVE_ACTIVITY_DATA,
        160,
        40,
    ),
    DatabaseTableContent(
        "folder_project_rule",
        TableCategory.DURABLE_CONFIGURATION,
        150,
        50,
    ),
    DatabaseTableContent(
        "project_rule",
        TableCategory.DURABLE_CONFIGURATION,
        140,
        60,
    ),
    DatabaseTableContent(
        "folder_rule_index_state",
        TableCategory.DERIVED_DATA,
        100,
        70,
    ),
    DatabaseTableContent(
        "activity_project_assignment",
        TableCategory.PROJECTION_OPERATIONS,
        70,
        80,
    ),
    DatabaseTableContent(
        "activity_clipboard_event",
        TableCategory.MUTATION_RECEIPTS,
        60,
        90,
    ),
    DatabaseTableContent(
        "report_session_operation",
        TableCategory.PROJECTION_OPERATIONS,
        40,
        100,
    ),
    DatabaseTableContent(
        "report_session_operation_member",
        TableCategory.PROJECTION_OPERATIONS,
        20,
        110,
    ),
    DatabaseTableContent(
        "report_mutation_request",
        TableCategory.MUTATION_RECEIPTS,
        30,
        120,
    ),
    DatabaseTableContent(
        "activity_resource",
        TableCategory.LIVE_ACTIVITY_DATA,
        10,
        130,
    ),
    DatabaseTableContent(
        "folder_rule_file_index",
        TableCategory.DERIVED_DATA,
        90,
    ),
    DatabaseTableContent(
        "history_mutation_job",
        TableCategory.WORKER_PROGRESS,
        120,
    ),
    DatabaseTableContent(
        "history_mutation_job_rule",
        TableCategory.WORKER_PROGRESS,
        110,
    ),
    DatabaseTableContent(
        "data_generation_state",
        TableCategory.GENERATION_STATE,
        None,
    ),
    DatabaseTableContent(
        "activity_inference_job",
        TableCategory.WORKER_PROGRESS,
        80,
    ),
    DatabaseTableContent(
        "activity_resource_repair_job",
        TableCategory.WORKER_PROGRESS,
        130,
    ),
    DatabaseTableContent(
        "startup_recovery_job",
        TableCategory.WORKER_PROGRESS,
        50,
    ),
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
    "INTERNAL_TABLES",
    "REBUILT_AFTER_CLEAR_TABLES",
    "TABLE_NAMES",
    "DatabaseTableContent",
    "TableCategory",
]
