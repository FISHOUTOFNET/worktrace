"""Consistent snapshot barrier shared by backup/export readers."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

from ..write_gate import DATABASE_WRITE_GATE

_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_QUIESCE_HANDLER: Any = None


def register_quiesce_handler(handler: Any) -> None:
    global _QUIESCE_HANDLER
    with _STATE_LOCK:
        _QUIESCE_HANDLER = handler


def clear_quiesce_handler(handler: Any | None = None) -> None:
    global _QUIESCE_HANDLER
    with _STATE_LOCK:
        if handler is None or _QUIESCE_HANDLER == handler:
            _QUIESCE_HANDLER = None


@contextmanager
def consistent_snapshot(timeout_seconds: float = 5.0) -> Iterator[None]:
    """Quiesce Collector writes and hold the process write gate for one read."""

    if not _LOCK.acquire(blocking=False):
        raise RuntimeError("snapshot_maintenance_in_progress")
    try:
        with _STATE_LOCK:
            handler = _QUIESCE_HANDLER
        if handler is not None:
            result = handler(timeout_seconds=timeout_seconds)
            if not bool(result.get("ok")):
                raise RuntimeError("collector_quiesce_not_acknowledged")
        with DATABASE_WRITE_GATE.acquire():
            yield
    finally:
        _LOCK.release()


__all__ = [
    "clear_quiesce_handler",
    "consistent_snapshot",
    "register_quiesce_handler",
]
