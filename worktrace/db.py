from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Iterable, Mapping

from . import config
from .constants import (
    DEFAULT_CONTEXT_CARRY_MINUTES,
    DEFAULT_IDLE_THRESHOLD_SECONDS,
    DEFAULT_UNRECORDED_GAP_BOUNDARY_SECONDS,
    EXCLUDED_PROJECT,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from .report_structure_generation import bump_generation
from .schema_migrations import MIN_SUPPORTED_SCHEMA_VERSION, migrate_schema
from .write_gate import DATABASE_WRITE_GATE

CURRENT_SCHEMA_VERSION = 7

_RETIRED_SCHEMA_TRIGGERS = (
    "close_existing_open_activity_before_insert",
    "reset_empty_active_folder_generation",
    "normalize_pending_folder_generation",
    "cleanup_history_jobs_after_project_reset",
)
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
_REPORT_STRUCTURE_TABLES = {
    "ACTIVITY_LOG",
    "ACTIVITY_PROJECT_ASSIGNMENT",
    "ACTIVITY_RESOURCE",
    "ACTIVITY_CLIPBOARD_EVENT",
    "SESSION_BOUNDARY",
    "REPORT_SESSION_OPERATION",
    "REPORT_SESSION_OPERATION_MEMBER",
    "PROJECT",
}
_REPORT_STRUCTURE_SETTINGS = {
    "context_carry_minutes",
    "unrecorded_gap_boundary_seconds",
}
_REPORT_STRUCTURE_NONE = 0
_REPORT_STRUCTURE_ALWAYS = 1
_REPORT_STRUCTURE_SETTINGS_PARAMETERS = 2
_ACTIVITY_LOG_UPDATE_RE = re.compile(
    r"\bUPDATE\s+(?:[A-Z0-9_]+\.)?ACTIVITY_LOG\s+SET\s+(.*?)(?:\s+WHERE\s+|$)",
    re.IGNORECASE | re.DOTALL,
)


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


def _parameter_values(parameters):
    if isinstance(parameters, Mapping):
        return parameters.values()
    if isinstance(parameters, (tuple, list)):
        return parameters
    return ()


def _parameters_affect_report_structure(parameters) -> bool:
    found_string = False
    for value in _parameter_values(parameters):
        if not isinstance(value, str):
            continue
        found_string = True
        if value in _REPORT_STRUCTURE_SETTINGS:
            return True
    return not found_string


def _activity_log_update_changes_structure(sql: str) -> bool:
    match = _ACTIVITY_LOG_UPDATE_RE.search(sql)
    if match is None:
        return True
    columns: set[str] = set()
    for assignment in match.group(1).split(","):
        left = assignment.split("=", 1)[0].strip().rsplit(".", 1)[-1]
        left = left.strip('"`[] ').upper()
        if left:
            columns.add(left)
    if not columns:
        return True
    return not columns.issubset({"DURATION_SECONDS", "UPDATED_AT"})


@lru_cache(maxsize=1024)
def _classify_report_structure_sql(sql: str) -> int:
    """Classify one SQL template once; parameters are handled separately."""

    text = str(sql or "").strip()
    if not text or not _WRITE_TOKEN_RE.search(text):
        return _REPORT_STRUCTURE_NONE
    upper = " ".join(text.upper().split())

    if upper.startswith(("CREATE ", "DROP ", "ALTER ")):
        if "SETTINGS" in upper or any(
            re.search(rf"\b{table}\b", upper)
            for table in _REPORT_STRUCTURE_TABLES
        ):
            return _REPORT_STRUCTURE_ALWAYS
        return _REPORT_STRUCTURE_NONE

    if re.search(r"\bACTIVITY_LOG\b", upper):
        if upper.startswith("UPDATE") and not _activity_log_update_changes_structure(
            text
        ):
            return _REPORT_STRUCTURE_NONE
        return _REPORT_STRUCTURE_ALWAYS

    if re.search(r"\bSETTINGS\b", upper):
        if upper.startswith("DELETE"):
            return _REPORT_STRUCTURE_ALWAYS
        return _REPORT_STRUCTURE_SETTINGS_PARAMETERS

    if any(
        re.search(rf"\b{table}\b", upper)
        for table in _REPORT_STRUCTURE_TABLES
    ):
        return _REPORT_STRUCTURE_ALWAYS
    return _REPORT_STRUCTURE_NONE


def _sql_affects_report_structure(sql: str, parameters=()) -> bool:
    classification = _classify_report_structure_sql(str(sql))
    if classification == _REPORT_STRUCTURE_ALWAYS:
        return True
    if classification == _REPORT_STRUCTURE_SETTINGS_PARAMETERS:
        return _parameters_affect_report_structure(parameters)
    return False


class WorkTraceConnection(sqlite3.Connection):
    """SQLite connection enforcing write exclusion and structural generations."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._report_structure_dirty = False
        self._report_structure_database_key = ""

    def _require_write_allowed(self, sql: str) -> None:
        if _sql_requires_write_gate(sql):
            DATABASE_WRITE_GATE.require_current_thread_allowed()

    def _mark_report_structure_dirty(
        self,
        sql: str,
        parameters=(),
        *,
        rowcount: int | None = None,
    ) -> None:
        if rowcount == 0 or self._report_structure_dirty:
            return
        if _sql_affects_report_structure(sql, parameters):
            self._report_structure_dirty = True

    def _persist_report_structure_generation(self) -> None:
        """Increment the durable generation inside the pending write transaction."""

        if not self._report_structure_dirty:
            return
        try:
            super().execute(
                """
                UPDATE report_structure_revision_state
                SET generation = generation + 1
                WHERE singleton_id = 1
                """
            )
        except sqlite3.OperationalError as exc:
            # Supported pre-v7 schemas may be assembled and committed before
            # migrate_schema() installs the internal revision table.
            if "no such table" not in str(exc).lower():
                raise

    def _publish_report_structure_generation(self) -> None:
        if not self._report_structure_dirty:
            return
        key = str(self._report_structure_database_key or "")
        self._report_structure_dirty = False
        if key:
            bump_generation(key)

    def _discard_report_structure_generation(self) -> None:
        self._report_structure_dirty = False

    def execute(self, sql, parameters=(), /):  # type: ignore[override]
        text = str(sql)
        self._require_write_allowed(text)
        cursor = super().execute(sql, parameters)
        if _sql_records_business_read(text):
            DATABASE_WRITE_GATE.note_current_thread_read()
        else:
            self._mark_report_structure_dirty(
                text,
                parameters,
                rowcount=cursor.rowcount,
            )
        return cursor

    def executemany(self, sql, seq_of_parameters, /):  # type: ignore[override]
        text = str(sql)
        self._require_write_allowed(text)
        if self._report_structure_dirty:
            return super().executemany(sql, seq_of_parameters)

        classification = _classify_report_structure_sql(text)
        if classification == _REPORT_STRUCTURE_NONE:
            return super().executemany(sql, seq_of_parameters)

        if classification == _REPORT_STRUCTURE_ALWAYS:
            cursor = super().executemany(sql, seq_of_parameters)
            if cursor.rowcount != 0:
                self._report_structure_dirty = True
            return cursor

        affects_structure = False

        def tracked_parameters():
            nonlocal affects_structure
            for parameters in seq_of_parameters:
                if (
                    not affects_structure
                    and _parameters_affect_report_structure(parameters)
                ):
                    affects_structure = True
                yield parameters

        cursor = super().executemany(sql, tracked_parameters())
        if cursor.rowcount != 0 and affects_structure:
            self._report_structure_dirty = True
        return cursor

    def executescript(self, sql_script, /):  # type: ignore[override]
        text = str(sql_script)
        self._require_write_allowed(text)
        cursor = super().executescript(sql_script)
        self._mark_report_structure_dirty(text, rowcount=cursor.rowcount)
        return cursor

    def commit(self) -> None:  # type: ignore[override]
        try:
            self._persist_report_structure_generation()
            super().commit()
        except Exception:
            self._discard_report_structure_generation()
            raise
        self._publish_report_structure_generation()

    def rollback(self) -> None:  # type: ignore[override]
        super().rollback()
        self._discard_report_structure_generation()

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if exc_type is None:
                self._persist_report_structure_generation()
            result = super().__exit__(exc_type, exc_value, traceback)
        except Exception:
            self._discard_report_structure_generation()
            raise
        if exc_type is None:
            self._publish_report_structure_generation()
        else:
            self._discard_report_structure_generation()
        return result


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
    if isinstance(conn, WorkTraceConnection):
        conn._report_structure_database_key = get_db_key()
    apply_connection_pragmas(conn)
    return conn


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
        ensure_report_structure_revision_state(conn)
        _require_current_schema_fingerprint(conn)
        seed_defaults(conn)
        return

    if version < MIN_SUPPORTED_SCHEMA_VERSION or version > CURRENT_SCHEMA_VERSION:
        raise ValueError("database_schema_incompatible")
    migrated = False
    if version < CURRENT_SCHEMA_VERSION:
        _require_supported_source_schema(conn, version)
        version = migrate_schema(
            conn,
            current_version=version,
            target_version=CURRENT_SCHEMA_VERSION,
        )
        migrated = True
    if version != CURRENT_SCHEMA_VERSION:
        raise ValueError("database_schema_incompatible")

    # Same-version maintenance accepts only the explicitly retired triggers.
    # Arbitrary malformed current-version schemas fail the fingerprint before
    # index DDL can obscure the compatibility error.
    drop_retired_schema_triggers(conn)
    if migrated:
        ensure_current_indexes(conn)
    _require_current_schema_fingerprint(conn)
    ensure_report_structure_revision_state(conn)
    seed_defaults(conn)


def _require_supported_source_schema(
    conn: sqlite3.Connection,
    version: int,
) -> None:
    """Validate a supported structural boundary before migration."""

    if version not in {4, 5, 6}:
        raise ValueError("database_schema_incompatible")
    required = {
        "project": {"id", "name", "is_deleted"},
        "settings": {"key", "value"},
        "activity_log": {"id", "start_time", "end_time", "duration_seconds"},
        "folder_project_rule": {"id", "project_id"},
        "folder_rule_index_state": {"folder_rule_id", "status", "valid_from"},
        "folder_rule_file_index": {
            "id",
            "folder_rule_id",
            "normalized_path_key",
        },
        "activity_project_assignment": {"activity_id", "project_id"},
        "report_session_operation": {"id", "report_date", "sequence"},
        "report_session_operation_member": {"operation_id", "activity_id"},
        "report_mutation_request": {"request_id", "result_json"},
        "activity_resource": {"activity_id", "identity_key"},
    }
    for table, columns in required.items():
        if not columns.issubset(_table_columns(conn, table)):
            raise ValueError("database_schema_incompatible")


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


def ensure_report_structure_revision_state(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO report_structure_revision_state(singleton_id, generation)
        VALUES (1, 0)
        ON CONFLICT(singleton_id) DO NOTHING
        """
    )


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
        "first_run_notice_accepted": "false",
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


