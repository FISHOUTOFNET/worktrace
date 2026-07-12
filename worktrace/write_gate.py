"""Process-wide exclusion for live database writes.

The secure-import coordinator activates this gate only after background
collectors have acknowledged their pause. All SQLite connections created by
:mod:`worktrace.db` consult the gate before executing a write statement. The
thread that owns the import remains allowed to replace the live database.
"""

from __future__ import annotations

from contextlib import contextmanager
import sqlite3
import threading
from typing import Iterator


class ProcessDatabaseWriteGate:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active = False
        self._owner_thread_id: int | None = None

    def active(self) -> bool:
        with self._lock:
            return self._active

    def require_current_thread_allowed(self) -> None:
        thread_id = threading.get_ident()
        with self._lock:
            if self._active and self._owner_thread_id != thread_id:
                raise sqlite3.OperationalError("secure_import_in_progress")

    @contextmanager
    def acquire(self) -> Iterator[None]:
        thread_id = threading.get_ident()
        with self._lock:
            if self._active:
                raise sqlite3.OperationalError("secure_import_in_progress")
            self._active = True
            self._owner_thread_id = thread_id
        try:
            yield
        finally:
            with self._lock:
                self._active = False
                self._owner_thread_id = None


DATABASE_WRITE_GATE = ProcessDatabaseWriteGate()


__all__ = ["DATABASE_WRITE_GATE", "ProcessDatabaseWriteGate"]
