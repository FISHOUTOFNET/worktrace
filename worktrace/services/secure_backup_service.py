"""Encrypted local backup export/import service.

A replace import is validated in a staging database before the live database is
mutated. The process database write gate is active for the full replacement
window, with the importing thread as the sole writer.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..constants import (
    APP_VERSION,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)
from ..db import (
    CURRENT_SCHEMA_VERSION,
    expected_schema_fingerprint,
    get_connection,
    now_str,
    read_schema_indexes_sql,
    read_schema_sql,
    schema_fingerprint,
    seed_defaults,
)
from ..security.backup_format import (
    BACKUP_VERSION,
    BackupFormatError,
    BackupManifest,
    create_encrypted_backup,
    decrypt_encrypted_backup,
    parse_backup_manifest,
)
from ..write_gate import DATABASE_WRITE_GATE
from .runtime_activity_state_service import clear_runtime_activity_state
from .settings_service import clear_settings_cache, get_bool_setting, get_setting, set_setting


PAYLOAD_FORMAT = "worktrace-local-data"
PAYLOAD_VERSION = 4
SCHEMA_VERSION = str(CURRENT_SCHEMA_VERSION)
BACKUP_FILE_SUFFIX = ".wtbackup"

EXPORT_TABLES: tuple[str, ...] = (
    "project",
    "settings",
    "session_boundary",
    "activity_log",
    "folder_project_rule",
    "project_rule",
    "folder_rule_index_state",
    "activity_project_assignment",
    "activity_clipboard_event",
    "report_session_operation",
    "report_session_operation_member",
    "report_mutation_request",
    "activity_resource",
)
EXCLUDED_TABLES: frozenset[str] = frozenset({"folder_rule_file_index"})
MIGRATABLE_SETTINGS: frozenset[str] = frozenset(
    {
        "poll_interval_seconds",
        "idle_threshold_seconds",
        "ui_refresh_seconds",
        "context_carry_minutes",
        "unrecorded_gap_boundary_seconds",
        "clipboard_capture_enabled",
        "collector_stall_threshold_seconds",
        "clock_jump_threshold_seconds",
    }
)
_DELETE_ORDER: tuple[str, ...] = (
    "activity_resource",
    "report_session_operation_member",
    "report_mutation_request",
    "report_session_operation",
    "activity_clipboard_event",
    "activity_project_assignment",
    "folder_rule_file_index",
    "folder_rule_index_state",
    "project_rule",
    "folder_project_rule",
    "activity_log",
    "session_boundary",
    "settings",
    "project",
)
_ALLOWED_ACTIVITY_STATUSES = {
    STATUS_NORMAL,
    STATUS_IDLE,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_PAUSED,
}


class SecureBackupError(Exception):
    """Base error for encrypted backup operations."""


class BackupDecryptionError(SecureBackupError):
    """Could not decrypt the backup or the passphrase was wrong."""


class BackupCorruptedError(SecureBackupError):
    """The backup file is invalid or corrupted."""


class BackupVersionNotSupportedError(SecureBackupError):
    """The backup version is not supported by this WorkTrace build."""


class BackupImportInProgressError(SecureBackupError):
    """Another secure import is already in progress."""


@dataclass(frozen=True)
class BackupManifestInfo:
    version: int
    app_version: str
    created_at: str
    kdf_algorithm: str
    payload_format: str
    payload_alg: str

    @classmethod
    def from_manifest(cls, manifest: BackupManifest) -> "BackupManifestInfo":
        return cls(
            version=manifest.version,
            app_version=manifest.app_version,
            created_at=manifest.created_at,
            kdf_algorithm=manifest.kdf.algorithm,
            payload_format=manifest.payload_format,
            payload_alg=manifest.payload_alg,
        )


@dataclass(frozen=True)
class ImportResult:
    mode: str
    imported_tables: dict[str, int] = field(default_factory=dict)
    folder_index_reset: bool = False


def export_encrypted_backup(output_path: str | Path, passphrase: str) -> Path:
    if not passphrase:
        raise SecureBackupError("passphrase is required")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = _build_export_payload()
    blob = create_encrypted_backup(payload, passphrase, APP_VERSION)
    _atomic_write_bytes(out, blob)
    logging.info("encrypted backup export success suffix=%s", BACKUP_FILE_SUFFIX)
    return out


def import_encrypted_backup(
    input_path: str | Path,
    passphrase: str,
    mode: str = "replace",
) -> ImportResult:
    if not passphrase:
        raise SecureBackupError("passphrase is required")
    if mode != "replace":
        raise SecureBackupError(f"unsupported import mode: {mode}")

    with SECURE_IMPORT_COORDINATOR.acquire() as guard:
        blob = Path(input_path).read_bytes()
        payload = _read_and_decrypt(blob, passphrase)
        data = _parse_and_validate_payload(payload)
        imported_counts = _replace_import(data)
        guard.mark_succeeded()

    try:
        _invalidate_caches()
    except Exception as exc:
        logging.warning("encrypted backup cache invalidation failed exc_type=%s", type(exc).__name__)
    logging.info("encrypted backup import success mode=%s tables=%d", mode, len(imported_counts))
    return ImportResult(mode=mode, imported_tables=imported_counts, folder_index_reset=True)


def parse_encrypted_backup_manifest(input_path: str | Path) -> BackupManifestInfo:
    blob = Path(input_path).read_bytes()
    try:
        manifest = parse_backup_manifest(blob)
    except BackupFormatError as exc:
        raise _classify_format_error(exc) from exc
    return BackupManifestInfo.from_manifest(manifest)


@dataclass
class _ImportGuardState:
    prior_user_paused: bool
    prior_collector_status: str
    prior_snapshot: str
    succeeded: bool = False

    def mark_succeeded(self) -> None:
        self.succeeded = True


class SecureImportCoordinator:
    """Process-owned import exclusion, acknowledgement and global write gate."""

    def __init__(self) -> None:
        self._import_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._write_gate = False
        self._pause_handler: Any = None

    def register_collector_pause_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._pause_handler = handler

    def clear_collector_pause_handler(self, handler: Any | None = None) -> None:
        with self._state_lock:
            if handler is None or self._pause_handler == handler:
                self._pause_handler = None

    def write_gate_active(self) -> bool:
        with self._state_lock:
            return self._write_gate or DATABASE_WRITE_GATE.active()

    @contextmanager
    def acquire(self) -> Iterator[_ImportGuardState]:
        if not self._import_lock.acquire(blocking=False):
            logging.warning("encrypted backup import rejected: already in progress")
            raise BackupImportInProgressError("another encrypted backup import is already in progress")

        from ..collector.snapshot_publisher import DEFAULT_SNAPSHOT_PUBLISHER

        prior_user_paused = get_bool_setting("user_paused", False)
        prior_collector_status = get_setting("collector_status", "stopped") or "stopped"
        prior_snapshot = DEFAULT_SNAPSHOT_PUBLISHER.read_raw()
        state = _ImportGuardState(prior_user_paused, prior_collector_status, prior_snapshot)
        try:
            with self._state_lock:
                handler = self._pause_handler
            if handler is not None:
                result = handler(timeout_seconds=5.0)
                if not bool(result.get("ok")):
                    raise SecureBackupError("collector_pause_not_acknowledged")

            # Pause/runtime writes occur after collector acknowledgement but
            # before the global gate, so no non-owner writer remains active.
            set_setting("user_paused", "true")
            set_setting("collector_status", "paused")
            clear_runtime_activity_state("secure_import_guard_enter")

            with DATABASE_WRITE_GATE.acquire():
                with self._state_lock:
                    self._write_gate = True
                try:
                    yield state
                except Exception:
                    if not state.succeeded:
                        set_setting("user_paused", "true" if prior_user_paused else "false")
                        set_setting("collector_status", prior_collector_status)
                        DEFAULT_SNAPSHOT_PUBLISHER.restore_raw(prior_snapshot)
                    raise
                else:
                    try:
                        clear_runtime_activity_state("secure_import_success")
                    except Exception as exc:
                        logging.warning(
                            "encrypted backup runtime clear failed exc_type=%s",
                            type(exc).__name__,
                        )
                    logging.info("encrypted backup import guard completed paused=true")
                finally:
                    with self._state_lock:
                        self._write_gate = False
        except Exception as exc:
            logging.warning("encrypted backup import failed exc_type=%s", type(exc).__name__)
            raise
        finally:
            clear_settings_cache()
            self._import_lock.release()


SECURE_IMPORT_COORDINATOR = SecureImportCoordinator()


def register_collector_pause_handler(handler: Any) -> None:
    SECURE_IMPORT_COORDINATOR.register_collector_pause_handler(handler)


def clear_collector_pause_handler(handler: Any | None = None) -> None:
    SECURE_IMPORT_COORDINATOR.clear_collector_pause_handler(handler)


def is_secure_import_in_progress() -> bool:
    return SECURE_IMPORT_COORDINATOR.write_gate_active()


def _build_export_payload() -> bytes:
    tables: dict[str, list[dict[str, Any]]] = {}
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        current_schema_fingerprint = schema_fingerprint(conn)
        if current_schema_fingerprint != expected_schema_fingerprint():
            raise SecureBackupError("database_schema_incompatible")
        for table in EXPORT_TABLES:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            if table == "settings":
                tables[table] = [dict(row) for row in rows if row["key"] in MIGRATABLE_SETTINGS]
            else:
                tables[table] = [dict(row) for row in rows]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    payload_dict = {
        "format": PAYLOAD_FORMAT,
        "version": PAYLOAD_VERSION,
        "created_at": _utc_now(),
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "schema_fingerprint": current_schema_fingerprint,
        "tables": tables,
    }
    return json.dumps(payload_dict, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _parse_and_validate_payload(payload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logging.warning("encrypted backup payload json parse failed: %s", type(exc).__name__)
        raise BackupCorruptedError("backup file is invalid or corrupted") from exc
    if not isinstance(data, dict) or data.get("format") != PAYLOAD_FORMAT:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    if data.get("version") != PAYLOAD_VERSION or str(data.get("schema_version") or "") != SCHEMA_VERSION:
        raise BackupVersionNotSupportedError("backup version is not supported")
    if data.get("schema_fingerprint") != expected_schema_fingerprint():
        raise BackupCorruptedError("backup file is invalid or corrupted")
    tables = data.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(EXPORT_TABLES):
        raise BackupCorruptedError("backup file is invalid or corrupted")
    for rows in tables.values():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BackupCorruptedError("backup file is invalid or corrupted")
    return data


def _replace_import(data: dict[str, Any]) -> dict[str, int]:
    staging_path: str | None = None
    try:
        fd, staging_path = tempfile.mkstemp(prefix="worktrace-import-", suffix=".sqlite")
        os.close(fd)
        staging = sqlite3.connect(staging_path)
        staging.row_factory = sqlite3.Row
        staging.execute("PRAGMA foreign_keys = ON")
        try:
            staging.executescript(read_schema_sql())
            staging.executescript(read_schema_indexes_sql())
            staging.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            imported = _load_import_tables(staging, data["tables"])
            seed_defaults(staging)
            _reset_derived_folder_index(staging)
            _validate_staging_database(staging)
            staging.commit()
        except Exception:
            staging.rollback()
            raise
        finally:
            staging.close()

        with get_connection() as live:
            live.execute("BEGIN IMMEDIATE")
            _delete_all_rows(live)
            source = sqlite3.connect(staging_path)
            source.row_factory = sqlite3.Row
            try:
                for table in EXPORT_TABLES:
                    _insert_rows(live, table, [dict(row) for row in source.execute(f"SELECT * FROM {table}")])
            finally:
                source.close()
            seed_defaults(live)
            _reset_derived_folder_index(live)
            live.execute(
                "UPDATE settings SET value = 'true', updated_at = ? WHERE key = 'user_paused'",
                (now_str(),),
            )
            live.execute(
                "UPDATE settings SET value = 'paused', updated_at = ? WHERE key = 'collector_status'",
                (now_str(),),
            )
            _validate_staging_database(live)
        return imported
    except BackupCorruptedError:
        raise
    except (sqlite3.DatabaseError, ValueError, KeyError, TypeError) as exc:
        raise BackupCorruptedError("backup file is invalid or corrupted") from exc
    finally:
        if staging_path:
            try:
                os.unlink(staging_path)
            except FileNotFoundError:
                pass


def _load_import_tables(conn: sqlite3.Connection, tables: dict[str, Any]) -> dict[str, int]:
    imported: dict[str, int] = {}
    for table in EXPORT_TABLES:
        rows = tables.get(table, [])
        if table == "settings":
            rows = [row for row in rows if row.get("key") in MIGRATABLE_SETTINGS]
        imported[table] = _insert_rows(conn, table, rows)
    return imported


def _reset_derived_folder_index(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM folder_rule_file_index")
    conn.execute(
        """
        UPDATE folder_rule_index_state
        SET status = 'pending', valid_from = NULL, last_indexed_at = NULL,
            last_checked_at = NULL, file_count = 0, error_message = NULL,
            refresh_requested = 1, updated_at = ?
        """,
        (now_str(),),
    )


def _validate_staging_database(conn: sqlite3.Connection) -> None:
    if int(conn.execute("PRAGMA user_version").fetchone()[0] or 0) != CURRENT_SCHEMA_VERSION:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    if schema_fingerprint(conn) != expected_schema_fingerprint():
        raise BackupCorruptedError("backup file is invalid or corrupted")
    if conn.execute("PRAGMA foreign_key_check").fetchone():
        raise BackupCorruptedError("backup file is invalid or corrupted")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or str(integrity[0]).lower() != "ok":
        raise BackupCorruptedError("backup file is invalid or corrupted")
    _validate_activity_rows(conn)
    _validate_operation_graph(conn)
    _validate_replay_records(conn)


def _validate_activity_rows(conn: sqlite3.Connection) -> None:
    for row in conn.execute(
        "SELECT id, start_time, end_time, duration_seconds, status FROM activity_log ORDER BY id"
    ).fetchall():
        try:
            start = datetime.strptime(str(row["start_time"] or ""), TIME_FORMAT)
            end_raw = row["end_time"]
            end = datetime.strptime(str(end_raw), TIME_FORMAT) if end_raw is not None else None
            duration = int(row["duration_seconds"])
        except (TypeError, ValueError) as exc:
            raise BackupCorruptedError("backup file is invalid or corrupted") from exc
        if duration < 0 or str(row["status"] or "") not in _ALLOWED_ACTIVITY_STATUSES:
            raise BackupCorruptedError("backup file is invalid or corrupted")
        if end is not None:
            expected = int((end - start).total_seconds())
            if expected < 0 or duration != expected:
                raise BackupCorruptedError("backup file is invalid or corrupted")


def _validate_replay_records(conn: sqlite3.Connection) -> None:
    from .report_projection_snapshot_service import build_visible_snapshot
    from .report_session_operation_engine import APPLIED, SUPERSEDED_BY_UNDO

    dates = conn.execute(
        """
        SELECT report_date FROM report_session_operation
        UNION
        SELECT substr(start_time, 1, 10) FROM activity_log WHERE length(start_time) >= 10
        UNION
        SELECT substr(end_time, 1, 10) FROM activity_log WHERE end_time IS NOT NULL AND length(end_time) >= 10
        ORDER BY 1
        """
    ).fetchall()
    try:
        for date_row in dates:
            report_date = str(date_row[0] or "")
            datetime.strptime(report_date, "%Y-%m-%d")
            for row in conn.execute(
                "SELECT * FROM report_session_operation WHERE report_date = ? ORDER BY sequence, id",
                (report_date,),
            ).fetchall():
                operation = dict(row)
                operation["payload"] = json.loads(str(operation.pop("payload_json")))
                _validate_operation_payload(operation, conn)
            snapshot = build_visible_snapshot(report_date, report_date, conn=conn)
            invalid = [
                item
                for item in snapshot.operation_diagnostics
                if item.state not in {APPLIED, SUPERSEDED_BY_UNDO}
            ]
            if invalid:
                raise BackupCorruptedError("backup file is invalid or corrupted")
    except BackupCorruptedError:
        raise
    except Exception as exc:
        raise BackupCorruptedError("backup file is invalid or corrupted") from exc


def _validate_operation_payload(operation: dict[str, Any], conn: sqlite3.Connection) -> None:
    payload = operation.get("payload")
    if not isinstance(payload, dict) or payload.get("payload_version") != 4:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    operation_type = str(operation.get("operation_type") or "")
    allowed = {"payload_version"}
    if operation_type == "edit_session":
        allowed |= {"project", "duration", "note"}
        if not any(key in payload for key in ("project", "duration", "note")):
            raise BackupCorruptedError("backup file is invalid or corrupted")
        project = payload.get("project")
        if project is not None:
            if not isinstance(project, dict) or set(project) - {"mode", "project_id"}:
                raise BackupCorruptedError("backup file is invalid or corrupted")
            if project.get("mode") == "set":
                project_id = project.get("project_id")
                if not isinstance(project_id, int) or not conn.execute(
                    "SELECT 1 FROM project WHERE id = ?", (project_id,)
                ).fetchone():
                    raise BackupCorruptedError("backup file is invalid or corrupted")
            elif project.get("mode") != "inherit":
                raise BackupCorruptedError("backup file is invalid or corrupted")
        duration = payload.get("duration")
        if duration is not None:
            if not isinstance(duration, dict) or set(duration) - {"mode", "value"}:
                raise BackupCorruptedError("backup file is invalid or corrupted")
            if duration.get("mode") == "set":
                if not isinstance(duration.get("value"), int) or duration["value"] < 0:
                    raise BackupCorruptedError("backup file is invalid or corrupted")
            elif duration.get("mode") != "inherit":
                raise BackupCorruptedError("backup file is invalid or corrupted")
        note = payload.get("note")
        if note is not None:
            if not isinstance(note, dict) or set(note) - {"mode", "value"}:
                raise BackupCorruptedError("backup file is invalid or corrupted")
            if note.get("mode") == "set":
                if not isinstance(note.get("value"), str):
                    raise BackupCorruptedError("backup file is invalid or corrupted")
            elif note.get("mode") != "inherit":
                raise BackupCorruptedError("backup file is invalid or corrupted")
    elif operation_type == "hide_activity":
        allowed |= {"summary_id"}
        if not isinstance(payload.get("summary_id"), str) or not payload["summary_id"]:
            raise BackupCorruptedError("backup file is invalid or corrupted")
    elif operation_type not in {"hide_session", "copy_session", "merge_sessions", "split_session"}:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    if set(payload) - allowed:
        raise BackupCorruptedError("backup file is invalid or corrupted")


def _validate_operation_graph(conn: sqlite3.Connection) -> None:
    checks = (
        """
        SELECT 1 FROM report_mutation_request r
        LEFT JOIN report_session_operation o ON o.id = r.operation_id
        WHERE r.operation_id IS NOT NULL AND o.id IS NULL LIMIT 1
        """,
        """
        SELECT 1 FROM report_mutation_request
        WHERE json_valid(result_json) = 0
           OR (outcome_type = 'operation_committed') <> (operation_id IS NOT NULL)
        LIMIT 1
        """,
        """
        SELECT 1 FROM report_session_operation o
        WHERE json_valid(o.payload_json) = 0
           OR NOT EXISTS (
                SELECT 1 FROM report_session_operation_member m
                WHERE m.operation_id = o.id AND m.role = 'source'
           )
           OR (o.operation_type = 'merge_sessions' AND NOT EXISTS (
                SELECT 1 FROM report_session_operation_member m
                WHERE m.operation_id = o.id AND m.role = 'target'
           ))
           OR (o.operation_type = 'split_session' AND NOT EXISTS (
                SELECT 1 FROM report_session_operation m
                WHERE m.id = o.undo_of_operation_id
                  AND m.operation_type = 'merge_sessions'
                  AND m.report_date = o.report_date
                  AND m.sequence < o.sequence
           ))
        LIMIT 1
        """,
        """
        SELECT 1 FROM report_session_operation
        GROUP BY report_date, sequence HAVING COUNT(*) > 1 LIMIT 1
        """,
    )
    for sql in checks:
        if conn.execute(sql).fetchone():
            raise BackupCorruptedError("backup file is invalid or corrupted")


def _delete_all_rows(conn: sqlite3.Connection) -> None:
    for table in _DELETE_ORDER:
        conn.execute(f"DELETE FROM {table}")


def _insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    schema_columns = _table_columns(conn, table)
    if not schema_columns:
        return 0
    expected = set(schema_columns)
    col_clause = ", ".join(f'"{column}"' for column in schema_columns)
    placeholders = ", ".join("?" for _ in schema_columns)
    sql = f"INSERT INTO {table} ({col_clause}) VALUES ({placeholders})"
    inserted = 0
    for row in rows:
        if set(row) != expected:
            raise BackupCorruptedError("backup file is invalid or corrupted")
        conn.execute(sql, [row.get(column) for column in schema_columns])
        inserted += 1
    return inserted


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _read_and_decrypt(blob: bytes, passphrase: str) -> bytes:
    try:
        parse_backup_manifest(blob)
    except BackupFormatError as exc:
        raise _classify_format_error(exc) from exc
    try:
        return decrypt_encrypted_backup(blob, passphrase)
    except BackupFormatError as exc:
        logging.warning("encrypted backup decrypt failed: %s", type(exc).__name__)
        raise BackupDecryptionError("could not decrypt backup or wrong passphrase") from exc


def _classify_format_error(exc: BackupFormatError) -> SecureBackupError:
    if "version" in str(exc).lower():
        return BackupVersionNotSupportedError("backup version is not supported")
    return BackupCorruptedError("backup file is invalid or corrupted")


def _invalidate_caches() -> None:
    from .folder_rule_service import invalidate_folder_rule_cache
    from .privacy_service import clear_exclude_rules_cache
    from .project_inference_service import invalidate_keyword_rule_cache
    from .project_service import invalidate_uncategorized_project_cache

    clear_settings_cache()
    clear_exclude_rules_cache()
    invalidate_uncategorized_project_cache()
    invalidate_folder_rule_cache()
    invalidate_keyword_rule_cache()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "BACKUP_FILE_SUFFIX",
    "BackupCorruptedError",
    "BackupDecryptionError",
    "BackupImportInProgressError",
    "BackupManifestInfo",
    "BackupVersionNotSupportedError",
    "EXCLUDED_TABLES",
    "EXPORT_TABLES",
    "ImportResult",
    "MIGRATABLE_SETTINGS",
    "SECURE_IMPORT_COORDINATOR",
    "SecureImportCoordinator",
    "SecureBackupError",
    "export_encrypted_backup",
    "import_encrypted_backup",
    "is_secure_import_in_progress",
    "register_collector_pause_handler",
    "clear_collector_pause_handler",
    "parse_encrypted_backup_manifest",
]
