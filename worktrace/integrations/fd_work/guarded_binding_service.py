"""FD Work binding service with durable main-database identity isolation."""

from __future__ import annotations

import hashlib
import threading
from typing import Callable

from .binding_identity_store import (
    FDWorkBindingIdentityStore,
    FDWorkBindingIdentityStoreError,
)
from .binding_repository import FDWorkBindingRepository, FDWorkBindingStoreError
from .binding_service import FDWorkBindingService
from .contracts import FDWorkEntryError


DatabaseIdentityReader = Callable[[], tuple[str, int]]


class _IdentityGuardedRepository:
    """Proxy every sidecar operation through the current main-DB identity."""

    def __init__(
        self,
        repository: FDWorkBindingRepository,
        guard: Callable[[], None],
    ) -> None:
        self._repository = repository
        self._guard = guard

    def __getattr__(self, name: str):
        attribute = getattr(self._repository, name)
        if not callable(attribute):
            return attribute

        def guarded(*args, **kwargs):
            self._guard()
            return attribute(*args, **kwargs)

        return guarded


class GuardedFDWorkBindingService(FDWorkBindingService):
    """Fail closed when durable FD Work state belongs to another main DB epoch.

    Existing sidecars without an identity record are adopted once for upgrade
    compatibility. After that, a database replacement changes the WorkTrace
    replacement epoch; if sidecar cleanup failed, the stale identity remains and
    the next process clears the stale bindings before any read or reconciliation.
    """

    def __init__(
        self,
        repository: FDWorkBindingRepository,
        *,
        database_identity_reader: DatabaseIdentityReader,
        identity_store: FDWorkBindingIdentityStore | None = None,
        **kwargs,
    ) -> None:
        super().__init__(repository, **kwargs)
        self._raw_repository = repository
        self._database_identity_reader = database_identity_reader
        self._identity_store = identity_store or FDWorkBindingIdentityStore(
            repository.path.with_name(f"{repository.path.name}.identity")
        )
        self._database_identity_lock = threading.RLock()
        self.repository = _IdentityGuardedRepository(
            repository,
            self._require_current_database_identity,
        )
        try:
            self._ensure_current_database_identity()
        except Exception:
            # Startup remains fail-closed. Every later repository operation will
            # retry the guard, so a temporary file lock can recover in-process.
            self._all_invalidated = True

    def _current_database_identity(self) -> str:
        database_key, replacement_epoch = self._database_identity_reader()
        payload = f"{str(database_key)}\0{int(replacement_epoch)}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _ensure_current_database_identity(self) -> None:
        current = self._current_database_identity()
        with self._database_identity_lock:
            stored = self._identity_store.read()
            if stored is None:
                # One-time upgrade path from the pre-identity sidecar format.
                # Adoption itself must be durable; otherwise stay fail-closed.
                self._identity_store.write(current)
                self._all_invalidated = False
                return
            if stored == current:
                self._all_invalidated = False
                return

            # The sidecar belongs to a superseded main database. Never attempt
            # project-id/name reconciliation across replacement epochs.
            self._all_invalidated = True
            if self._raw_repository.path.exists():
                self._raw_repository.clear_all()
            self._identity_store.write(current)
            self._invalidated_project_ids.clear()
            self._all_invalidated = False

    def _require_current_database_identity(self) -> None:
        try:
            self._ensure_current_database_identity()
        except FDWorkBindingStoreError:
            self._all_invalidated = True
            raise
        except FDWorkBindingIdentityStoreError as exc:
            self._all_invalidated = True
            raise FDWorkBindingStoreError("binding_store_unavailable") from exc
        except Exception as exc:
            self._all_invalidated = True
            raise FDWorkBindingStoreError("binding_store_unavailable") from exc

    def clear_all_bindings(self, *, delete_database: bool = False) -> None:
        # The base workflow deliberately invalidates in-memory truth before
        # touching the second SQLite database. The proxy first verifies/repairs
        # epoch ownership, then the base clear executes. Publish the new identity
        # only after that clear succeeds.
        super().clear_all_bindings(delete_database=delete_database)
        try:
            self._identity_store.write(self._current_database_identity())
        except FDWorkBindingIdentityStoreError as exc:
            self._all_invalidated = True
            raise FDWorkEntryError("binding_store_unavailable") from exc
        except Exception as exc:
            self._all_invalidated = True
            raise FDWorkEntryError("binding_store_unavailable") from exc


__all__ = ["GuardedFDWorkBindingService"]
