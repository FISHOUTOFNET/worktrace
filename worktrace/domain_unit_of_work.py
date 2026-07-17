"""Explicit caller-owned SQLite transaction with atomic generation effects.

The unit of work does not proxy modules, intercept nested commits, or infer
which namespaces a SQL statement affects. Command owners declare effects and
may mark semantic changes explicitly. A bounded connection change count also
covers approved low-level command helpers within the same transaction.
"""

from __future__ import annotations

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

# Report structure has a separate fallback publisher for repair and migration
# paths. Other declared namespaces are published directly by this transaction.
_FALLBACK_PUBLISHED_NAMESPACES = frozenset(
    {DataGenerationNamespace.REPORT_STRUCTURE}
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
        self._effects = {_namespace(effect) for effect in effects}
        self._root: DomainUnitOfWork | None = None
        self._connection = None
        self._token: Token[DomainUnitOfWork | None] | None = None
        self._initial_total_changes = 0
        self._changed = False
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
            return bool(owner._changed)
        return bool(
            owner._changed
            or int(owner._connection.total_changes) > owner._initial_total_changes
        )

    def add_effects(self, *effects: DataGenerationNamespace | str) -> None:
        self._owner()._effects.update(_namespace(effect) for effect in effects)

    def mark_changed(self) -> None:
        self._owner()._changed = True

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
        try:
            if exc_type is not None or self._rollback_only:
                connection.rollback()
                return False
            changed = bool(
                self._changed
                or int(connection.total_changes) > self._initial_total_changes
            )
            if changed and self._effects:
                explicit_effects = self._effects.difference(
                    _FALLBACK_PUBLISHED_NAMESPACES
                )
                if explicit_effects:
                    DataGenerationRepository.bump(connection, explicit_effects)
            connection.commit()
            return False
        except Exception:
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
