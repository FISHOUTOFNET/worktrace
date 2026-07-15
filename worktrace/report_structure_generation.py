"""Process-local structural generations for report revision caching.

WorkTrace has a single collector owner per database. A monotonically increasing
process-local generation therefore provides an O(1) invalidation key without a
schema table or a second source of durable business truth.
"""

from __future__ import annotations

import threading

_LOCK = threading.Lock()
_GENERATIONS: dict[str, int] = {}


def current_generation(database_key: str) -> int:
    with _LOCK:
        return int(_GENERATIONS.get(str(database_key), 0))


def bump_generation(database_key: str) -> int:
    key = str(database_key)
    with _LOCK:
        value = int(_GENERATIONS.get(key, 0)) + 1
        _GENERATIONS[key] = value
        return value


def reset_generation(database_key: str | None = None) -> None:
    with _LOCK:
        if database_key is None:
            _GENERATIONS.clear()
        else:
            _GENERATIONS.pop(str(database_key), None)


__all__ = ["bump_generation", "current_generation", "reset_generation"]
