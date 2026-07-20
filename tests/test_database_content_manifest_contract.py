from __future__ import annotations

import pytest

from worktrace.database_content_manifest import (
    BACKUP_TABLES,
    DATABASE_CONTENT,
    DELETE_ORDER,
    DERIVED_TABLES,
    INTERNAL_TABLES,
    REBUILT_AFTER_CLEAR_TABLES,
    TABLE_NAMES,
)
from worktrace.db import CURRENT_SCHEMA_VERSION, get_connection
from worktrace.services.secure_backup_service import BACKUP_FORMAT_VERSION

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _schema_tables(conn) -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
    }


def test_manifest_exactly_covers_current_schema(temp_db) -> None:
    with get_connection() as conn:
        actual = _schema_tables(conn)
    assert set(TABLE_NAMES) == actual
    assert len(TABLE_NAMES) == len(set(TABLE_NAMES))
    assert {item.name for item in DATABASE_CONTENT} == actual


def test_backup_and_clear_sets_derive_from_manifest(temp_db) -> None:
    manifest = {item.name: item for item in DATABASE_CONTENT}
    assert set(BACKUP_TABLES) <= set(TABLE_NAMES)
    assert set(DELETE_ORDER) <= set(TABLE_NAMES)
    assert set(BACKUP_TABLES).isdisjoint(INTERNAL_TABLES)
    assert set(BACKUP_TABLES).isdisjoint(
        {name for name in DERIVED_TABLES if manifest[name].backup_rank is None}
    )
    assert REBUILT_AFTER_CLEAR_TABLES == {"project", "settings"}
    assert all(manifest[name].delete_rank is not None for name in DELETE_ORDER)
    assert all(manifest[name].backup_rank is not None for name in BACKUP_TABLES)


def test_delete_order_places_foreign_key_children_before_parents(temp_db) -> None:
    positions = {table: index for index, table in enumerate(DELETE_ORDER)}
    with get_connection() as conn:
        for child in DELETE_ORDER:
            for row in conn.execute(f"PRAGMA foreign_key_list({child})").fetchall():
                parent = str(row["table"])
                if parent in positions:
                    assert positions[child] < positions[parent], (
                        f"{child} must be deleted before parent {parent}"
                    )


def test_current_only_schema_and_backup_versions_are_frozen() -> None:
    assert CURRENT_SCHEMA_VERSION == 13
    assert BACKUP_FORMAT_VERSION == 6
