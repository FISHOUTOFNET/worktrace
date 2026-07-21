"""Explicit caller-owned SQLite transaction with atomic generation effects.

The unit of work does not proxy modules, intercept nested commits, inspect SQL,
or infer business effects from connection counters. Command owners declare the
namespaces they may change and explicitly mark only the namespaces whose user-
visible semantics actually changed. Root commit publishes each changed namespace
at most once; no-op and rollback paths publish nothing.
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
    """Own one root transaction and publish explicit changed effects once."""

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
        return bool(self._owner()._changed_effects)

    def add_effects(self, *effects: DataGenerationNamespace | str) -> None:
        self._owner()._effects.update(_namespace(effect) for effect in effects)

    def mark_changed(
        self,
        *namespaces: DataGenerationNamespace | str,
    ) -> None:
        """Mark explicitly declared namespaces as semantically changed.

        Callers that discover a namespace dynamically must first declare it with
        ``add_effects(namespace)``. Missing or undeclared namespaces are contract
        violations rather than silently ignored hints.
        """

        if not namespaces:
            raise RuntimeError("generation_effect_required")
        owner = self._owner()
        resolved = tuple(_namespace(value) for value in namespaces)
        undeclared = tuple(
            namespace for namespace in resolved if namespace not in owner._effects
        )
        if undeclared:
            raise RuntimeError("undeclared_generation_effect")
        owner._changed_effects.update(resolved)

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
            if self._changed_effects:
                DataGenerationRepository.bump(connection, self._changed_effects)
                committed_effects = tuple(self._changed_effects)
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
