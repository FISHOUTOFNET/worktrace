from __future__ import annotations

import sqlite3

import pytest

from worktrace.data_generation_repository import (
    ALL_DATA_GENERATION_NAMESPACES,
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection
from worktrace.schema_migrations import migrate_7_to_8

pytestmark = [pytest.mark.db, pytest.mark.contract, pytest.mark.serial]


def test_current_schema_seeds_every_generation_namespace(temp_db):
    with get_connection() as conn:
        values = DataGenerationRepository.get_many(
            conn,
            ALL_DATA_GENERATION_NAMESPACES,
        )

    assert set(values) == set(ALL_DATA_GENERATION_NAMESPACES)
    assert all(value >= 0 for value in values.values())


def test_repository_bumps_only_selected_namespaces(temp_db):
    with get_connection() as conn:
        before = DataGenerationRepository.get_many(
            conn,
            ALL_DATA_GENERATION_NAMESPACES,
        )
        DataGenerationRepository.bump(
            conn,
            (
                DataGenerationNamespace.SETTINGS,
                DataGenerationNamespace.PRIVACY_CATALOG,
                DataGenerationNamespace.SETTINGS,
            ),
        )

    with get_connection() as conn:
        after = DataGenerationRepository.get_many(
            conn,
            ALL_DATA_GENERATION_NAMESPACES,
        )

    assert after[DataGenerationNamespace.SETTINGS] == before[DataGenerationNamespace.SETTINGS] + 1
    assert after[DataGenerationNamespace.PRIVACY_CATALOG] == before[DataGenerationNamespace.PRIVACY_CATALOG] + 1
    for namespace in set(ALL_DATA_GENERATION_NAMESPACES) - {
        DataGenerationNamespace.SETTINGS,
        DataGenerationNamespace.PRIVACY_CATALOG,
    }:
        assert after[namespace] == before[namespace]


def test_generation_bump_rolls_back_with_caller_transaction(temp_db):
    conn = get_connection()
    try:
        before = DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
        )
        DataGenerationRepository.bump(
            conn,
            (DataGenerationNamespace.CLASSIFICATION_CATALOG,),
        )
        assert DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
        ) == before + 1
        conn.rollback()
    finally:
        conn.close()

    with get_connection() as read_conn:
        assert DataGenerationRepository.get(
            read_conn,
            DataGenerationNamespace.CLASSIFICATION_CATALOG,
        ) == before


def test_v7_migration_preserves_report_generation_and_removes_old_table():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(
            """
            CREATE TABLE report_structure_revision_state (
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
                generation INTEGER NOT NULL CHECK(generation >= 0)
            );
            INSERT INTO report_structure_revision_state(singleton_id, generation)
            VALUES (1, 41);
            """
        )

        migrate_7_to_8(conn)

        assert DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.REPORT_STRUCTURE,
        ) == 41
        assert {
            str(row["namespace"])
            for row in conn.execute(
                "SELECT namespace FROM data_generation_state"
            ).fetchall()
        } == {namespace.value for namespace in ALL_DATA_GENERATION_NAMESPACES}
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'report_structure_revision_state'"
        ).fetchone() is None
    finally:
        conn.close()


def test_missing_generation_namespace_is_schema_error(temp_db):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM data_generation_state WHERE namespace = ?",
            (DataGenerationNamespace.DATABASE_REPLACEMENT.value,),
        )

    with get_connection() as conn:
        with pytest.raises(ValueError, match="database_schema_incompatible"):
            DataGenerationRepository.get(
                conn,
                DataGenerationNamespace.DATABASE_REPLACEMENT,
            )
