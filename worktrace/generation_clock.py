"""Process-local view of committed durable generations.

The clock stores only generation counters, never domain rows. Command owners
publish after commit; cache owners include the counter in their cache key.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

from .data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from .db import get_connection, get_db_key

_LOCK = threading.RLock()
_VALUES: dict[tuple[str, DataGenerationNamespace], int] = {}


def _namespace(value: DataGenerationNamespace | str) -> DataGenerationNamespace:
    if isinstance(value, DataGenerationNamespace):
        return value
    return DataGenerationNamespace(str(value))


def generation(
    namespace: DataGenerationNamespace | str,
    *,
    conn=None,
) -> int:
    """Return the last committed generation for the active database."""

    resolved = _namespace(namespace)
    key = (get_db_key(), resolved)
    with _LOCK:
        cached = _VALUES.get(key)
    if cached is not None:
        return cached
    if conn is not None:
        value = DataGenerationRepository.get(conn, resolved)
    else:
        with get_connection() as read_conn:
            value = DataGenerationRepository.get(read_conn, resolved)
    with _LOCK:
        _VALUES[key] = int(value)
    return int(value)


def generation_tuple(
    namespaces: Iterable[DataGenerationNamespace | str],
    *,
    conn=None,
) -> tuple[int, ...]:
    return tuple(generation(namespace, conn=conn) for namespace in namespaces)


def publish_committed(
    conn,
    namespaces: Iterable[DataGenerationNamespace | str],
) -> None:
    """Publish counters only after the owning transaction has committed."""

    resolved = tuple(dict.fromkeys(_namespace(value) for value in namespaces))
    if not resolved:
        return
    values = DataGenerationRepository.get_many(conn, resolved)
    database_key = get_db_key()
    with _LOCK:
        for namespace, value in values.items():
            _VALUES[(database_key, namespace)] = int(value)


def clear(database_key: str | None = None) -> None:
    """Forget counters after database replacement or test reconfiguration."""

    with _LOCK:
        if database_key is None:
            _VALUES.clear()
            return
        for key in list(_VALUES):
            if key[0] == str(database_key):
                _VALUES.pop(key, None)


__all__ = ["clear", "generation", "generation_tuple", "publish_committed"]
