"""Process-local owner for transient current-activity display state.

Runtime activity state is deliberately kept out of SQLite. Durable activity
facts live in ``activity_log``; this module owns only the current in-process
sample used by the live display. State is namespaced by the configured database
path so tests and explicit database reconfiguration cannot leak samples across
instances.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import threading
from typing import Any, Mapping

from ..db import get_db_key

CURRENT_ACTIVITY_SNAPSHOT_KEY = "current_activity_snapshot"
PENDING_SHORT_SECONDS_KEY = "pending_short_seconds"
PENDING_CARRY_PROVENANCE_KEY = "pending_short_carry_provenance"


@dataclass(frozen=True)
class RuntimeActivitySample:
    """One atomic, detached read of the current runtime activity state."""

    snapshot: dict[str, Any] | None
    revision: int


_LOCK = threading.RLock()
_SNAPSHOTS: dict[str, dict[str, Any] | None] = {}
_RAW_OVERRIDES: dict[str, str | None] = {}
_REVISIONS: dict[str, int] = {}
_LEGACY_COMPAT_VALUES: dict[tuple[str, str], str] = {}


def _key(database_key: str | None = None) -> str:
    return str(database_key or get_db_key())


def _bump_locked(database_key: str) -> int:
    revision = int(_REVISIONS.get(database_key, 0)) + 1
    _REVISIONS[database_key] = revision
    return revision


def publish_runtime_activity_snapshot(
    snapshot: Mapping[str, Any] | None,
    reason: str = "runtime_publish",
    *,
    database_key: str | None = None,
) -> int:
    """Publish a display-safe snapshot and return its new local revision."""

    key = _key(database_key)
    detached = deepcopy(dict(snapshot)) if snapshot is not None else None
    with _LOCK:
        _SNAPSHOTS[key] = detached
        _RAW_OVERRIDES[key] = None
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


def read_runtime_activity_snapshot_raw(
    *, database_key: str | None = None
) -> str:
    """Compatibility serializer for callers not yet migrated to typed samples."""

    key = _key(database_key)
    with _LOCK:
        raw_override = _RAW_OVERRIDES.get(key)
        if raw_override is not None:
            return raw_override
        snapshot = _SNAPSHOTS.get(key)
        if snapshot is None:
            return ""
        return json.dumps(snapshot, ensure_ascii=False)


def restore_runtime_activity_snapshot(
    snapshot: str | Mapping[str, Any] | None,
    reason: str,
    *,
    database_key: str | None = None,
) -> None:
    """Restore a validated display sample without writing SQLite.

    String input remains supported for test/compatibility callers. Invalid JSON
    is retained only as an in-memory raw override so legacy readers fail closed
    exactly as before; production publishers always provide mappings.
    """

    key = _key(database_key)
    if isinstance(snapshot, Mapping):
        publish_runtime_activity_snapshot(snapshot, reason, database_key=key)
        return
    raw = str(snapshot or "")
    if not raw:
        clear_runtime_activity_state(reason, database_key=key)
        return
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        with _LOCK:
            _SNAPSHOTS[key] = None
            _RAW_OVERRIDES[key] = raw
            _bump_locked(key)
        return
    if isinstance(value, dict):
        publish_runtime_activity_snapshot(value, reason, database_key=key)
        return
    with _LOCK:
        _SNAPSHOTS[key] = None
        _RAW_OVERRIDES[key] = raw
        _bump_locked(key)


def clear_runtime_activity_state(
    reason: str,
    *,
    clear_snapshot: bool = True,
    clear_pending: bool = True,
    clear_ownership: bool = True,
    database_key: str | None = None,
) -> None:
    """Clear transient state idempotently without touching durable history."""

    key = _key(database_key)
    changed = False
    with _LOCK:
        if clear_snapshot:
            changed = (
                _SNAPSHOTS.get(key) is not None
                or _RAW_OVERRIDES.get(key) not in (None, "")
            )
            _SNAPSHOTS[key] = None
            _RAW_OVERRIDES[key] = None
        if clear_pending:
            for legacy_key, default in (
                (PENDING_SHORT_SECONDS_KEY, "0"),
                (PENDING_CARRY_PROVENANCE_KEY, ""),
            ):
                compat_key = (key, legacy_key)
                changed = changed or _LEGACY_COMPAT_VALUES.get(compat_key, default) != default
                _LEGACY_COMPAT_VALUES[compat_key] = default
        if changed or clear_ownership:
            _bump_locked(key)
    logging.info(
        "runtime activity state cleared reason=%s snapshot=%s pending=%s ownership=%s",
        reason,
        bool(clear_snapshot),
        bool(clear_pending),
        bool(clear_ownership),
    )


def get_legacy_runtime_setting(
    name: str,
    default: str | None = None,
    *,
    database_key: str | None = None,
) -> str | None:
    """Temporary non-persistent bridge for removed short-activity settings."""

    key = _key(database_key)
    with _LOCK:
        return _LEGACY_COMPAT_VALUES.get((key, name), default)


def set_legacy_runtime_setting(
    name: str,
    value: str,
    *,
    database_key: str | None = None,
) -> None:
    key = _key(database_key)
    with _LOCK:
        _LEGACY_COMPAT_VALUES[(key, name)] = str(value)


def record_runtime_boundary(
    reason: str,
    *,
    clear_snapshot: bool = True,
    clear_pending: bool = True,
) -> None:
    """Record a durable hard boundary and clear the process-local sample."""

    from . import session_boundary_service

    session_boundary_service.record_hard_boundary(reason=reason)
    clear_runtime_activity_state(
        reason,
        clear_snapshot=clear_snapshot,
        clear_pending=clear_pending,
        clear_ownership=True,
    )


__all__ = [
    "CURRENT_ACTIVITY_SNAPSHOT_KEY",
    "PENDING_CARRY_PROVENANCE_KEY",
    "PENDING_SHORT_SECONDS_KEY",
    "RuntimeActivitySample",
    "clear_runtime_activity_state",
    "get_legacy_runtime_setting",
    "get_runtime_activity_snapshot",
    "publish_runtime_activity_snapshot",
    "read_runtime_activity_snapshot_raw",
    "record_runtime_boundary",
    "restore_runtime_activity_snapshot",
    "sample_runtime_activity_state",
    "set_legacy_runtime_setting",
]
