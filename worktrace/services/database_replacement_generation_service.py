"""Declare durable cache invalidation for destructive data replacement."""

from __future__ import annotations

import sqlite3

from ..data_generation_repository import DataGenerationNamespace
from ..domain_unit_of_work import current_domain_unit_of_work

_REPLACEMENT_NAMESPACES = (
    DataGenerationNamespace.CLASSIFICATION_CATALOG,
    DataGenerationNamespace.SETTINGS,
    DataGenerationNamespace.PRIVACY_CATALOG,
    DataGenerationNamespace.DATABASE_REPLACEMENT,
)


def publish_database_replacement(conn: sqlite3.Connection) -> None:
    """Attach replacement effects to the active caller-owned unit of work.

    The generation clock is published by ``DomainUnitOfWork`` only after the
    replacement transaction commits. Calling this function outside the active
    replacement UoW is a programming error because pre-commit cache reset would
    reopen the stale-generation race this boundary exists to prevent.
    """

    uow = current_domain_unit_of_work()
    if uow is None or uow.connection is not conn:
        raise RuntimeError("database_replacement_requires_active_uow")
    uow.add_effects(*_REPLACEMENT_NAMESPACES)
    uow.mark_changed()


__all__ = ["publish_database_replacement"]
