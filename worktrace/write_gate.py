"""Process-wide write draining, exclusion, recovery blocking, and generations."""

from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
import re
import sqlite3
import threading
from typing import Iterator

DATABASE_MAINTENANCE_ERROR = "database_maintenance_in_progress"
DATABASE_RECOVERY_ERROR = "database_maintenance_recovery_required"
_RECOVERY_WRITE_TABLE_PATTERN = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)"
    r"\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.IGNORECASE,
)
_RECOVERY_WRITE_TABLES = frozenset({"settings", "data_generation"})


class WriteGatePhase(str, Enum):
    OPEN = "open"
    DRAINING = "draining"
    EXCLUSIVE = "exclusive"


class WriteDrainLease:
    """Capability owned by the thread holding one physical maintenance window."""

    def __init__(self, gate: "ProcessDatabaseWriteGate", owner_thread_id: int) -> None:
        self._gate = gate
        self._owner_thread_id = int(owner_thread_id)
        self._recovery_handoff_completed = False

    def promote(self) -> None:
        self._gate.promote_to_exclusive(self._owner_thread_id)

    def handoff_to_recovery_block(self, reason: str) -> None:
        """Atomically convert this exclusive lease into a fail-closed block."""

        if self._recovery_handoff_completed:
            raise sqlite3.OperationalError("write_gate_recovery_handoff_already_completed")
        self._gate._handoff_exclusive_to_recovery_block(  # noqa: SLF001
            self._owner_thread_id,
            reason,
        )
        self._recovery_handoff_completed = True


class ProcessDatabaseWriteGate:
    """Reject ordinary writes during a physical operation or recovery block."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._phase = WriteGatePhase.OPEN
        self._owner_thread_id: int | None = None
        self._generation = 0
        self._recovery_block_reason: str | None = None
        self._thread_state = threading.local()

    def operation_active(self) -> bool:
        """Return whether a drain/exclusive operation is currently executing."""

        with self._lock:
            return self._phase is not WriteGatePhase.OPEN

    def recovery_blocked(self) -> bool:
        """Return whether runtime recovery still requires explicit confirmation."""

        with self._lock:
            return self._recovery_block_reason is not None

    def writes_blocked(self) -> bool:
        """Return whether ordinary writes are currently rejected."""

        with self._lock:
            return (
                self._phase is not WriteGatePhase.OPEN
                or self._recovery_block_reason is not None
            )

    def recovery_block_reason(self) -> str | None:
        with self._lock:
            return self._recovery_block_reason

    def _set_recovery_block(self, reason: str) -> None:
        normalized = str(reason or "").strip()
        if not normalized:
            raise ValueError("maintenance_recovery_reason_required")
        with self._lock:
            self._recovery_block_reason = normalized

    def _clear_recovery_block(self) -> None:
        with self._lock:
            self._recovery_block_reason = None

    def _handoff_exclusive_to_recovery_block(
        self,
        owner_thread_id: int,
        reason: str,
    ) -> None:
        normalized = str(reason or "").strip()
        if not normalized:
            raise ValueError("maintenance_recovery_reason_required")
        owner = int(owner_thread_id)
        with self._lock:
            if (
                self._phase is not WriteGatePhase.EXCLUSIVE
                or self._owner_thread_id != owner
            ):
                raise sqlite3.OperationalError("write_gate_not_exclusive_owner")
            if self._recovery_block_reason is not None:
                raise sqlite3.OperationalError("write_gate_recovery_handoff_already_completed")
            self._recovery_block_reason = normalized

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

    @staticmethod
    def _is_recovery_latch_sql(sql: str) -> bool:
        normalized = " ".join(str(sql or "").strip().split())
        upper = normalized.upper()
        if upper.startswith("BEGIN IMMEDIATE") or upper.startswith("BEGIN EXCLUSIVE"):
            return True
        tables = {
            str(table).casefold()
            for table in _RECOVERY_WRITE_TABLE_PATTERN.findall(normalized)
        }
        return bool(tables) and tables.issubset(_RECOVERY_WRITE_TABLES)

    @contextmanager
    def _maintenance_recovery_write_scope(self) -> Iterator[None]:
        """Permit the maintenance owner to update only the durable recovery latch."""

        depth = int(getattr(self._thread_state, "recovery_write_depth", 0))
        self._thread_state.recovery_write_depth = depth + 1
        try:
            yield
        finally:
            self._thread_state.recovery_write_depth = depth

    def require_current_thread_allowed(self, sql: str = "") -> None:
        """Validate one write at statement admission time."""

        thread_id = threading.get_ident()
        with self._lock:
            recovery_write = self._recovery_write_allowed()
            if recovery_write:
                if not self._is_recovery_latch_sql(sql):
                    raise sqlite3.OperationalError(DATABASE_RECOVERY_ERROR)
                if (
                    self._phase is not WriteGatePhase.OPEN
                    and thread_id != self._owner_thread_id
                ):
                    raise sqlite3.OperationalError(DATABASE_MAINTENANCE_ERROR)
                self._thread_state.observed_generation = self._generation
                return

            if self._recovery_block_reason is not None:
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
