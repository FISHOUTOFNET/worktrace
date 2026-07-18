"""Process-local owner for transient current-activity display state.

Runtime activity state is deliberately kept out of SQLite. Durable activity
facts live in ``activity_log``; this module owns only one typed, display-safe
in-process sample namespaced by the configured database path.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import logging
import threading
from typing import Any, Iterator, Mapping

from ..db import get_db_key


@dataclass(frozen=True)
class RuntimeActivitySample:
    """One atomic, detached read of the current runtime activity state."""

    snapshot: dict[str, Any] | None
    revision: int


_LOCK = threading.RLock()
_SNAPSHOTS: dict[str, dict[str, Any] | None] = {}
_REVISIONS: dict[str, int] = {}
_BOUND_SAMPLE: ContextVar[tuple[str, RuntimeActivitySample] | None] = ContextVar(
    "worktrace_bound_runtime_activity_sample",
    default=None,
)


def _key(database_key: str | None = None) -> str:
    return str(database_key or get_db_key())


def _bump_locked(database_key: str) -> int:
    revision = int(_REVISIONS.get(database_key, 0)) + 1
    _REVISIONS[database_key] = revision
    return revision


@contextmanager
def bind_runtime_activity_sample(
    sample: RuntimeActivitySample,
    *,
    database_key: str | None = None,
) -> Iterator[None]:
    """Freeze one runtime sample for the duration of an explicit API request."""

    key = _key(database_key)
    detached = RuntimeActivitySample(
        snapshot=deepcopy(sample.snapshot) if sample.snapshot is not None else None,
        revision=int(sample.revision),
    )
    token = _BOUND_SAMPLE.set((key, detached))
    try:
        yield
    finally:
        _BOUND_SAMPLE.reset(token)


def publish_runtime_activity_snapshot(
    snapshot: Mapping[str, Any] | None,
    reason: str = "runtime_publish",
    *,
    database_key: str | None = None,
) -> int:
    """Publish a typed display-safe snapshot and return its local revision."""

    key = _key(database_key)
    detached = deepcopy(dict(snapshot)) if snapshot is not None else None
    with _LOCK:
        _SNAPSHOTS[key] = detached
        revision = _bump_locked(key)
    logging.debug(
        "runtime activity snapshot published reason=%s present=%s revision=%d",
        reason,
        detached is not None,
        revision,
    )
    return revision


def sample_runtime_activity_state(
    *, database_key: str | None = None
) -> RuntimeActivitySample:
    """Return one atomic detached sample for a page/API request."""

    key = _key(database_key)
    bound = _BOUND_SAMPLE.get()
    if bound is not None and bound[0] == key:
        sample = bound[1]
        return RuntimeActivitySample(
            snapshot=deepcopy(sample.snapshot) if sample.snapshot is not None else None,
            revision=int(sample.revision),
        )
    with _LOCK:
        snapshot = _SNAPSHOTS.get(key)
        return RuntimeActivitySample(
            snapshot=deepcopy(snapshot) if snapshot is not None else None,
            revision=int(_REVISIONS.get(key, 0)),
        )


def get_runtime_activity_snapshot(
    *, database_key: str | None = None
) -> dict[str, Any] | None:
    return sample_runtime_activity_state(database_key=database_key).snapshot


def clear_runtime_activity_state(
    reason: str,
    *,
    clear_snapshot: bool = True,
    clear_ownership: bool = True,
    database_key: str | None = None,
) -> None:
    """Clear transient state idempotently without touching durable history."""

    key = _key(database_key)
    changed = False
    with _LOCK:
        if clear_snapshot:
            changed = _SNAPSHOTS.get(key) is not None
            _SNAPSHOTS[key] = None
        if changed or clear_ownership:
            _bump_locked(key)
    logging.info(
        "runtime activity state cleared reason=%s snapshot=%s ownership=%s",
        reason,
        bool(clear_snapshot),
        bool(clear_ownership),
    )


__all__ = [
    "RuntimeActivitySample",
    "bind_runtime_activity_sample",
    "clear_runtime_activity_state",
    "get_runtime_activity_snapshot",
    "publish_runtime_activity_snapshot",
    "sample_runtime_activity_state",
]
