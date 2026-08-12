"""Durable main-database identity guard for the FD Work sidecar.

The FD Work binding database is intentionally outside the main WorkTrace
backup/replace transaction. This tiny companion record prevents a stale binding
database from becoming authoritative again after a main-database replacement.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path


class FDWorkBindingIdentityStoreError(RuntimeError):
    pass


class FDWorkBindingIdentityStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def read(self) -> str | None:
        with self._lock:
            if not self.path.exists():
                return None
            try:
                value = self.path.read_text(encoding="ascii").strip().casefold()
            except OSError as exc:
                raise FDWorkBindingIdentityStoreError(
                    "binding_identity_unavailable"
                ) from exc
            if not self._valid(value):
                raise FDWorkBindingIdentityStoreError(
                    "binding_identity_corrupted"
                )
            return value

    def write(self, identity: str) -> None:
        value = str(identity or "").strip().casefold()
        if not self._valid(value):
            raise FDWorkBindingIdentityStoreError("binding_identity_invalid")
        with self._lock:
            temporary = self.path.with_name(f"{self.path.name}.tmp")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with temporary.open("w", encoding="ascii", newline="\n") as handle:
                    handle.write(value)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            except OSError as exc:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                raise FDWorkBindingIdentityStoreError(
                    "binding_identity_unavailable"
                ) from exc

    @staticmethod
    def _valid(value: str) -> bool:
        return len(value) == 64 and all(
            character in "0123456789abcdef" for character in value
        )


__all__ = [
    "FDWorkBindingIdentityStore",
    "FDWorkBindingIdentityStoreError",
]
