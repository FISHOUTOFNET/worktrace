from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Iterable

from . import config
from .constants import (
    DEFAULT_CONTEXT_CARRY_MINUTES,
    DEFAULT_IDLE_THRESHOLD_SECONDS,
    DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    EXCLUDED_PROJECT,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from .data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from .write_gate import DATABASE_WRITE_GATE

CURRENT_SCHEMA_VERSION = 13

_WRITE_TOKEN_RE = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|REPLACE|CREATE|DROP|ALTER|VACUUM|REINDEX|ATTACH|DETACH)\b",
    re.IGNORECASE,
)
_DB_MUTATING_PRAGMAS = {
    "APPLICATION_ID",
    "AUTO_VACUUM",
    "JOURNAL_MODE",
    "PAGE_SIZE",
    "USER_VERSION",
}


def _pragma_name(upper_sql: str) -> str:
    value = upper_sql.removeprefix("PRAGMA").strip()
    value = value.split("=", 1)[0].split("(", 1)[0].strip()
    if "." in value:
        value = value.rsplit(".", 1)[-1]
    return value.split()[0] if value else ""


@lru_cache(maxsize=1024)
def _sql_requires_write_gate(sql: str) -> bool:
    text = str(sql or "").strip()
    if not text:
        return False
    upper = text.upper()
    if upper.startswith("BEGIN IMMEDIATE") or upper.startswith("BEGIN EXCLUSIVE"):
        return True
    if upper.startswith("PRAGMA"):
        pragma = _pragma_name(upper)
        return pragma in _DB_MUTATING_PRAGMAS and (
            "=" in text or pragma == "JOURNAL_MODE"
        )
    return bool(_WRITE_TOKEN_RE.search(text))


def _sql_records_business_read(sql: str) -> bool:
    upper = str(sql or "").lstrip().upper()
    return (
        upper.startswith("SELECT")
        or upper.startswith("WITH")
        or upper.startswith("EXPLAIN")
    )


class WorkTraceConnection(sqlite3.Connection):
    """SQLite infrastructure enforcing write exclusion and read observation."""

    def _require_write_allowed(self, sql: str) -> None:
        if _sql_requires_write_gate(sql):
            DATABASE_WRITE_GATE.require_current_thread_allowed(sql)

    def execute(self, sql, parameters=(), /):  # type: ignore[override]
        text = str(sql)
        self._require_write_allowed(text)
        cursor = super().execute(sql, parameters)
        if _sql_records_business_read(text):
            DATABASE_WRITE_GATE.note_current_thread_read()
        return cursor

    def executemany(self, sql, seq_of_parameters, /):  # type: ignore[override]
        text = str(sql)
        self._require_write_allowed(text)
        return super().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script, /):  # type: ignore[override]
        text = str(sql_script)
        self._require_write_allowed(text)
        return super().executescript(sql_script)


@lru_cache(maxsize=1)
def read_schema_sql() -> str:
    return resources.files(__package__).joinpath("schema.sql").read_text(
        encoding="utf-8"
    )


@lru_cache(maxsize=1)
def read_internal_schema_sql() -> str:
    return resources.files(__package__).joinpath("schema_internal.sql").read_text(
        encoding="utf-8"
    )


@lru_cache(maxsize=1)
def read_schema_indexes_sql() -> str:
    return resources.files(__package__).joinpath("schema_indexes.sql").read_text(
        encoding="utf-8"
    )


_db_path: Path | None = None
_db_key: str | None = None


def now_str() -> str:
    from datetime import datetime

    return datetime.now().strftime(TIME_FORMAT)


def configure_database(path: str | Path | None = None) -> Path:
    global _db_path, _db_key
    database_path = Path(path) if path is not None else config.resolve_paths().db_path
    database_path.parent.mkdir(parents=True, exist_ok=True)
    _db_path = database_path
    _db_key = str(database_path.resolve())
    return database_path


def get_db_path() -> Path:
    global _db_path
    if _db_path is None:
        configure_database()
    assert _db_path is not None
    return _db_path


def get_db_key() -> str:
    global _db_key
    if _db_key is None:
        configure_database()
    assert _db_key is not None
    return _db_key


def get_connection() -> sqlite3.Connection:
    database_path = get_db_path()
    conn = sqlite3.connect(
        database_path,
        timeout=5,
        check_same_thread=False,
        factory=WorkTraceConnection,
    )
    conn.row_factory = sqlite3.Row
    apply_connection_pragmas(conn)
    return conn


def active_database_epoch_key() -> tuple[str, int]:
    """Return the process-cache identity for the currently active database."""

    with get_connection() as conn:
        replacement_epoch = DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.DATABASE_REPLACEMENT,
        )
    return get_db_key(), replacement_epoch


def apply_connection_pragmas(conn: sqlite3.Connection) -> None:
    """Apply connection-local settings without taking the database write gate."""

    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA foreign_keys = ON;")