def reset_database() -> None:
    with get_connection() as conn:
        ensure_wal(conn)
        drop_all_tables(conn)
        apply_current_schema(conn)


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


def drop_retired_schema_triggers(conn: sqlite3.Connection) -> None:
    """Remove only the explicit legacy triggers accepted at this version."""

    for trigger_name in _RETIRED_SCHEMA_TRIGGERS:
        conn.execute(f'DROP TRIGGER IF EXISTS "{trigger_name}"')


def ensure_current_indexes(conn: sqlite3.Connection) -> None:
    """Install current indexes after trusted creation or migration."""

    drop_retired_schema_triggers(conn)
    conn.executescript(read_schema_indexes_sql())


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
    )


def _table_columns(conn: sqlite3.Connection, name: str) -> set[str]:
    if not _table_exists(conn, name):
        return set()
    return {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({name})").fetchall()
    }


def drop_all_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS activity_resource;
        DROP TABLE IF EXISTS folder_rule_file_index;
        DROP TABLE IF EXISTS folder_rule_index_state;
        DROP TABLE IF EXISTS history_mutation_job_rule;
        DROP TABLE IF EXISTS history_mutation_job;
        DROP TABLE IF EXISTS report_session_operation_member;
        DROP TABLE IF EXISTS report_mutation_request;
        DROP TABLE IF EXISTS report_session_operation;
        DROP TABLE IF EXISTS activity_clipboard_event;
        DROP TABLE IF EXISTS activity_project_assignment;
        DROP TABLE IF EXISTS activity_log;
        DROP TABLE IF EXISTS session_boundary;
        DROP TABLE IF EXISTS folder_project_rule;
        DROP TABLE IF EXISTS project_rule;
        DROP TABLE IF EXISTS project;
        DROP TABLE IF EXISTS settings;
        DROP TABLE IF EXISTS report_structure_revision_state;
        """
    )
