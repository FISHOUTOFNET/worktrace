"""Explicit caller-owned SQLite transaction with atomic generation effects.

The unit of work deliberately does not proxy modules, intercept nested commits,
or infer domain effects from SQL. Command owners use ``connection`` directly and
call ``mark_changed`` only after a durable business fact actually changes.
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


class DomainUnitOfWork:
    """Own one root transaction and publish declared effects exactly once."""

    def __init__(
        self,
        effects: Iterable[DataGenerationNamespace | str] = (),
    ) -> None:
        self._effects = {
            DataGenerationNamespace(str(effect))
            for effect in effects
        }
        self._parent: DomainUnitOfWork | None = None
        self._connection = None
        self._token: Token[DomainUnitOfWork | None] | None = None
        self._changed = False
        self._rollback_only = False

    @property
    def connection(self):
        owner = self._parent or self
        if owner._connection is None:
            raise RuntimeError("domain_unit_of_work_not_active")
        return owner._connection

    @property
    def changed(self) -> bool:
        owner = self._parent or self
        return bool(owner._changed)

    def add_effects(self, *effects: DataGenerationNamespace | str) -> None:
        owner = self._parent or self
        owner._effects.update(
            DataGenerationNamespace(str(effect))
            for effect in effects
        )

    def mark_changed(self) -> None:
        owner = self._parent or self
        owner._changed = True

    def mark_rollback_only(self) -> None:
        owner = self._parent or self
        owner._rollback_only = True

    def __enter__(self) -> DomainUnitOfWork:
        current = _CURRENT_UNIT_OF_WORK.get()
        if current is not None:
            self._parent = current
            current.add_effects(*self._effects)
            return self

        from .db import get_connection

        self._connection = get_connection()
        self._connection.execute("BEGIN IMMEDIATE")
        self._token = _CURRENT_UNIT_OF_WORK.set(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._parent is not None:
            if exc_type is not None:
                self._parent.mark_rollback_only()
            return False

        connection = self.connection
        try:
            if exc_type is not None or self._rollback_only:
                connection.rollback()
                return False
            if self._changed and self._effects:
                DataGenerationRepository.bump(connection, self._effects)
                # Stage 2A still contains the report-only SQL classifier. An
                # explicitly owned transaction has already published its effects,
                # so prevent that transitional fallback from double-incrementing.
                if hasattr(connection, "_report_structure_dirty"):
                    connection._report_structure_dirty = False
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
    return _CURRENT_UNIT_OF_WORK.get()


__all__ = ["DomainUnitOfWork", "current_domain_unit_of_work"]
