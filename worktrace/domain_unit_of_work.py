"""Explicit domain transaction owner with atomic durable generation effects."""

from __future__ import annotations

from contextvars import ContextVar, Token
from functools import wraps
from typing import Callable, Iterable, ParamSpec, TypeVar

from .data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)

_CURRENT_UNIT_OF_WORK: ContextVar[DomainUnitOfWork | None] = ContextVar(
    "worktrace_domain_unit_of_work",
    default=None,
)


class UnitOfWorkConnectionLease:
    """Non-owning connection facade returned to nested repository code."""

    def __init__(self, unit_of_work: DomainUnitOfWork) -> None:
        object.__setattr__(self, "_unit_of_work", unit_of_work)

    def __enter__(self) -> UnitOfWorkConnectionLease:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is not None:
            self._unit_of_work.mark_rollback_only()
        return False

    def __getattr__(self, name):
        return getattr(self._unit_of_work.connection, name)

    def execute(self, sql, parameters=(), /):
        upper = str(sql or "").strip().upper()
        if upper.startswith("BEGIN") or upper in {"COMMIT", "END"}:
            return _NoOpCursor()
        if upper.startswith("ROLLBACK"):
            self._unit_of_work.mark_rollback_only()
            return _NoOpCursor()
        return self._unit_of_work.connection.execute(sql, parameters)

    def executemany(self, sql, seq_of_parameters, /):
        return self._unit_of_work.connection.executemany(sql, seq_of_parameters)

    def executescript(self, sql_script, /):
        raise RuntimeError("executescript_not_allowed_in_domain_unit_of_work")

    def __setattr__(self, name, value) -> None:
        if name == "_unit_of_work":
            object.__setattr__(self, name, value)
            return
        setattr(self._unit_of_work.connection, name, value)

    def commit(self) -> None:
        """The root unit of work owns commit."""

    def rollback(self) -> None:
        self._unit_of_work.mark_rollback_only()

    def close(self) -> None:
        """Nested users never close the root connection."""


class _NoOpCursor:
    rowcount = -1
    lastrowid = None

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class DomainUnitOfWork:
    """Own one SQLite transaction and publish declared effects exactly once."""

    def __init__(
        self,
        effects: Iterable[DataGenerationNamespace | str] = (),
        *,
        allow_no_effect: bool = False,
    ) -> None:
        self._effects = {
            DataGenerationNamespace(str(effect))
            for effect in effects
        }
        self._parent: DomainUnitOfWork | None = None
        self._token: Token[DomainUnitOfWork | None] | None = None
        self._connection = None
        self._lease: UnitOfWorkConnectionLease | None = None
        self._rollback_only = False
        self._allow_no_effect = bool(allow_no_effect)

    @property
    def connection(self):
        if self._parent is not None:
            return self._parent.connection
        if self._connection is None:
            raise RuntimeError("domain_unit_of_work_not_active")
        return self._connection

    @property
    def effects(self) -> frozenset[DataGenerationNamespace]:
        if self._parent is not None:
            return self._parent.effects
        return frozenset(self._effects)

    def add_effects(
        self,
        *effects: DataGenerationNamespace | str,
    ) -> None:
        target = self._parent or self
        target._effects.update(
            DataGenerationNamespace(str(effect))
            for effect in effects
        )

    def mark_rollback_only(self) -> None:
        target = self._parent or self
        target._rollback_only = True

    def lease(self) -> UnitOfWorkConnectionLease:
        target = self._parent or self
        if target._lease is None:
            target._lease = UnitOfWorkConnectionLease(target)
        return target._lease

    def __enter__(self) -> DomainUnitOfWork:
        current = _CURRENT_UNIT_OF_WORK.get()
        if current is not None:
            self._parent = current
            current.add_effects(*self._effects)
            return current

        from .db import _open_connection

        self._connection = _open_connection()
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
            wrote = bool(getattr(connection, "_domain_write_occurred", False))
            if wrote:
                if not self._effects and not self._allow_no_effect:
                    raise RuntimeError("domain_mutation_effect_required")
                if self._effects:
                    DataGenerationRepository.bump(connection, self._effects)
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
            self._lease = None


def current_domain_unit_of_work() -> DomainUnitOfWork | None:
    return _CURRENT_UNIT_OF_WORK.get()


P = ParamSpec("P")
R = TypeVar("R")


def domain_mutation(
    *effects: DataGenerationNamespace | str,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Run a mutation owner in one root-or-nested domain transaction."""

    resolved = tuple(DataGenerationNamespace(str(effect)) for effect in effects)
    if not resolved:
        raise ValueError("domain_mutation_effect_required")

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with DomainUnitOfWork(resolved):
                return function(*args, **kwargs)

        return wrapped

    return decorate


def transactional_write(function: Callable[P, R]) -> Callable[P, R]:
    """Run a durable write that intentionally invalidates no derived namespace."""

    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with DomainUnitOfWork(allow_no_effect=True):
            return function(*args, **kwargs)

    return wrapped


__all__ = [
    "DomainUnitOfWork",
    "UnitOfWorkConnectionLease",
    "current_domain_unit_of_work",
    "domain_mutation",
    "transactional_write",
]
