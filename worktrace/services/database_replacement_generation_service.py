"""Publish durable cache invalidation after destructive data replacement."""

from __future__ import annotations

import sqlite3

from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)

# REPORT_STRUCTURE is still published by the validated connection classifier.
# The remaining namespaces have no SQL fallback and must be invalidated explicitly
# inside the replacement transaction.
_REPLACEMENT_NAMESPACES = (
    DataGenerationNamespace.CLASSIFICATION_CATALOG,
    DataGenerationNamespace.SETTINGS,
    DataGenerationNamespace.PRIVACY_CATALOG,
    DataGenerationNamespace.DATABASE_REPLACEMENT,
)


def publish_database_replacement(conn: sqlite3.Connection) -> None:
    DataGenerationRepository.bump(conn, _REPLACEMENT_NAMESPACES)


__all__ = ["publish_database_replacement"]
