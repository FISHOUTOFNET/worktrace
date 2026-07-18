"""Installation-scoped metadata stored outside the replaceable business database."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from ..db import get_db_path

_PRIVACY_NOTICE_VERSION_KEY = "privacy_notice_version"
_LEGACY_PRIVACY_KEYS = (
    "first_run_notice_accepted",
    "accepted_privacy_notice_version",
)


def metadata_path() -> Path:
    return get_db_path().with_name("installation_metadata.db")


def _connect() -> sqlite3.Connection:
    path = metadata_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS installation_metadata (
            key TEXT PRIMARY KEY CHECK(length(trim(key)) > 0),
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute("PRAGMA user_version = 1")
    return conn


def get_privacy_notice_version() -> str:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value FROM installation_metadata WHERE key = ?",
            (_PRIVACY_NOTICE_VERSION_KEY,),
        ).fetchone()
    return str(row["value"] or "") if row else ""


def set_privacy_notice_version(version: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO installation_metadata(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (
                _PRIVACY_NOTICE_VERSION_KEY,
                str(version or ""),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def migrate_legacy_privacy_state(business_conn: sqlite3.Connection) -> None:
    """Move legacy settings once; an existing installation value always wins."""

    rows = business_conn.execute(
        "SELECT key, value FROM settings WHERE key IN (?, ?)",
        _LEGACY_PRIVACY_KEYS,
    ).fetchall()
    legacy = {str(row["key"]): str(row["value"] or "") for row in rows}
    with _connect() as metadata_conn:
        current = metadata_conn.execute(
            "SELECT value FROM installation_metadata WHERE key = ?",
            (_PRIVACY_NOTICE_VERSION_KEY,),
        ).fetchone()
        if current is None:
            accepted_version = legacy.get("accepted_privacy_notice_version", "")
            legacy_accepted = legacy.get(
                "first_run_notice_accepted", "false"
            ).strip().casefold() == "true"
            if not accepted_version and legacy_accepted:
                accepted_version = "1"
            metadata_conn.execute(
                """
                INSERT INTO installation_metadata(key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                (
                    _PRIVACY_NOTICE_VERSION_KEY,
                    accepted_version,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )
    business_conn.executemany(
        "DELETE FROM settings WHERE key = ?",
        [(key,) for key in _LEGACY_PRIVACY_KEYS],
    )


__all__ = [
    "get_privacy_notice_version",
    "metadata_path",
    "migrate_legacy_privacy_state",
    "set_privacy_notice_version",
]
