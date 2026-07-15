from __future__ import annotations

from ..db import get_connection, now_str, seed_defaults

_DELETE_ORDER: tuple[str, ...] = (
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
    """Delete all user/runtime rows atomically while retaining the schema."""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table in _DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")
            seed_defaults(conn)
            _apply_post_clear_settings(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


__all__ = ["clear_all_live_data"]
