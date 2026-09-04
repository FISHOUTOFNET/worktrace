from __future__ import annotations

import logging
import sqlite3

import pytest

from worktrace import db
from worktrace.db import get_connection

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def test_explicit_writer_hold_is_attributed_without_sql_or_parameters(temp_db, monkeypatch, caplog):
    monkeypatch.setattr(db, "_WRITER_HOLD_WARNING_MS", 0.0)
    caplog.set_level(logging.WARNING)

    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE settings SET value = value WHERE key = ?", ("user_paused",))
        conn.commit()
    finally:
        conn.close()

    message = next(record.getMessage() for record in caplog.records if "database writer slow" in record.getMessage())
    assert "transaction_kind=explicit" in message
    assert "thread=" in message
    assert "user_paused" not in message
    assert "UPDATE settings" not in message


def test_database_busy_logs_waiter_contention_at_connection_boundary(temp_db, caplog):
    caplog.set_level(logging.WARNING)
    holder = get_connection()
    waiter = get_connection()
    try:
        holder.execute("BEGIN IMMEDIATE")
        waiter.execute("PRAGMA busy_timeout = 10")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
  waiter.execute("BEGIN IMMEDIATE")
    finally:
        holder.rollback()
        holder.close()
        waiter.close()

    message = next(record.getMessage() for record in caplog.records if "database writer contention" in record.getMessage())
    assert "outcome=database_busy" in message
    assert "transaction_kind=explicit" in message
    assert "thread=" in message
