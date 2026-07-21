"""Declare the independent durable epoch for destructive data replacement.

This module exposes only low-level durable effect operations. It is not a
transaction owner: callers that need to replace the live database must use
``DatabaseReplacementUnitOfWork``, which captures the floor, opens the
exclusive transaction, advances the replacement epoch exactly once, commits,
and publishes the committed value to the process-local clock.
"""

from __future__ import annotations

import sqlite3

from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)

_REPLACEMENT_NAMESPACE = DataGenerationNamespace.DATABASE_REPLACEMENT
_REPLACEMENT_NAMESPACES = (_REPLACEMENT_NAMESPACE,)


def capture_replacement_generation_floor(
    conn: sqlite3.Connection,
) -> dict[DataGenerationNamespace, int]:
    """Capture only the live replacement epoch before replacing contents."""

    return DataGenerationRepository.get_many(conn, _REPLACEMENT_NAMESPACES)


__all__ = [
    "capture_replacement_generation_floor",
]