def ensure_wal(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL;")


def dict_rows(rows: Iterable[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def initialize_database(path: str | Path | None = None) -> None:
    configure_database(path)
    with get_connection() as conn:
        ensure_wal(conn)
        apply_current_schema(conn)
    logging.info("database initialized")


def apply_current_schema(conn: sqlite3.Connection) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    has_user_tables = _database_has_user_tables(conn)
    if not has_user_tables:
        conn.executescript(read_schema_sql())
        conn.executescript(read_internal_schema_sql())
        ensure_current_indexes(conn)
        conn.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        ensure_data_generation_state(conn)
        _require_current_schema_fingerprint(conn)
        seed_defaults(conn)
        return

    if version != CURRENT_SCHEMA_VERSION:
        raise ValueError("database_schema_incompatible")

    _require_current_schema_fingerprint(conn)
    ensure_data_generation_state(conn)
    seed_defaults(conn)


def schema_fingerprint(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        """
        SELECT type, name, tbl_name, sql
        FROM sqlite_master
        WHERE name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'trigger', 'view')
        ORDER BY type, name
        """
    ).fetchall()
    canonical = [
        (
            str(row["type"]),
            str(row["name"]),
            str(row["tbl_name"]),
            " ".join(str(row["sql"] or "").split()),
        )
        for row in rows
    ]
    return hashlib.sha256(
        json.dumps(
            canonical,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@lru_cache(maxsize=1)
def expected_schema_fingerprint() -> str:
    reference = sqlite3.connect(":memory:")
    reference.row_factory = sqlite3.Row
    try:
        reference.executescript(read_schema_sql())
        reference.executescript(read_internal_schema_sql())
        reference.executescript(read_schema_indexes_sql())
        return schema_fingerprint(reference)
    finally:
        reference.close()


def _require_current_schema_fingerprint(conn: sqlite3.Connection) -> None:
    if schema_fingerprint(conn) != expected_schema_fingerprint():
        raise ValueError("database_schema_incompatible")


def ensure_data_generation_state(conn: sqlite3.Connection) -> None:
    DataGenerationRepository.ensure_rows(conn)


def seed_defaults(conn: sqlite3.Connection) -> None:
    ts = now_str()
    defaults = {
        "poll_interval_seconds": "1",
        "idle_threshold_seconds": str(DEFAULT_IDLE_THRESHOLD_SECONDS),
        "collector_status": "stopped",
        "collector_health_state": "stopped",
        "collector_last_successful_observation_at": "",
        "collector_last_failure_at": "",
        "collector_consecutive_failures": "0",
        "collector_last_failure_phase": "",
        "collector_last_failure_kind": "",
        "collector_stall_threshold_seconds": "180",
        "clock_jump_threshold_seconds": "300",
        "last_collector_heartbeat": "",
        "last_shutdown_at": "",
        "export_path": str(config.get_default_export_dir().resolve()),
        "ui_refresh_seconds": "10",
        "user_paused": "false",
        "context_carry_minutes": str(DEFAULT_CONTEXT_CARRY_MINUTES),
        "unrecorded_gap_boundary_seconds": str(
            DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS
        ),
        "clipboard_capture_enabled": "false",
    }
    for key, value in defaults.items():
        conn.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, value, ts),
        )
    conn.execute(
        """
        INSERT INTO project(
            name, description, language, is_archived, enabled,
            created_by, created_at, updated_at
        )
        VALUES (?, '', '中文', 0, 1, 'system', ?, ?)
        ON CONFLICT(name) DO NOTHING
        """,
        (UNCATEGORIZED_PROJECT, ts, ts),
    )
    conn.execute(
        """
        INSERT INTO project(
            name, description, language, is_archived, enabled,
            created_by, created_at, updated_at
        )
        VALUES (?, '命中后匿名记录', '中文', 0, 0, 'system', ?, ?)
        ON CONFLICT(name) DO NOTHING
        """,
        (EXCLUDED_PROJECT, ts, ts),
    )


def _database_has_user_tables(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def ensure_current_indexes(conn: sqlite3.Connection) -> None:
    """Install the indexes declared by the current schema contract."""

    conn.executescript(read_schema_indexes_sql())


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "WorkTraceConnection",
    "active_database_epoch_key",
    "apply_connection_pragmas",
    "apply_current_schema",
    "configure_database",
    "dict_rows",
    "ensure_current_indexes",
    "ensure_data_generation_state",
    "ensure_wal",
    "expected_schema_fingerprint",
    "get_connection",
    "get_db_key",
    "get_db_path",
    "initialize_database",
    "now_str",
    "read_internal_schema_sql",
    "read_schema_indexes_sql",
    "read_schema_sql",
    "schema_fingerprint",
    "seed_defaults",
]
