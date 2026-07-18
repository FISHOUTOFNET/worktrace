"""Declare durable cache invalidation for destructive data replacement."""

from __future__ import annotations

import sqlite3

from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..domain_unit_of_work import current_domain_unit_of_work

_REPLACEMENT_NAMESPACES = (
    DataGenerationNamespace.CLASSIFICATION_CATALOG,
    DataGenerationNamespace.SETTINGS,
    DataGenerationNamespace.PRIVACY_CATALOG,
    DataGenerationNamespace.DATABASE_REPLACEMENT,
)


def publish_database_replacement(conn: sqlite3.Connection) -> None:
    """Declare replacement generations without touching process-local caches.

    Normal replacement commands attach effects to the active ``DomainUnitOfWork``
    and receive atomic post-commit publication there. The encrypted-import path
    owns a lower-level exclusive SQLite transaction; for that path this helper
    only bumps durable values. Its maintenance coordinator clears the process
    clock after the connection context has committed.
    """

    uow = current_domain_unit_of_work()
    if uow is not None and uow.connection is conn:
        uow.add_effects(*_REPLACEMENT_NAMESPACES)
        uow.mark_changed()
        return
    DataGenerationRepository.bump(conn, _REPLACEMENT_NAMESPACES)


__all__ = ["publish_database_replacement"]
