"""Contracts separating maintenance exclusion from database replacement.

A read-only drain is process coordination, not evidence that SQLite identity
changed. Only the exclusive replacement owner may advance the epoch.
"""

from __future__ import annotations

import sqlite3

import pytest

from worktrace.write_gate import ProcessDatabaseWriteGate

pytestmark = [pytest.mark.contract, pytest.mark.db]


def test_read_only_drain_does_not_change_database_replacement_epoch():
    gate = ProcessDatabaseWriteGate()
    before = gate.generation()

    with gate.draining() as lease:
        lease.promote()

    assert gate.generation() == before


def test_exclusive_owner_publishes_database_replacement_once():
    gate = ProcessDatabaseWriteGate()

    with gate.draining() as lease:
        lease.promote()
        published = lease.publish_database_replaced()

    assert published == 1
    assert gate.generation() == 1


def test_database_replacement_cannot_be_published_without_exclusive_lease():
    gate = ProcessDatabaseWriteGate()

    with pytest.raises(
        sqlite3.OperationalError,
        match="database_replacement_not_exclusive_owner",
    ):
        gate.publish_database_replaced(0)
