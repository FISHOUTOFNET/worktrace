"""Process-local view of committed durable generations.

The clock stores only generation counters, never domain rows. Command owners
publish after commit; cache owners include the counter in their cache key.
Ordinary publication is monotonic. Database replacement uses a separate atomic
publication path because a newly installed database may legitimately have lower
counter values than the database it replaces.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping

from .data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from .db import get_connection, get_db_key
from .write_gate import DATABASE_WRITE_GATE

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
    """Return the last committed generation for the active database.

    The database read intentionally happens outside the process lock. The
    loaded value is then compare-and-published under the lock so a concurrent
    post-commit publication can never be overwritten by an older read.
    """

    resolved = _namespace(namespace)
    key = (get_db_key(), resolved)
    with _LOCK:
        cached = _VALUES.get(key)
    if cached is not None:
        return cached
    if conn is not None:
        loaded = int(DataGenerationRepository.get(conn, resolved))
    else:
        with get_connection() as read_conn:
            loaded = int(DataGenerationRepository.get(read_conn, resolved))
    with _LOCK:
        current = _VALUES.get(key)
        published = loaded if current is None else max(int(current), loaded)
        _VALUES[key] = published
        return published


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
    """Publish ordinary counters only after the owning transaction committed."""

    resolved = tuple(dict.fromkeys(_namespace(value) for value in namespaces))
    if not resolved:
        return
    values = DataGenerationRepository.get_many(conn, resolved)
    database_key = get_db_key()
    with _LOCK:
        for namespace, value in values.items():
            key = (database_key, namespace)
            _VALUES[key] = max(int(_VALUES.get(key, 0)), int(value))


def publish_replacement_committed(
    database_key: str,
    values: Mapping[DataGenerationNamespace | str, int],
) -> None:
    """Atomically publish a committed replacement and its database identity.

    The write-gate epoch advances only here, after the replacement transaction
    has committed and while the destructive maintenance owner still holds the
    exclusive lease. Read-only consistent snapshots never call this path.
    """

    DATABASE_WRITE_GATE.publish_database_replaced(threading.get_ident())
    resolved = {_namespace(namespace): int(value) for namespace, value in values.items()}
    key_prefix = str(database_key)
    with _LOCK:
        for key in list(_VALUES):
            if key[0] == key_prefix:
                _VALUES.pop(key, None)
        for namespace, value in resolved.items():
            _VALUES[(key_prefix, namespace)] = value


def clear(database_key: str | None = None) -> None:
    """Forget counters after test reconfiguration or publication failure."""

    with _LOCK:
        if database_key is None:
            _VALUES.clear()
            return
        for key in list(_VALUES):
            if key[0] == str(database_key):
                _VALUES.pop(key, None)


__all__ = [
    "clear",
    "generation",
    "generation_tuple",
    "publish_committed",
    "publish_replacement_committed",
]
