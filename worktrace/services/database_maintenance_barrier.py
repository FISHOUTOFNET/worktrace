"""SQLite-backed drain barrier for destructive or snapshot maintenance."""

from __future__ import annotations

from ..db import get_connection


def drain_existing_writers() -> None:
    """Wait until pre-existing SQLite transactions release their write locks.

    The process write gate must already be in DRAINING state, so no new ordinary
    writer can enter while this short-lived exclusive transaction waits. Once the
    lock is acquired and rolled back, every transaction admitted before draining
    has finished and the caller may promote the process gate to EXCLUSIVE.
    """

    conn = get_connection()
    try:
        conn.execute("BEGIN EXCLUSIVE")
        conn.rollback()
    finally:
        conn.close()


__all__ = ["drain_existing_writers"]
