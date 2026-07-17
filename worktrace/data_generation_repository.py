"""Durable generation namespaces used to invalidate derived application state."""

from __future__ import annotations

import sqlite3
from enum import StrEnum
from typing import Iterable


class DataGenerationNamespace(StrEnum):
    REPORT_STRUCTURE = "report_structure"
    CLASSIFICATION_CATALOG = "classification_catalog"
    SETTINGS = "settings"
    PRIVACY_CATALOG = "privacy_catalog"
    DATABASE_REPLACEMENT = "database_replacement"


ALL_DATA_GENERATION_NAMESPACES = tuple(DataGenerationNamespace)


class DataGenerationRepository:
    """Read and increment durable generations inside caller-owned transactions."""

    @staticmethod
    def ensure_rows(conn: sqlite3.Connection) -> None:
        conn.executemany(
            """
            INSERT INTO data_generation_state(namespace, generation)
            VALUES (?, 0)
            ON CONFLICT(namespace) DO NOTHING
            """,
            [(namespace.value,) for namespace in ALL_DATA_GENERATION_NAMESPACES],
        )

    @staticmethod
    def get(
        conn: sqlite3.Connection,
        namespace: DataGenerationNamespace | str,
    ) -> int:
        value = DataGenerationNamespace(str(namespace)).value
        row = conn.execute(
            "SELECT generation FROM data_generation_state WHERE namespace = ?",
            (value,),
        ).fetchone()
        if row is None:
            raise ValueError("database_schema_incompatible")
        return int(row["generation"] if isinstance(row, sqlite3.Row) else row[0])

    @staticmethod
    def get_many(
        conn: sqlite3.Connection,
        namespaces: Iterable[DataGenerationNamespace | str],
    ) -> dict[DataGenerationNamespace, int]:
        resolved = tuple(dict.fromkeys(DataGenerationNamespace(str(value)) for value in namespaces))
        return {
            namespace: DataGenerationRepository.get(conn, namespace)
            for namespace in resolved
        }

    @staticmethod
    def bump(
        conn: sqlite3.Connection,
        namespaces: Iterable[DataGenerationNamespace | str],
    ) -> None:
        resolved = tuple(dict.fromkeys(DataGenerationNamespace(str(value)) for value in namespaces))
        for namespace in resolved:
            cursor = conn.execute(
                """
                UPDATE data_generation_state
                SET generation = generation + 1
                WHERE namespace = ?
                """,
                (namespace.value,),
            )
            if cursor.rowcount != 1:
                raise ValueError("database_schema_incompatible")

    @staticmethod
    def reset_all(conn: sqlite3.Connection) -> None:
        DataGenerationRepository.ensure_rows(conn)
        conn.execute("UPDATE data_generation_state SET generation = 0")


__all__ = [
    "ALL_DATA_GENERATION_NAMESPACES",
    "DataGenerationNamespace",
    "DataGenerationRepository",
]
