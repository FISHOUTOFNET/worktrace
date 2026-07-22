"""Crash-safe durable fail-closed seal owned exclusively by maintenance."""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..atomic_file import atomic_write_text
from ..db import get_db_path
from .settings_service import get_bool_setting, get_setting, set_settings

_MARKER_VERSION = 1
_MARKER_NAME = "maintenance-recovery.json"
_STATE_ARMED = "armed"
_STATE_BLOCKED = "blocked"
_VALID_STATES = frozenset({_STATE_ARMED, _STATE_BLOCKED})

_SENSITIVE_STAGING_DIR_NAME = "sensitive-staging"
_SENSITIVE_STAGING_PREFIX = "worktrace-import-"
_SENSITIVE_STAGING_SUFFIX = ".sqlite"
_SENSITIVE_STAGING_RESIDUE_REASON = "maintenance_sensitive_staging_cleanup_required"

_ACTIVE_SENSITIVE_STAGING: set[Path] = set()
_ACTIVE_SENSITIVE_STAGING_LOCK = threading.Lock()


class MaintenanceRecoverySealError(RuntimeError):
    """The durable recovery seal could not be verified or transitioned."""


@dataclass(frozen=True)
class MaintenanceRecoveryLatch:
    blocked: bool
    reason: str | None
    epoch: str | None = None
    state: str | None = None
    marker_present: bool = False
    database_mirror_present: bool = False
    sensitive_residue_present: bool = False


def marker_path() -> Path:
    """Keep the recovery seal beside, but outside, the replaceable database."""

    return get_db_path().with_name(_MARKER_NAME)


def sensitive_staging_directory() -> Path:
    """Dedicated directory for decrypted backup staging beside the database."""

    return get_db_path().with_name(_SENSITIVE_STAGING_DIR_NAME)


def _sensitive_staging_residue_paths() -> list[Path]:
    """Return staging files not currently owned by any active process."""

    directory = sensitive_staging_directory()
    if not directory.exists():
        return []
    with _ACTIVE_SENSITIVE_STAGING_LOCK:
        active = {Path(path).resolve() for path in _ACTIVE_SENSITIVE_STAGING}
    residue: list[Path] = []
    for entry in directory.iterdir():
        if not entry.is_file():
            continue
        if not entry.name.startswith(_SENSITIVE_STAGING_PREFIX):
            continue
        if not entry.name.endswith(_SENSITIVE_STAGING_SUFFIX):
            continue
        if entry.resolve() in active:
            continue
        residue.append(entry)
    return residue


def has_sensitive_staging_residue() -> bool:
    """Return True if any unowned sensitive staging file remains on disk."""

    return bool(_sensitive_staging_residue_paths())


def register_active_sensitive_staging(path: Path) -> None:
    """Track a staging file as actively owned by this process."""

    with _ACTIVE_SENSITIVE_STAGING_LOCK:
        _ACTIVE_SENSITIVE_STAGING.add(Path(path).resolve())


def unregister_active_sensitive_staging(path: Path) -> None:
    """Release a staging file so it can be detected as residue if it remains."""

    with _ACTIVE_SENSITIVE_STAGING_LOCK:
        _ACTIVE_SENSITIVE_STAGING.discard(Path(path).resolve())


def clear_sensitive_staging_residue() -> bool:
    """Delete all residue staging files. Return True if all were removed."""

    residue = _sensitive_staging_residue_paths()
    cleared = True
    for entry in residue:
        try:
            entry.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            logging.warning(
                "sensitive staging residue cleanup failed exception=%s",
                type(exc).__name__,
            )
            cleared = False
    return cleared


def _normalized_reason(reason: str) -> str:
    normalized = str(reason or "").strip()
    if not normalized:
        raise ValueError("maintenance_recovery_reason_required")
    return normalized


