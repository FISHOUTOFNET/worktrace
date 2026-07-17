from __future__ import annotations

from ..db import get_connection, now_str


def recover_interrupted_indexes() -> int:
    """Discard incomplete staging generations and preserve active indexes."""

    timestamp = now_str()
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        states = conn.execute(
            """
            SELECT folder_rule_id, active_generation, building_generation
            FROM folder_rule_index_state
            WHERE building_generation IS NOT NULL
               OR build_status = 'indexing'
               OR status = 'indexing'
            """
        ).fetchall()
        for state in states:
            building = int(state["building_generation"] or 0)
            if building > 0:
                conn.execute(
                    """
                    DELETE FROM folder_rule_file_index
                    WHERE folder_rule_id = ? AND generation = ?
                    """,
                    (int(state["folder_rule_id"]), building),
                )
            conn.execute(
                """
                UPDATE folder_rule_index_state
                SET status = CASE
                        WHEN active_generation IS NULL THEN 'pending'
                        ELSE 'ready' END,
                    building_generation = NULL,
                    build_status = 'pending',
                    refresh_requested = 1,
                    last_error = NULL,
                    error_message = NULL,
                    updated_at = ?
                WHERE folder_rule_id = ?
                """,
                (timestamp, int(state["folder_rule_id"])),
            )
        conn.commit()
        return len(states)


__all__ = ["recover_interrupted_indexes"]
