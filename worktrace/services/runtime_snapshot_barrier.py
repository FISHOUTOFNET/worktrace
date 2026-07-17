"""Consistent snapshot barrier shared by backup/export readers."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

from ..write_gate import DATABASE_WRITE_GATE
from .database_maintenance_barrier import drain_existing_writers

_LOCK = threading.Lock()


@contextmanager
def consistent_snapshot(
    quiesce_handler: Any,
    timeout_seconds: float = 5.0,
) -> Iterator[None]:
    """Drain writes, explicitly quiesce Collector, then hold exclusive read scope."""

    if quiesce_handler is None:
        raise RuntimeError("runtime_quiesce_capability_required")
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError("snapshot_maintenance_in_progress")
    try:
        with DATABASE_WRITE_GATE.draining() as lease:
            result = quiesce_handler(timeout_seconds=timeout_seconds)
            if not bool(result.get("ok")):
                raise RuntimeError("collector_quiesce_not_acknowledged")
            drain_existing_writers()
            lease.promote()
            yield
    finally:
        _LOCK.release()


__all__ = ["consistent_snapshot"]
