"""Declare durable cache invalidation for destructive data replacement."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from ..data_generation_repository import (
    ALL_DATA_GENERATION_NAMESPACES,
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..domain_unit_of_work import current_domain_unit_of_work

_REPLACEMENT_NAMESPACES = ALL_DATA_GENERATION_NAMESPACES


def capture_replacement_generation_floor(
    conn: sqlite3.Connection,
) -> dict[DataGenerationNamespace, int]:
    """Capture the live durable counters before destructive replacement."""

    return DataGenerationRepository.get_many(conn, _REPLACEMENT_NAMESPACES)


def publish_database_replacement(
    conn: sqlite3.Connection,
    *,
    minimum_values: Mapping[DataGenerationNamespace | str, int] | None = None,
) -> dict[DataGenerationNamespace, int] | None:
    """Declare replacement generations without touching process-local caches.

    The normal ``DomainUnitOfWork`` path records effects here and publishes them
    after its transaction commits. Encrypted import instead writes durable
    replacement generations inside its exclusive transaction, commits, and then
    publishes the exact committed values to the process clock. Only a failure
    of that post-commit publication clears the process clock, so later reads
    reload the already durable values.
    """

    uow = current_domain_unit_of_work()
    if uow is not None and uow.connection is conn:
        uow.add_effects(*_REPLACEMENT_NAMESPACES)
        uow.mark_changed()
        return None
    if minimum_values is None:
        DataGenerationRepository.bump(conn, _REPLACEMENT_NAMESPACES)
    else:
        DataGenerationRepository.ensure_rows(conn)
        floors = {
            DataGenerationNamespace(str(namespace)): int(value)
            for namespace, value in minimum_values.items()
        }
        for namespace in _REPLACEMENT_NAMESPACES:
            conn.execute(
                """
                UPDATE data_generation_state
                SET generation = MAX(generation, ?) + 1
                WHERE namespace = ?
                """,
                (int(floors.get(namespace, 0)), namespace.value),
            )
    return DataGenerationRepository.get_many(conn, _REPLACEMENT_NAMESPACES)


__all__ = [
    "capture_replacement_generation_floor",
    "publish_database_replacement",
]
