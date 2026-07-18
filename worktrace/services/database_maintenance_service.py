from __future__ import annotations

from ..db import now_str, seed_defaults
from ..domain_unit_of_work import DomainUnitOfWork
from .database_replacement_generation_service import publish_database_replacement

_DELETE_ORDER: tuple[str, ...] = (
    "activity_inference_job",
    "activity_resource",
    "report_session_operation_member",
    "report_mutation_request",
    "report_session_operation",
    "activity_clipboard_event",
    "activity_project_assignment",
    "folder_rule_file_index",
    "folder_rule_index_state",
    "project_rule",
    "folder_project_rule",
    "activity_log",
    "session_boundary",
    "settings",
    "project",
)

_POST_CLEAR_SETTINGS: dict[str, str] = {
    "user_paused": "true",
    "collector_status": "paused",
    "clipboard_capture_enabled": "false",
}


def _apply_post_clear_settings(conn) -> None:
    """Persist the safe stopped-write state in the same clear transaction."""

    updated_at = now_str()
    for key, value in _POST_CLEAR_SETTINGS.items():
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, updated_at),
        )


def clear_all_live_data() -> None:
    """Delete live rows atomically and publish every affected generation once."""

    with DomainUnitOfWork() as uow:
        conn = uow.connection
        for table in _DELETE_ORDER:
            conn.execute(f"DELETE FROM {table}")
        conn.execute("DELETE FROM activity_resource_repair_job")
        seed_defaults(conn)
        _apply_post_clear_settings(conn)
        publish_database_replacement(conn)


__all__ = ["clear_all_live_data"]
