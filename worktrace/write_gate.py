"""Process-wide write draining, exclusion, and generation tracking."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import sqlite3
import threading
from typing import Iterator


class WriteGatePhase(str, Enum):
    OPEN = "open"
    DRAINING = "draining"
    EXCLUSIVE = "exclusive"


@dataclass(frozen=True)
class WriteDrainLease:
    """Short-lived capability for promoting one drained window to exclusivity."""

    _gate: "ProcessDatabaseWriteGate"
    _owner_thread_id: int

    def promote(self) -> None:
        self._gate.promote_to_exclusive(self._owner_thread_id)


class ProcessDatabaseWriteGate:
    """Reject new writes while SQLite drains, then grant one exclusive owner.

    The gate never grants durable write authority to a worker identity. The
    maintenance coordinator must quiesce the Collector while the gate is OPEN;
    only then may the coordinator enter DRAINING and eventually EXCLUSIVE.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase = WriteGatePhase.OPEN
        self._owner_thread_id: int | None = None
        self._generation = 0
        self._thread_state = threading.local()

    def active(self) -> bool:
        with self._lock:
            return self._phase is not WriteGatePhase.OPEN

    def phase(self) -> WriteGatePhase:
        with self._lock:
            return self._phase

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def note_current_thread_read(self) -> None:
        with self._lock:
            self._thread_state.observed_generation = self._generation

    def require_current_thread_allowed(self) -> None:
        """Validate one write at statement admission time."""

        thread_id = threading.get_ident()
        with self._lock:
            if self._phase is WriteGatePhase.EXCLUSIVE:
                if thread_id != self._owner_thread_id:
                    raise sqlite3.OperationalError("secure_import_in_progress")
                self._thread_state.observed_generation = self._generation
                return

            if self._phase is WriteGatePhase.DRAINING:
                if thread_id != self._owner_thread_id:
                    raise sqlite3.OperationalError("secure_import_in_progress")
                self._thread_state.observed_generation = self._generation
                return

            observed = getattr(
                self._thread_state,
                "observed_generation",
                None,
            )
            if observed is not None and int(observed) != self._generation:
                raise sqlite3.OperationalError("database_generation_changed")
            self._thread_state.observed_generation = self._generation

    def promote_to_exclusive(self, owner_thread_id: int) -> None:
        owner = int(owner_thread_id)
        with self._lock:
            if (
                self._phase is not WriteGatePhase.DRAINING
                or self._owner_thread_id != owner
            ):
                raise sqlite3.OperationalError("write_gate_not_draining_owner")
            self._phase = WriteGatePhase.EXCLUSIVE

    @contextmanager
    def draining(self) -> Iterator[WriteDrainLease]:
        owner = threading.get_ident()
        with self._lock:
            if self._phase is not WriteGatePhase.OPEN:
                raise sqlite3.OperationalError("secure_import_in_progress")
            self._phase = WriteGatePhase.DRAINING
            self._owner_thread_id = owner
            self._thread_state.observed_generation = self._generation

        try:
            yield WriteDrainLease(self, owner)
        finally:
            with self._lock:
                self._generation += 1
                self._phase = WriteGatePhase.OPEN
                self._owner_thread_id = None
                self._thread_state.observed_generation = self._generation


DATABASE_WRITE_GATE = ProcessDatabaseWriteGate()


__all__ = [
    "DATABASE_WRITE_GATE",
    "ProcessDatabaseWriteGate",
    "WriteDrainLease",
    "WriteGatePhase",
]
