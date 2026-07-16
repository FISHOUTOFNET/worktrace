"""Process-wide write draining, exclusion, and generation tracking."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import sqlite3
import threading
import time
from typing import Iterator


class WriteGatePhase(str, Enum):
    OPEN = "open"
    DRAINING = "draining"
    EXCLUSIVE = "exclusive"


@dataclass(frozen=True)
class WriteDrainLease:
    """Owner capability for promoting one draining window to exclusivity."""

    _gate: "ProcessDatabaseWriteGate"
    _owner_thread_id: int

    def promote(self, timeout_seconds: float = 5.0) -> None:
        self._gate.promote_to_exclusive(
            self._owner_thread_id,
            timeout_seconds=timeout_seconds,
        )


class ProcessDatabaseWriteGate:
    """Drain existing writes, reject new writers, then grant one exclusive owner."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._phase = WriteGatePhase.OPEN
        self._owner_thread_id: int | None = None
        self._generation = 0
        self._thread_state = threading.local()
        self._active_write_tokens: dict[int, int] = {}
        self._maintenance_thread_ids: set[int] = set()

    def active(self) -> bool:
        with self._condition:
            return self._phase is not WriteGatePhase.OPEN

    def phase(self) -> WriteGatePhase:
        with self._condition:
            return self._phase

    def generation(self) -> int:
        with self._condition:
            return self._generation

    def register_maintenance_thread(self, thread_id: int | None) -> None:
        if thread_id is None:
            return
        with self._condition:
            self._maintenance_thread_ids.add(int(thread_id))

    def unregister_maintenance_thread(self, thread_id: int | None) -> None:
        if thread_id is None:
            return
        with self._condition:
            self._maintenance_thread_ids.discard(int(thread_id))

    def note_current_thread_read(self) -> None:
        with self._condition:
            self._thread_state.observed_generation = self._generation

    def begin_write(self, connection_token: int) -> None:
        """Admit one connection transaction or continue its existing write."""

        token = int(connection_token)
        thread_id = threading.get_ident()
        with self._condition:
            existing_owner = self._active_write_tokens.get(token)
            is_existing = existing_owner == thread_id

            if self._phase is WriteGatePhase.EXCLUSIVE:
                if thread_id != self._owner_thread_id:
                    raise sqlite3.OperationalError("secure_import_in_progress")
            elif self._phase is WriteGatePhase.DRAINING:
                if not (
                    is_existing
                    or thread_id == self._owner_thread_id
                    or thread_id in self._maintenance_thread_ids
                ):
                    raise sqlite3.OperationalError("secure_import_in_progress")
            else:
                observed = getattr(
                    self._thread_state,
                    "observed_generation",
                    None,
                )
                if observed is not None and int(observed) != self._generation:
                    raise sqlite3.OperationalError("database_generation_changed")

            if existing_owner is not None and existing_owner != thread_id:
                raise sqlite3.OperationalError("connection_write_owner_changed")
            self._active_write_tokens[token] = thread_id
            self._thread_state.observed_generation = self._generation

    def finish_write(self, connection_token: int) -> None:
        token = int(connection_token)
        with self._condition:
            if self._active_write_tokens.pop(token, None) is not None:
                self._condition.notify_all()

    def promote_to_exclusive(
        self,
        owner_thread_id: int,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        owner = int(owner_thread_id)
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        with self._condition:
            if (
                self._phase is not WriteGatePhase.DRAINING
                or self._owner_thread_id != owner
            ):
                raise sqlite3.OperationalError("write_gate_not_draining_owner")

            while any(
                writer_thread_id != owner
                for writer_thread_id in self._active_write_tokens.values()
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise sqlite3.OperationalError(
                        "secure_import_drain_timeout"
                    )
                self._condition.wait(timeout=remaining)

            self._phase = WriteGatePhase.EXCLUSIVE
            self._condition.notify_all()

    @contextmanager
    def draining(self) -> Iterator[WriteDrainLease]:
        owner = threading.get_ident()
        with self._condition:
            if self._phase is not WriteGatePhase.OPEN:
                raise sqlite3.OperationalError("secure_import_in_progress")
            self._phase = WriteGatePhase.DRAINING
            self._owner_thread_id = owner
            self._thread_state.observed_generation = self._generation

        try:
            yield WriteDrainLease(self, owner)
        finally:
            with self._condition:
                self._generation += 1
                self._phase = WriteGatePhase.OPEN
                self._owner_thread_id = None
                self._thread_state.observed_generation = self._generation
                self._condition.notify_all()

    @contextmanager
    def acquire(self, timeout_seconds: float = 5.0) -> Iterator[None]:
        """Compatibility facade for callers that need immediate exclusivity."""

        with self.draining() as lease:
            lease.promote(timeout_seconds=timeout_seconds)
            yield


DATABASE_WRITE_GATE = ProcessDatabaseWriteGate()


__all__ = [
    "DATABASE_WRITE_GATE",
    "ProcessDatabaseWriteGate",
    "WriteDrainLease",
    "WriteGatePhase",
]
