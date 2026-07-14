from __future__ import annotations

from ..db import get_connection, seed_defaults

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


def clear_all_live_data() -> None:
    """Delete all user/runtime rows atomically while retaining the schema."""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            for table in _DELETE_ORDER:
                conn.execute(f"DELETE FROM {table}")
            seed_defaults(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise


__all__ = ["clear_all_live_data"]
