from __future__ import annotations

import pytest

from worktrace.data_generation_repository import (
    ALL_DATA_GENERATION_NAMESPACES,
    DataGenerationNamespace,
    DataGenerationRepository,
)
from worktrace.db import get_connection

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


def test_reset_all_restores_every_current_namespace(temp_db):
    with get_connection() as conn:
        DataGenerationRepository.bump(conn, ALL_DATA_GENERATION_NAMESPACES)
        DataGenerationRepository.reset_all(conn)
        values = DataGenerationRepository.get_many(
            conn,
            ALL_DATA_GENERATION_NAMESPACES,
        )
    assert values == {namespace: 0 for namespace in ALL_DATA_GENERATION_NAMESPACES}


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
        with pytest.raises(ValueError, match="database_schema_incompatible"):
            DataGenerationRepository.bump_replacement(conn, minimum_value=100)
