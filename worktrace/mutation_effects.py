"""Explicit transaction effects declared by domain mutation owners."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from enum import Enum
from functools import wraps
from typing import Callable, Iterator, ParamSpec, TypeVar


class MutationEffect(str, Enum):
    REPORT_STRUCTURE = "report_structure"
    CLASSIFICATION_CATALOG = "classification_catalog"
    SETTINGS = "settings"
    PRIVACY_CATALOG = "privacy_catalog"
    DATABASE_REPLACEMENT = "database_replacement"


_CURRENT_EFFECTS: ContextVar[frozenset[MutationEffect]] = ContextVar(
    "worktrace_mutation_effects",
    default=frozenset(),
)


def current_mutation_effects() -> frozenset[MutationEffect]:
    return _CURRENT_EFFECTS.get()


@contextmanager
def mutation_effects(*effects: MutationEffect) -> Iterator[None]:
    """Add explicit effects to every write transaction opened in this scope."""

    merged = frozenset({*current_mutation_effects(), *effects})
    token = _CURRENT_EFFECTS.set(merged)
    try:
        yield
    finally:
        _CURRENT_EFFECTS.reset(token)


P = ParamSpec("P")
R = TypeVar("R")


def declares_mutation_effects(
    *effects: MutationEffect,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorate a mutation owner with its durable transaction effects."""

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with mutation_effects(*effects):
                return function(*args, **kwargs)

        return wrapped

    return decorate


report_structure_mutation = declares_mutation_effects(
    MutationEffect.REPORT_STRUCTURE,
)


__all__ = [
    "MutationEffect",
    "current_mutation_effects",
    "declares_mutation_effects",
    "mutation_effects",
    "report_structure_mutation",
]
