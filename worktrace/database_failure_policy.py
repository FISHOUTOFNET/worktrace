"""Shared classification for transient database infrastructure failures."""

from __future__ import annotations

import sqlite3
from enum import StrEnum

from .write_gate import DATABASE_MAINTENANCE_ERROR, DATABASE_RECOVERY_ERROR


class DatabaseFailureKind(StrEnum):
    BUSY = "database_busy"
    MAINTENANCE = DATABASE_MAINTENANCE_ERROR
    GENERATION_CHANGED = "database_generation_changed"
    RECOVERY_REQUIRED = DATABASE_RECOVERY_ERROR


def classify_database_failure(
    exc: BaseException,
) -> DatabaseFailureKind | None:
    """Return a stable infrastructure failure kind, or ``None`` for domain errors."""

    if not isinstance(exc, sqlite3.Error):
        return None
    message = str(exc).strip().lower()
    sqlite_code = getattr(exc, "sqlite_errorcode", None)
    sqlite_name = str(getattr(exc, "sqlite_errorname", "") or "").upper()
    try:
        primary_code = int(sqlite_code) & 0xFF
    except (TypeError, ValueError):
        primary_code = None

    if (
        primary_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
        or sqlite_name.startswith("SQLITE_BUSY")
        or sqlite_name.startswith("SQLITE_LOCKED")
        or message in {
            "database is locked",
            "database table is locked",
            "database is busy",
        }
    ):
        return DatabaseFailureKind.BUSY
    if message == DATABASE_MAINTENANCE_ERROR:
        return DatabaseFailureKind.MAINTENANCE
    if message == "database_generation_changed":
        return DatabaseFailureKind.GENERATION_CHANGED
    if message == DATABASE_RECOVERY_ERROR:
        return DatabaseFailureKind.RECOVERY_REQUIRED
    return None


__all__ = ["DatabaseFailureKind", "classify_database_failure"]
