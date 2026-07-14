"""Process-wide exclusion and generation tracking for live database writes."""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
import threading
from typing import Iterator


class ProcessDatabaseWriteGate:
    """Reject concurrent import writes and post-import stale write intents."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active = False
        self._owner_thread_id: int | None = None
        self._generation = 0
        self._thread_state = threading.local()

    def active(self) -> bool:
        with self._lock:
            return self._active

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def note_current_thread_read(self) -> None:
        with self._lock:
            self._thread_state.observed_generation = self._generation

    def require_current_thread_allowed(self) -> None:
        thread_id = threading.get_ident()
        with self._lock:
            if self._active:
                if self._owner_thread_id != thread_id:
                    raise sqlite3.OperationalError("secure_import_in_progress")
                self._thread_state.observed_generation = self._generation
                return
            observed = getattr(self._thread_state, "observed_generation", None)
            if observed is not None and int(observed) != self._generation:
                raise sqlite3.OperationalError("database_generation_changed")
            self._thread_state.observed_generation = self._generation

    @contextmanager
    def acquire(self) -> Iterator[None]:
        thread_id = threading.get_ident()
        with self._lock:
            if self._active:
                raise sqlite3.OperationalError("secure_import_in_progress")
            self._generation += 1
            self._active = True
            self._owner_thread_id = thread_id
            self._thread_state.observed_generation = self._generation
        try:
            yield
        finally:
            with self._lock:
                self._generation += 1
                self._active = False
                self._owner_thread_id = None
                # The owner performed or rolled back the replacement and is the
                # only thread that can safely continue without a fresh read.
                self._thread_state.observed_generation = self._generation


DATABASE_WRITE_GATE = ProcessDatabaseWriteGate()


__all__ = ["DATABASE_WRITE_GATE", "ProcessDatabaseWriteGate"]
