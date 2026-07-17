"""Publish durable cache invalidation after destructive data replacement."""

from __future__ import annotations

import sqlite3

from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)

_REPLACEMENT_NAMESPACES = (
    DataGenerationNamespace.CLASSIFICATION_CATALOG,
    DataGenerationNamespace.SETTINGS,
    DataGenerationNamespace.PRIVACY_CATALOG,
    DataGenerationNamespace.DATABASE_REPLACEMENT,
)


def publish_database_replacement(conn: sqlite3.Connection) -> None:
    DataGenerationRepository.bump(conn, _REPLACEMENT_NAMESPACES)


__all__ = ["publish_database_replacement"]