def _payload(*, epoch: str, reason: str, state: str) -> str:
    return json.dumps(
        {
            "version": _MARKER_VERSION,
            "epoch": epoch,
            "state": state,
            "reason": reason,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _read_marker() -> tuple[str, str, str] | None:
    path = marker_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise MaintenanceRecoverySealError(
            "maintenance_recovery_marker_unreadable"
        ) from exc
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise MaintenanceRecoverySealError(
            "maintenance_recovery_marker_invalid"
        ) from exc
    if not isinstance(data, dict) or data.get("version") != _MARKER_VERSION:
        raise MaintenanceRecoverySealError("maintenance_recovery_marker_invalid")
    epoch = str(data.get("epoch") or "").strip()
    state = str(data.get("state") or "").strip()
    reason = str(data.get("reason") or "").strip()
    if not epoch or state not in _VALID_STATES or not reason:
        raise MaintenanceRecoverySealError("maintenance_recovery_marker_invalid")
    return epoch, state, reason


def _read_database_mirror() -> tuple[bool, str | None]:
    blocked = get_bool_setting("maintenance_fail_closed", False)
    reason = str(get_setting("maintenance_fail_closed_reason", "") or "").strip()
    return blocked, reason or None


def read_latch() -> MaintenanceRecoveryLatch:
    """Merge the sidecar authority with the SQLite diagnostic mirror.

    All three durable evidence fields (``marker_present``,
    ``database_mirror_present``, ``sensitive_residue_present``) are read
    independently before constructing the result. An invalid marker still
    fails closed, but the database mirror and residue evidence are reported
    accurately so diagnostics reflect the full durable state.
    """

    sensitive_residue = has_sensitive_staging_residue()

    marker: tuple[str, str, str] | None = None
    marker_error: str | None = None
    try:
        marker = _read_marker()
    except MaintenanceRecoverySealError as exc:
        marker_error = str(exc)

    database_blocked = False
    database_reason: str | None = None
    database_read_failed = False
    try:
        database_blocked, database_reason = _read_database_mirror()
    except Exception:
        database_read_failed = True

    # Invalid marker: fail closed with accurate mirror/residue evidence.
    if marker_error is not None:
        return MaintenanceRecoveryLatch(
            blocked=True,
            reason=marker_error,
            state="invalid",
            marker_present=True,
            database_mirror_present=database_blocked,
            sensitive_residue_present=sensitive_residue,
        )

    # Valid marker: authority for epoch/state/reason; mirror is diagnostic.
    if marker is not None:
        epoch, state, reason = marker
        return MaintenanceRecoveryLatch(
            blocked=True,
            reason=reason,
            epoch=epoch,
            state=state,
            marker_present=True,
            database_mirror_present=database_blocked,
            sensitive_residue_present=sensitive_residue,
        )

    # No marker. An unreadable mirror cannot prove safety: fail closed.
    if database_read_failed:
        return MaintenanceRecoveryLatch(
            blocked=True,
            reason=(
                _SENSITIVE_STAGING_RESIDUE_REASON
                if sensitive_residue
                else "maintenance_recovery_state_unavailable"
            ),
            state="unavailable",
            sensitive_residue_present=sensitive_residue,
        )

    if database_blocked or sensitive_residue:
        reason = database_reason or (
            _SENSITIVE_STAGING_RESIDUE_REASON if sensitive_residue else None
        )
        return MaintenanceRecoveryLatch(
            blocked=True,
            reason=reason,
            state=_STATE_BLOCKED,
            marker_present=False,
            database_mirror_present=database_blocked,
            sensitive_residue_present=sensitive_residue,
        )
    return MaintenanceRecoveryLatch(
        blocked=False,
        reason=None,
        state=None,
        marker_present=False,
        database_mirror_present=False,
        sensitive_residue_present=False,
    )


def arm_recovery(reason: str) -> MaintenanceRecoveryLatch:
    """Persist proof of an unfinished maintenance epoch before risky work."""

    normalized = _normalized_reason(reason)
    existing = _read_marker()
    if existing is not None:
        raise MaintenanceRecoverySealError("maintenance_recovery_epoch_active")
    epoch = uuid.uuid4().hex
    atomic_write_text(
        marker_path(),
        _payload(epoch=epoch, reason=normalized, state=_STATE_ARMED),
        resource="maintenance_recovery_seal",
        permissions=0o600,
    )
    return MaintenanceRecoveryLatch(
        blocked=True,
        reason=normalized,
        epoch=epoch,
        state=_STATE_ARMED,
        marker_present=True,
    )


def persist_fail_closed(
    reason: str,
    *,
    expected_epoch: str | None = None,
) -> MaintenanceRecoveryLatch:
    """Make the sidecar authoritative before attempting the SQLite mirror."""

    normalized = _normalized_reason(reason)
    marker = _read_marker()
    if marker is None:
        if expected_epoch is not None:
            raise MaintenanceRecoverySealError("maintenance_recovery_epoch_missing")
        epoch = uuid.uuid4().hex
    else:
        epoch, _state, _old_reason = marker
        if expected_epoch is not None and epoch != str(expected_epoch):
            raise MaintenanceRecoverySealError("maintenance_recovery_epoch_mismatch")
    atomic_write_text(
        marker_path(),
        _payload(epoch=epoch, reason=normalized, state=_STATE_BLOCKED),
        resource="maintenance_recovery_seal",
        permissions=0o600,
    )
    # This mirror is diagnostic and query-friendly. Failure is surfaced, but the
    # sidecar already guarantees that a later process remains blocked.
    set_settings(
        {
            "maintenance_fail_closed": "true",
            "maintenance_fail_closed_reason": normalized,
            "user_paused": "true",
            "collector_status": "paused",
        }
    )
    return MaintenanceRecoveryLatch(
        blocked=True,
        reason=normalized,
        epoch=epoch,
        state=_STATE_BLOCKED,
        marker_present=True,
        database_mirror_present=True,
    )


def ensure_fail_closed_evidence(reason: str) -> MaintenanceRecoveryLatch:
    """Re-establish durable fail-closed evidence if none remains on disk.

    Called only after a strict ``persist_fail_closed``/``clear_latch`` failure
    when the coordinator cannot prove the expected epoch is still durable. If
    any durable blocking evidence already exists (valid/invalid marker, SQLite
    mirror, or sensitive staging residue) the current latch is returned
    unchanged so existing epochs are never overwritten. Otherwise a fresh
    blocked marker with a new epoch is created and the SQLite mirror is
    restored. Raises ``MaintenanceRecoverySealError`` if no durable evidence
    can be established.
    """

    latch = read_latch()
    if latch.blocked:
        return latch
    normalized = _normalized_reason(reason)
    epoch = uuid.uuid4().hex
    atomic_write_text(
        marker_path(),
        _payload(epoch=epoch, reason=normalized, state=_STATE_BLOCKED),
        resource="maintenance_recovery_seal",
        permissions=0o600,
    )
    set_settings(
        {
            "maintenance_fail_closed": "true",
            "maintenance_fail_closed_reason": normalized,
            "user_paused": "true",
            "collector_status": "paused",
        }
    )
    return MaintenanceRecoveryLatch(
        blocked=True,
        reason=normalized,
        epoch=epoch,
        state=_STATE_BLOCKED,
        marker_present=True,
        database_mirror_present=True,
    )


def seal_legacy_latch(reason: str) -> MaintenanceRecoveryLatch:
    """Give a database-only blocked state an epoch before explicit recovery."""

    try:
        marker = _read_marker()
    except MaintenanceRecoverySealError:
        # An invalid marker is durable proof of a blocked state but cannot be
        # trusted for epoch verification. Explicit recovery may safely remove
        # it and persist a fresh blocked epoch.
        try:
            marker_path().unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise MaintenanceRecoverySealError(
                "maintenance_recovery_marker_cleanup_failed"
            ) from exc
        return persist_fail_closed(reason)

    if marker is not None:
        epoch, state, marker_reason = marker
        return MaintenanceRecoveryLatch(
            blocked=True,
            reason=marker_reason,
            epoch=epoch,
            state=state,
            marker_present=True,
        )
    return persist_fail_closed(reason)


def clear_latch(*, expected_epoch: str) -> None:
    """Clear the DB mirror first and delete the exact sidecar epoch last."""

    expected = str(expected_epoch or "").strip()
    if not expected:
        raise MaintenanceRecoverySealError("maintenance_recovery_epoch_required")
    marker = _read_marker()
    if marker is None:
        raise MaintenanceRecoverySealError("maintenance_recovery_epoch_missing")
    epoch, _state, _reason = marker
    if epoch != expected:
        raise MaintenanceRecoverySealError("maintenance_recovery_epoch_mismatch")

    set_settings(
        {
            "maintenance_fail_closed": "false",
            "maintenance_fail_closed_reason": "",
        }
    )
    try:
        marker_path().unlink()
    except FileNotFoundError as exc:
        # Losing the marker between verification and deletion means this clear
        # did not prove that it removed the expected epoch.
        raise MaintenanceRecoverySealError(
            "maintenance_recovery_epoch_missing"
        ) from exc
    except OSError as exc:
        raise MaintenanceRecoverySealError(
            "maintenance_recovery_marker_cleanup_failed"
        ) from exc


def reset_for_tests() -> None:
    """Test-only best-effort cleanup; production recovery never calls this."""

    try:
        marker_path().unlink()
    except FileNotFoundError:
        pass
    with _ACTIVE_SENSITIVE_STAGING_LOCK:
        _ACTIVE_SENSITIVE_STAGING.clear()


__all__ = [
    "MaintenanceRecoveryLatch",
    "MaintenanceRecoverySealError",
    "arm_recovery",
    "clear_latch",
    "clear_sensitive_staging_residue",
    "ensure_fail_closed_evidence",
    "has_sensitive_staging_residue",
    "marker_path",
    "persist_fail_closed",
    "read_latch",
    "register_active_sensitive_staging",
    "reset_for_tests",
    "seal_legacy_latch",
    "sensitive_staging_directory",
    "unregister_active_sensitive_staging",
]
