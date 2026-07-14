from __future__ import annotations

from ..db import get_connection, now_str


def recover_interrupted_indexes() -> int:
    """Return crash-interrupted ``indexing`` states to the pending queue."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = 'pending',
                refresh_requested = 1,
                error_message = NULL,
                valid_from = NULL,
                file_count = 0,
                updated_at = ?
            WHERE status = 'indexing'
            """,
            (now_str(),),
        )
        return int(cursor.rowcount or 0)


__all__ = ["recover_interrupted_indexes"]
