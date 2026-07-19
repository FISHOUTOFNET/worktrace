"""Declare the independent durable epoch for destructive data replacement."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..domain_unit_of_work import current_domain_unit_of_work

_REPLACEMENT_NAMESPACE = DataGenerationNamespace.DATABASE_REPLACEMENT
_REPLACEMENT_NAMESPACES = (_REPLACEMENT_NAMESPACE,)


def capture_replacement_generation_floor(
    conn: sqlite3.Connection,
) -> dict[DataGenerationNamespace, int]:
    """Capture only the live replacement epoch before replacing contents."""

    return DataGenerationRepository.get_many(conn, _REPLACEMENT_NAMESPACES)


def publish_database_replacement(
    conn: sqlite3.Connection,
    *,
    minimum_values: Mapping[DataGenerationNamespace | str, int] | None = None,
) -> dict[DataGenerationNamespace, int] | None:
    """Publish exactly one replacement epoch without impersonating domain writes.

    A normal ``DomainUnitOfWork`` records the replacement effect and publishes
    it only after commit. Encrypted import writes the durable replacement epoch
    inside its exclusive transaction and publishes the exact committed value
    only after commit. Ordinary domain generations are intentionally unchanged.
    """

    uow = current_domain_unit_of_work()
    if uow is not None and uow.connection is conn:
        uow.add_effects(_REPLACEMENT_NAMESPACE)
        uow.mark_changed()
        return None

    minimum_value = None
    if minimum_values is not None:
        for namespace, value in minimum_values.items():
            if DataGenerationNamespace(str(namespace)) is _REPLACEMENT_NAMESPACE:
                minimum_value = int(value)
                break
    return DataGenerationRepository.bump_replacement(
        conn,
        minimum_value=minimum_value,
    )


__all__ = [
    "capture_replacement_generation_floor",
    "publish_database_replacement",
]
