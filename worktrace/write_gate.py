"""Process-wide write draining, exclusion, recovery blocking, and generations."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import sqlite3
import threading
from typing import Iterator

DATABASE_MAINTENANCE_ERROR = "database_maintenance_in_progress"
DATABASE_RECOVERY_ERROR = "database_maintenance_recovery_required"


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
    """Reject ordinary writes during maintenance or failed-closed recovery.

    The physical phase tracks one active drain/exclusive operation. A separate
    recovery block remains latched after that operation has ended whenever
    runtime restoration was not acknowledged. Only an explicit recovery writer
    may clear the durable latch while the process remains write-blocked.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase = WriteGatePhase.OPEN
        self._owner_thread_id: int | None = None
        self._generation = 0
        self._recovery_block_reason: str | None = None
        self._thread_state = threading.local()

    def active(self) -> bool:
        """Return whether ordinary writes are currently blocked."""

        with self._lock:
            return (
                self._phase is not WriteGatePhase.OPEN
                or self._recovery_block_reason is not None
            )

    def operation_active(self) -> bool:
        """Return whether a drain/exclusive operation is currently executing."""

        with self._lock:
            return self._phase is not WriteGatePhase.OPEN

    def recovery_blocked(self) -> bool:
        with self._lock:
            return self._recovery_block_reason is not None

    def recovery_block_reason(self) -> str | None:
        with self._lock:
            return self._recovery_block_reason

    def latch_recovery_block(self, reason: str) -> None:
        normalized = str(reason or "").strip()
        if not normalized:
            raise ValueError("maintenance_recovery_reason_required")
        with self._lock:
            self._recovery_block_reason = normalized

    def clear_recovery_block(self) -> None:
        with self._lock:
            self._recovery_block_reason = None

    def phase(self) -> WriteGatePhase:
        with self._lock:
            return self._phase

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def note_current_thread_read(self) -> None:
        with self._lock:
            self._thread_state.observed_generation = self._generation

    def _recovery_write_allowed(self) -> bool:
        return int(getattr(self._thread_state, "recovery_write_depth", 0)) > 0

    @contextmanager
    def allow_recovery_write(self) -> Iterator[None]:
        """Permit only the current thread to update the durable recovery latch."""

        depth = int(getattr(self._thread_state, "recovery_write_depth", 0))
        self._thread_state.recovery_write_depth = depth + 1
        try:
            yield
        finally:
            self._thread_state.recovery_write_depth = depth

    def require_current_thread_allowed(self) -> None:
        """Validate one write at statement admission time."""

        thread_id = threading.get_ident()
        with self._lock:
            if (
                self._recovery_block_reason is not None
                and not self._recovery_write_allowed()
            ):
                raise sqlite3.OperationalError(DATABASE_RECOVERY_ERROR)

            if self._phase is WriteGatePhase.EXCLUSIVE:
                if thread_id != self._owner_thread_id:
                    raise sqlite3.OperationalError(DATABASE_MAINTENANCE_ERROR)
                self._thread_state.observed_generation = self._generation
                return

            if self._phase is WriteGatePhase.DRAINING:
                if thread_id != self._owner_thread_id:
                    raise sqlite3.OperationalError(DATABASE_MAINTENANCE_ERROR)
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
            if self._recovery_block_reason is not None:
                raise sqlite3.OperationalError(DATABASE_RECOVERY_ERROR)
            if self._phase is not WriteGatePhase.OPEN:
                raise sqlite3.OperationalError(DATABASE_MAINTENANCE_ERROR)
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
    "DATABASE_MAINTENANCE_ERROR",
    "DATABASE_RECOVERY_ERROR",
    "DATABASE_WRITE_GATE",
    "ProcessDatabaseWriteGate",
    "WriteDrainLease",
    "WriteGatePhase",
]
