"""Request-level verified read context for page ViewModel construction."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import logging
import threading
from typing import Any, Iterator

from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..db import get_connection, get_db_key
from .runtime_activity_state_service import (
    RuntimeActivitySample,
    bind_runtime_activity_sample,
    sample_runtime_activity_state,
)

_MAX_RUNTIME_RETRIES = 2
_DIAGNOSTIC_LOCK = threading.Lock()
_DIAGNOSTIC_KEYS: set[tuple[bool, bool, bool]] = set()


@dataclass
class PageReadContext:
    conn: Any
    database_key: str
    runtime_sample: RuntimeActivitySample
    verified_open_activity_id: int | None
    replacement_epoch: int
    report_generations: dict[DataGenerationNamespace, int]
    runtime_consistent: bool
    needs_full_refresh: bool
    snapshot_cache: dict[tuple[str, str], Any] = field(default_factory=dict)


_CURRENT_PAGE_READ_CONTEXT: ContextVar[PageReadContext | None] = ContextVar(
    "worktrace_page_read_context",
    default=None,
)


def current_page_read_context() -> PageReadContext | None:
    return _CURRENT_PAGE_READ_CONTEXT.get()


def _open_query_snapshot():
    conn = get_connection()
    conn.execute("PRAGMA query_only = ON")
    conn.execute("BEGIN")
    # This real read fixes the SQLite snapshot before any runtime validation.
    conn.execute("SELECT id FROM activity_log ORDER BY id DESC LIMIT 1").fetchone()
    return conn


def _snapshot_facts(conn) -> tuple[dict[DataGenerationNamespace, int], int | None]:
    generations = DataGenerationRepository.get_many(
        conn,
        tuple(DataGenerationNamespace),
    )
    open_rows = conn.execute(
        "SELECT id, end_time FROM activity_log WHERE end_time IS NULL ORDER BY id"
    ).fetchall()
    if len(open_rows) > 1:
        return generations, -1
    open_id = int(open_rows[0]["id"]) if open_rows else None
    return generations, open_id


def _runtime_activity_id(sample: RuntimeActivitySample) -> int | None:
    snapshot = sample.snapshot
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get("persisted_activity_id")
    return int(value) if type(value) is int and value > 0 else None


def _samples_match(
    sample_a: RuntimeActivitySample,
    sample_b: RuntimeActivitySample,
    *,
    database_key: str,
    replacement_epoch: int,
    open_activity_id: int | None,
) -> bool:
    if sample_a.revision != sample_b.revision:
        return False
    if (
        sample_a.database_key != database_key
        or sample_b.database_key != database_key
        or sample_a.replacement_epoch != replacement_epoch
        or sample_b.replacement_epoch != replacement_epoch
    ):
        return False
    runtime_id = _runtime_activity_id(sample_b)
    if open_activity_id == -1:
        return False
    if sample_b.snapshot is None:
        return open_activity_id is None
    return runtime_id is not None and runtime_id == open_activity_id


def _log_mismatch_once(
    sample: RuntimeActivitySample,
    open_activity_id: int | None,
    replacement_epoch: int,
) -> None:
    key = (
        sample.snapshot is not None,
        open_activity_id is not None,
        sample.replacement_epoch == replacement_epoch,
    )
    with _DIAGNOSTIC_LOCK:
        if key in _DIAGNOSTIC_KEYS:
            return
        _DIAGNOSTIC_KEYS.add(key)
    logging.warning(
        "page runtime/sqlite mismatch; durable-only projection selected "
        "runtime_present=%s durable_open=%s epoch_match=%s",
        key[0],
        key[1],
        key[2],
    )


@contextmanager
def page_read_scope() -> Iterator[PageReadContext]:
    """Bind one verified query-only SQLite snapshot and runtime sample."""

    existing = current_page_read_context()
    if existing is not None:
        yield existing
        return

    database_key = get_db_key()
    accepted: tuple[Any, RuntimeActivitySample, dict, int | None] | None = None
    last_sample: RuntimeActivitySample | None = None
    last_open_id: int | None = None
    last_generations: dict[DataGenerationNamespace, int] = {}

    for _attempt in range(_MAX_RUNTIME_RETRIES + 1):
        sample_a = sample_runtime_activity_state(database_key=database_key)
        conn = _open_query_snapshot()
        try:
            generations, open_id = _snapshot_facts(conn)
            replacement_epoch = int(
                generations.get(DataGenerationNamespace.DATABASE_REPLACEMENT, 0)
            )
            sample_b = sample_runtime_activity_state(database_key=database_key)
            if _samples_match(
                sample_a,
                sample_b,
                database_key=database_key,
                replacement_epoch=replacement_epoch,
                open_activity_id=open_id,
            ):
                accepted = (conn, sample_b, generations, open_id)
                break
            last_sample = sample_b
            last_open_id = open_id
            last_generations = generations
        except Exception:
            conn.rollback()
            conn.close()
            raise
        conn.rollback()
        conn.close()

    if accepted is None:
        conn = _open_query_snapshot()
        generations, open_id = _snapshot_facts(conn)
        replacement_epoch = int(
            generations.get(DataGenerationNamespace.DATABASE_REPLACEMENT, 0)
        )
        sample = last_sample or sample_runtime_activity_state(
            database_key=database_key
        )
        _log_mismatch_once(sample, last_open_id, replacement_epoch)
        runtime_sample = RuntimeActivitySample(
            snapshot=None,
            revision=int(sample.revision),
            database_key=database_key,
            replacement_epoch=replacement_epoch,
        )
        context = PageReadContext(
            conn=conn,
            database_key=database_key,
            runtime_sample=runtime_sample,
            verified_open_activity_id=open_id if open_id != -1 else None,
            replacement_epoch=replacement_epoch,
            report_generations=generations or last_generations,
            runtime_consistent=False,
            needs_full_refresh=True,
        )
    else:
        conn, runtime_sample, generations, open_id = accepted
        replacement_epoch = int(
            generations.get(DataGenerationNamespace.DATABASE_REPLACEMENT, 0)
        )
        context = PageReadContext(
            conn=conn,
            database_key=database_key,
            runtime_sample=runtime_sample,
            verified_open_activity_id=open_id,
            replacement_epoch=replacement_epoch,
            report_generations=generations,
            runtime_consistent=True,
            needs_full_refresh=False,
        )

    token = _CURRENT_PAGE_READ_CONTEXT.set(context)
    try:
        with bind_runtime_activity_sample(
            context.runtime_sample,
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
