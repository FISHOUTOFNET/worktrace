"""Request-level read context for page ViewModel construction.

One explicit API request receives one SQLite read transaction and one detached
runtime sample. Canonical projection, structural revision and page DTO shaping
reuse that context instead of opening independent database views.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..db import get_connection, get_db_key
from .runtime_activity_state_service import (
    RuntimeActivitySample,
    bind_runtime_activity_sample,
    sample_runtime_activity_state,
)


@dataclass
class PageReadContext:
    conn: Any
    database_key: str
    runtime_sample: RuntimeActivitySample
    snapshot_cache: dict[tuple[str, str], Any] = field(default_factory=dict)


_CURRENT_PAGE_READ_CONTEXT: ContextVar[PageReadContext | None] = ContextVar(
    "worktrace_page_read_context",
    default=None,
)


def current_page_read_context() -> PageReadContext | None:
    return _CURRENT_PAGE_READ_CONTEXT.get()


@contextmanager
def page_read_scope() -> Iterator[PageReadContext]:
    """Bind a query-only SQLite snapshot and one runtime sample to a request."""

    existing = current_page_read_context()
    if existing is not None:
        yield existing
        return

    database_key = get_db_key()
    runtime_sample = sample_runtime_activity_state(database_key=database_key)
    conn = get_connection()
    conn.execute("PRAGMA query_only = ON")
    conn.execute("BEGIN")
    context = PageReadContext(
        conn=conn,
        database_key=database_key,
        runtime_sample=runtime_sample,
    )
    token = _CURRENT_PAGE_READ_CONTEXT.set(context)
    try:
        with bind_runtime_activity_sample(
            runtime_sample,
            database_key=database_key,
        ):
            yield context
    finally:
        _CURRENT_PAGE_READ_CONTEXT.reset(token)
        try:
            conn.rollback()
        finally:
            conn.close()


__all__ = [
    "PageReadContext",
    "current_page_read_context",
    "page_read_scope",
]
