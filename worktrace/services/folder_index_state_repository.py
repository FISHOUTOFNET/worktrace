"""Transaction-local mutations for durable folder-index state and facts."""

from __future__ import annotations

import sqlite3

from ..db import now_str

INDEX_STATUS_PENDING = "pending"
INDEX_STATUS_STALE = "stale"


def ensure_pending_state(conn: sqlite3.Connection, rule_id: int) -> bool:
    """Create the durable pending marker when a rule has no index state."""

    timestamp = now_str()
    cursor = conn.execute(
        """
        INSERT INTO folder_rule_index_state(
            folder_rule_id, status, valid_from, active_generation,
            building_generation, build_status, last_error, file_count,
            error_message, refresh_requested, created_at, updated_at
        )
        VALUES (?, ?, NULL, NULL, NULL, ?, NULL, 0, NULL, 1, ?, ?)
        ON CONFLICT(folder_rule_id) DO NOTHING
        """,
        (
            int(rule_id),
            INDEX_STATUS_PENDING,
            INDEX_STATUS_PENDING,
            timestamp,
            timestamp,
        ),
    )
    return cursor.rowcount == 1


def request_rebuild(conn: sqlite3.Connection, rule_id: int) -> bool:
    """Atomically make one rule discoverable by the rebuild worker."""

    state = conn.execute(
        """
        SELECT active_generation, building_generation
        FROM folder_rule_index_state
        WHERE folder_rule_id = ?
        """,
        (int(rule_id),),
    ).fetchone()
    if state is None:
        return ensure_pending_state(conn, rule_id)

    building_generation = int(state["building_generation"] or 0)
    if building_generation > 0:
        conn.execute(
            """
            DELETE FROM folder_rule_file_index
            WHERE folder_rule_id = ? AND generation = ?
            """,
            (int(rule_id), building_generation),
        )
    status = (
        INDEX_STATUS_STALE
        if state["active_generation"] is not None
        else INDEX_STATUS_PENDING
    )
    cursor = conn.execute(
        """
        UPDATE folder_rule_index_state
        SET status = ?, building_generation = NULL, build_status = ?,
            last_error = NULL, error_message = NULL,
            refresh_requested = 1, updated_at = ?
        WHERE folder_rule_id = ?
        """,
        (status, INDEX_STATUS_PENDING, now_str(), int(rule_id)),
    )
    return cursor.rowcount == 1


def delete_rule_index(conn: sqlite3.Connection, rule_id: int) -> bool:
    """Delete all derived index facts and state for one catalog rule."""

    facts = conn.execute(
        "DELETE FROM folder_rule_file_index WHERE folder_rule_id = ?",
        (int(rule_id),),
    )
    state = conn.execute(
        "DELETE FROM folder_rule_index_state WHERE folder_rule_id = ?",
        (int(rule_id),),
    )
    return bool((facts.rowcount or 0) + (state.rowcount or 0))


__all__ = ["delete_rule_index", "ensure_pending_state", "request_rebuild"]
