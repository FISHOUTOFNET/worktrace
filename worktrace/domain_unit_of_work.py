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
from enum import StrEnum
from typing import Iterable

from .data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)

_CURRENT_UNIT_OF_WORK: ContextVar[DomainUnitOfWork | None] = ContextVar(
    "worktrace_domain_unit_of_work",
    default=None,
)


class UnitOfWorkState(StrEnum):
    ACQUIRING = "acquiring"
    ACTIVE = "active"
    DURABLE_COMMITTED = "durable_committed"
    ROLLED_BACK = "rolled_back"
    FINALIZED = "finalized"


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
        self._context_published = False
        self._rollback_only = False
        self._state = UnitOfWorkState.ACQUIRING
        self._durable_committed = False
        self._rolled_back = False

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

    @property
    def state(self) -> UnitOfWorkState:
        return self._owner()._state

    @property
    def durable_committed(self) -> bool:
        return self._owner()._durable_committed

    @property
    def rolled_back(self) -> bool:
        return self._owner()._rolled_back

    def add_effects(self, *effects: DataGenerationNamespace | str) -> None:
        self._owner()._effects.update(_namespace(effect) for effect in effects)

    def mark_changed(
        self,
        *namespaces: DataGenerationNamespace | str,
    ) -> None:
        """Mark explicitly declared namespaces as semantically changed."""

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

        connection = None
        try:
            connection = get_connection()
            connection.execute("BEGIN IMMEDIATE")
            self._connection = connection
            self._token = _CURRENT_UNIT_OF_WORK.set(self)
            self._context_published = True
            self._state = UnitOfWorkState.ACTIVE
            return self
        except BaseException:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    logging.warning(
                        "domain unit of work cleanup failed stage=acquisition"
                    )
            self._connection = None
            self._state = UnitOfWorkState.FINALIZED
            raise

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._root is not None:
            if exc_type is not None:
                self._root.mark_rollback_only()
            return False

        connection = self.connection
        primary_error = exc_value if exc_type is not None else None
        committed_effects: tuple[DataGenerationNamespace, ...] = ()
        database_key: str | None = None
        try:
            if primary_error is not None or self._rollback_only:
                try:
                    connection.rollback()
                except Exception:
                    logging.warning(
                        "domain unit of work rollback failed stage=operation"
                    )
                self._rolled_back = True
                self._state = UnitOfWorkState.ROLLED_BACK
                return False

            if self._changed_effects:
                from .db import get_db_key

                database_key = get_db_key()
                DataGenerationRepository.bump(connection, self._changed_effects)
                committed_effects = tuple(self._changed_effects)
            connection.commit()
            self._durable_committed = True
            self._state = UnitOfWorkState.DURABLE_COMMITTED

            if committed_effects:
                from .generation_clock import clear, publish_committed

                try:
                    publish_committed(connection, committed_effects)
                except Exception:
                    logging.warning(
                        "generation publication failed stage=post_commit"
                    )
                    try:
                        assert database_key is not None
                        clear(database_key)
                    except Exception:
                        logging.warning(
                            "generation cache invalidation failed stage=post_commit"
                        )
            return False
        except BaseException:
            if not self._durable_committed:
                try:
                    connection.rollback()
                except Exception:
                    logging.warning(
                        "domain unit of work rollback failed stage=commit"
                    )
                self._rolled_back = True
                self._state = UnitOfWorkState.ROLLED_BACK
            raise
        finally:
            token = self._token
            self._token = None
            if self._context_published:
                try:
                    _CURRENT_UNIT_OF_WORK.reset(token)  # type: ignore[arg-type]
                except Exception:
                    logging.warning(
                        "domain unit of work context reset failed stage=finalization"
                    )
                    _CURRENT_UNIT_OF_WORK.set(None)
                finally:
                    self._context_published = False
            try:
                connection.close()
            except Exception:
                logging.warning(
                    "domain unit of work connection close failed stage=finalization"
                )
            self._connection = None
            self._state = UnitOfWorkState.FINALIZED


def current_domain_unit_of_work() -> DomainUnitOfWork | None:
    current = _CURRENT_UNIT_OF_WORK.get()
    return current._owner() if current is not None else None


__all__ = [
    "DomainUnitOfWork",
    "UnitOfWorkState",
    "current_domain_unit_of_work",
]
