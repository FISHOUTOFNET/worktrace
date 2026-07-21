"""Explicit caller-owned SQLite transaction with atomic generation effects.

The unit of work does not proxy modules, intercept nested commits, or infer
which namespaces a SQL statement affects. Command owners declare effects and
mark semantic changes explicitly per namespace. A bounded connection change
count covers single-effect scopes where the lone declared namespace is the
only possible target of any SQL in the transaction. Multi-effect scopes must
call ``mark_changed(namespace)`` explicitly so that no-op or rollback paths
never publish unrelated generations.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Iterable

from .data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)

_CURRENT_UNIT_OF_WORK: ContextVar[DomainUnitOfWork | None] = ContextVar(
    "worktrace_domain_unit_of_work",
    default=None,
)


def _namespace(value: DataGenerationNamespace | str) -> DataGenerationNamespace:
    if isinstance(value, DataGenerationNamespace):
        return value
    return DataGenerationNamespace(str(value))


class DomainUnitOfWork:
    """Own one root transaction and publish declared effects exactly once."""

    def __init__(
        self,
        effects: Iterable[DataGenerationNamespace | str] = (),
    ) -> None:
        self._effects: set[DataGenerationNamespace] = {
            _namespace(effect) for effect in effects
        }
        self._changed_effects: set[DataGenerationNamespace] = set()
        self._root: DomainUnitOfWork | None = None
        self._connection = None
        self._token: Token[DomainUnitOfWork | None] | None = None
        self._initial_total_changes = 0
        self._rollback_only = False

    def _owner(self) -> DomainUnitOfWork:
        return self._root or self

    @property
    def connection(self):
        owner = self._owner()
        if owner._connection is None:
            raise RuntimeError("domain_unit_of_work_not_active")
        return owner._connection

    @property
    def changed(self) -> bool:
        owner = self._owner()
        if owner._connection is None:
            return bool(owner._changed_effects)
        if len(owner._effects) == 1:
            single = next(iter(owner._effects))
            if single in owner._changed_effects:
                return True
            return int(owner._connection.total_changes) > owner._initial_total_changes
        return bool(owner._changed_effects)

    def add_effects(self, *effects: DataGenerationNamespace | str) -> None:
        self._owner()._effects.update(_namespace(effect) for effect in effects)

    def mark_changed(self, *namespaces: DataGenerationNamespace | str) -> None:
        """Mark namespaces as actually changed by this transaction.

        Without arguments, marks every declared effect as changed. This is a
        backward-compatible convenience that must only be used when every
        declared namespace is known to have been modified by the writes that
        ran in this scope. Multi-effect scopes should pass explicit namespaces
        so that no-op or rollback paths do not publish unrelated generations.
        """

        owner = self._owner()
        if not namespaces:
            owner._changed_effects.update(owner._effects)
            return
        for value in namespaces:
            resolved = _namespace(value)
            if resolved in owner._effects:
                owner._changed_effects.add(resolved)

    def mark_rollback_only(self) -> None:
        self._owner()._rollback_only = True

    def __enter__(self) -> DomainUnitOfWork:
        current = _CURRENT_UNIT_OF_WORK.get()
        if current is not None:
            root = current._owner()
            self._root = root
            root.add_effects(*self._effects)
            return self

        from .db import get_connection

        self._connection = get_connection()
        self._connection.execute("BEGIN IMMEDIATE")
        self._initial_total_changes = int(self._connection.total_changes)
        self._token = _CURRENT_UNIT_OF_WORK.set(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._root is not None:
            if exc_type is not None:
                self._root.mark_rollback_only()
            return False

        connection = self.connection
        committed = False
        committed_effects: tuple[DataGenerationNamespace, ...] = ()
        try:
            if exc_type is not None or self._rollback_only:
                connection.rollback()
                return False
            if len(self._effects) == 1:
                single = next(iter(self._effects))
                if (
                    single not in self._changed_effects
                    and int(connection.total_changes) > self._initial_total_changes
                ):
                    self._changed_effects.add(single)
            changed_effects = self._changed_effects & self._effects
            if changed_effects:
                DataGenerationRepository.bump(connection, changed_effects)
                committed_effects = tuple(changed_effects)
            connection.commit()
            committed = True
            if committed_effects:
                from .db import get_db_key
                from .generation_clock import publish_committed

                database_key = get_db_key()
                try:
                    publish_committed(connection, committed_effects)
                except Exception:
                    # The durable transaction is already committed. A failed
                    # process-local publication must degrade to a cache miss,
                    # never misreport the command itself as failed.
                    logging.exception("generation clock publication failed")
                    from .generation_clock import clear

                    clear(database_key)
            return False
        except Exception:
            if not committed:
                connection.rollback()
            raise
        finally:
            if self._token is not None:
                _CURRENT_UNIT_OF_WORK.reset(self._token)
            connection.close()
            self._connection = None


def current_domain_unit_of_work() -> DomainUnitOfWork | None:
    current = _CURRENT_UNIT_OF_WORK.get()
    return current._owner() if current is not None else None


__all__ = ["DomainUnitOfWork", "current_domain_unit_of_work"]
