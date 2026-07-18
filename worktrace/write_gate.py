"""Process-wide write draining, exclusion, and replacement epoch tracking."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Iterator


class WriteGatePhase(str, Enum):
    OPEN = "open"
    DRAINING = "draining"
    EXCLUSIVE = "exclusive"


@dataclass(frozen=True)
class WriteDrainLease:
    """Owner capability for one drained maintenance window."""

    _gate: "ProcessDatabaseWriteGate"
    _owner_thread_id: int

    def promote(self) -> None:
        self._gate.promote_to_exclusive(self._owner_thread_id)

    def publish_database_replaced(self) -> int:
        """Advance database identity only after replacement has committed."""

        return self._gate.publish_database_replaced(self._owner_thread_id)


class ProcessDatabaseWriteGate:
    """Reject new writes while SQLite drains, then grant one exclusive owner.

    Maintenance exclusion and database identity are separate concepts. Ordinary
    consistent snapshots use ``draining`` without changing the replacement epoch;
    destructive replacement explicitly publishes a new epoch after commit.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase = WriteGatePhase.OPEN
        self._owner_thread_id: int | None = None
        self._database_replacement_epoch = 0
        self._thread_state = threading.local()
        self._maintenance_thread_ids: set[int] = set()

    def active(self) -> bool:
        with self._lock:
            return self._phase is not WriteGatePhase.OPEN

    def phase(self) -> WriteGatePhase:
        with self._lock:
            return self._phase

    def generation(self) -> int:
        """Return the process-local database replacement epoch."""

        with self._lock:
            return self._database_replacement_epoch

    def register_maintenance_thread(self, thread_id: int | None) -> None:
        if thread_id is None:
            return
        with self._lock:
            self._maintenance_thread_ids.add(int(thread_id))

    def unregister_maintenance_thread(self, thread_id: int | None) -> None:
        if thread_id is None:
            return
        with self._lock:
            self._maintenance_thread_ids.discard(int(thread_id))

    def note_current_thread_read(self) -> None:
        with self._lock:
            self._thread_state.observed_generation = self._database_replacement_epoch

    def require_current_thread_allowed(self) -> None:
        """Validate one write at statement admission time."""

        thread_id = threading.get_ident()
        with self._lock:
            if self._phase is WriteGatePhase.EXCLUSIVE:
                if thread_id != self._owner_thread_id:
                    raise sqlite3.OperationalError("secure_import_in_progress")
                self._thread_state.observed_generation = (
                    self._database_replacement_epoch
                )
                return

            if self._phase is WriteGatePhase.DRAINING:
                if (
                    thread_id != self._owner_thread_id
                    and thread_id not in self._maintenance_thread_ids
                ):
                    raise sqlite3.OperationalError("secure_import_in_progress")
                self._thread_state.observed_generation = (
                    self._database_replacement_epoch
                )
                return

            observed = getattr(
                self._thread_state,
                "observed_generation",
                None,
            )
            if (
                observed is not None
                and int(observed) != self._database_replacement_epoch
            ):
                raise sqlite3.OperationalError("database_generation_changed")
            self._thread_state.observed_generation = self._database_replacement_epoch

    def promote_to_exclusive(self, owner_thread_id: int) -> None:
        owner = int(owner_thread_id)
        with self._lock:
            if (
                self._phase is not WriteGatePhase.DRAINING
                or self._owner_thread_id != owner
            ):
                raise sqlite3.OperationalError("write_gate_not_draining_owner")
            self._phase = WriteGatePhase.EXCLUSIVE

    def publish_database_replaced(self, owner_thread_id: int) -> int:
        owner = int(owner_thread_id)
        with self._lock:
            if (
                self._phase is not WriteGatePhase.EXCLUSIVE
                or self._owner_thread_id != owner
                or threading.get_ident() != owner
            ):
                raise sqlite3.OperationalError("database_replacement_not_exclusive_owner")
            self._database_replacement_epoch += 1
            self._thread_state.observed_generation = (
                self._database_replacement_epoch
            )
            return self._database_replacement_epoch

    @contextmanager
    def draining(self) -> Iterator[WriteDrainLease]:
        owner = threading.get_ident()
        with self._lock:
            if self._phase is not WriteGatePhase.OPEN:
                raise sqlite3.OperationalError("secure_import_in_progress")
            self._phase = WriteGatePhase.DRAINING
            self._owner_thread_id = owner
            self._thread_state.observed_generation = (
                self._database_replacement_epoch
            )

        try:
            yield WriteDrainLease(self, owner)
        finally:
            with self._lock:
                self._phase = WriteGatePhase.OPEN
                self._owner_thread_id = None
                self._thread_state.observed_generation = (
                    self._database_replacement_epoch
                )


DATABASE_WRITE_GATE = ProcessDatabaseWriteGate()


__all__ = [
    "DATABASE_WRITE_GATE",
    "ProcessDatabaseWriteGate",
    "WriteDrainLease",
    "WriteGatePhase",
]
