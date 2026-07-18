"""Encrypted local backup and destructive database-maintenance boundary."""

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
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from ..constants import APP_VERSION, TIME_FORMAT
from ..db import (
    CURRENT_SCHEMA_VERSION,
    expected_schema_fingerprint,
    get_connection,
    get_db_key,
    now_str,
    read_schema_indexes_sql,
    read_internal_schema_sql,
    read_schema_sql,
    schema_fingerprint,
    seed_defaults,
)
from ..security.backup_format import (
    BackupFormatError,
    BackupManifest,
    create_encrypted_backup,
    decrypt_encrypted_backup,
    parse_backup_manifest,
)
from ..write_gate import DATABASE_WRITE_GATE
from . import activity_inference_job_repository as inference_jobs
from .database_maintenance_barrier import drain_existing_writers
from .database_replacement_generation_service import (
    capture_replacement_generation_floor,
    publish_database_replacement,
)
from ..generation_clock import clear as clear_generation_clock
from ..generation_clock import publish_replacement_committed
from .runtime_activity_state_service import clear_runtime_activity_state
from .secure_backup_validation import BackupValidationError, validate_staging_database
from .settings_service import get_bool_setting, get_setting, set_setting

PAYLOAD_FORMAT = "worktrace-local-data"
PAYLOAD_VERSION = 5
SCHEMA_VERSION = str(CURRENT_SCHEMA_VERSION)
_LEGACY_BACKUP_SCHEMA_FINGERPRINTS = {
    "8": "3fd5ae980749886a04f7f9170669a606fa80d6b554924d0ad29b457b0c51deac",
}
BACKUP_FILE_SUFFIX = ".wtbackup"
MAX_BACKUP_FILE_BYTES = 512 * 1024 * 1024
MAX_BACKUP_PAYLOAD_BYTES = 384 * 1024 * 1024

EXPORT_TABLES_V4: tuple[str, ...] = (
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
EXPORT_TABLES: tuple[str, ...] = (
    *EXPORT_TABLES_V4,
    "activity_inference_job",
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
    "activity_inference_job",
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


class SecureBackupError(Exception):
    """Base error for encrypted backup operations."""


class BackupDecryptionError(SecureBackupError):
    """Could not decrypt the backup or the passphrase was wrong."""


class BackupCorruptedError(SecureBackupError):
    """The backup file is invalid or corrupted."""


class BackupVersionNotSupportedError(SecureBackupError):
    """The backup version is not supported by this build."""


class BackupImportInProgressError(SecureBackupError):
    """Another destructive maintenance operation is already in progress."""


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


@dataclass
class _ImportGuardState:
    prior_user_paused: bool
    prior_collector_status: str
    succeeded: bool = False
    fail_closed: bool = False

    def mark_succeeded(self) -> None:
        self.succeeded = True


class SecureImportPhase(str, Enum):
    IDLE = "idle"
    DRAINING = "draining"
    EXCLUSIVE = "exclusive"


class SecureImportCoordinator:
    """Single owner for DRAINING, pause/reset, and exclusive replacement."""

    def __init__(self) -> None:
        self._maintenance_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._phase = SecureImportPhase.IDLE
        self._pause_handler: Any = None
        self._reset_handler: Any = None

    def register_collector_pause_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._pause_handler = handler

    def clear_collector_pause_handler(self, handler: Any | None = None) -> None:
        with self._state_lock:
            if handler is None or self._pause_handler == handler:
                self._pause_handler = None

    def register_collector_reset_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._reset_handler = handler

    def clear_collector_reset_handler(self, handler: Any | None = None) -> None:
        with self._state_lock:
            if handler is None or self._reset_handler == handler:
                self._reset_handler = None

    def phase(self) -> SecureImportPhase:
        with self._state_lock:
            return self._phase

    def write_gate_active(self) -> bool:
        with self._state_lock:
            return (
                self._phase is not SecureImportPhase.IDLE
                or DATABASE_WRITE_GATE.active()
            )

    def _require_command_ack(
        self,
        result: dict[str, Any],
        *,
        kind: str,
        state: _ImportGuardState,
        reason: str,
    ) -> None:
        if bool(result.get("ok")):
            return
        if bool(result.get("command_state_unknown")):
            state.fail_closed = True
            set_setting("user_paused", "true")
            set_setting("collector_status", "paused")
            clear_runtime_activity_state(f"{reason}_{kind}_state_unknown")
        raise SecureBackupError(f"collector_{kind}_not_acknowledged")

    @contextmanager
    def acquire(
        self,
        *,
        reason: str = "secure_import",
    ) -> Iterator[_ImportGuardState]:
        if not self._maintenance_lock.acquire(blocking=False):
            logging.warning("runtime maintenance rejected reason=%s", reason)
            raise BackupImportInProgressError(
                "another destructive operation is already in progress"
            )

        try:
            with self._state_lock:
                pause_handler = self._pause_handler
                reset_handler = self._reset_handler

            with DATABASE_WRITE_GATE.draining() as lease:
                with self._state_lock:
                    self._phase = SecureImportPhase.DRAINING

                prior_user_paused = get_bool_setting("user_paused", False)
                prior_collector_status = (
                    get_setting("collector_status", "stopped") or "stopped"
                )
                state = _ImportGuardState(
                    prior_user_paused=prior_user_paused,
                    prior_collector_status=prior_collector_status,
                )

                try:
                    if pause_handler is not None:
                        result = pause_handler(timeout_seconds=5.0)
                        self._require_command_ack(
                            result,
                            kind="pause",
                            state=state,
                            reason=reason,
                        )
                    if reset_handler is not None:
                        result = reset_handler(timeout_seconds=5.0)
                        self._require_command_ack(
                            result,
                            kind="reset",
                            state=state,
                            reason=reason,
                        )

                    set_setting("user_paused", "true")
                    set_setting("collector_status", "paused")
                    clear_runtime_activity_state(f"{reason}_guard_enter")

                    drain_existing_writers()
                    lease.promote()
                    with self._state_lock:
                        self._phase = SecureImportPhase.EXCLUSIVE

                    yield state
                    state.succeeded = True
                    clear_runtime_activity_state(f"{reason}_success")
                    logging.info(
                        "runtime maintenance completed reason=%s paused=true",
                        reason,
                    )
                except Exception as exc:
                    if not state.succeeded and not state.fail_closed:
                        set_setting(
                            "user_paused",
                            "true" if prior_user_paused else "false",
                        )
                        set_setting("collector_status", prior_collector_status)
                        clear_runtime_activity_state(f"{reason}_rollback")
                    logging.warning(
                        "runtime maintenance failed reason=%s exc_type=%s",
                        reason,
                        type(exc).__name__,
                    )
                    raise
        finally:
            with self._state_lock:
                self._phase = SecureImportPhase.IDLE
            self._maintenance_lock.release()


SECURE_IMPORT_COORDINATOR = SecureImportCoordinator()


def register_collector_pause_handler(handler: Any) -> None:
    SECURE_IMPORT_COORDINATOR.register_collector_pause_handler(handler)


def clear_collector_pause_handler(handler: Any | None = None) -> None:
    SECURE_IMPORT_COORDINATOR.clear_collector_pause_handler(handler)


def register_collector_reset_handler(handler: Any) -> None:
    SECURE_IMPORT_COORDINATOR.register_collector_reset_handler(handler)


def clear_collector_reset_handler(handler: Any | None = None) -> None:
    SECURE_IMPORT_COORDINATOR.clear_collector_reset_handler(handler)


def is_secure_import_in_progress() -> bool:
    return SECURE_IMPORT_COORDINATOR.write_gate_active()


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

    input_file = Path(input_path)
    _require_bounded_backup_file(input_file)
    with SECURE_IMPORT_COORDINATOR.acquire(reason="secure_import") as guard:
        blob = input_file.read_bytes()
        payload = _read_and_decrypt(blob, passphrase)
        data = _parse_and_validate_payload(payload)
        imported_counts = _replace_import(data)
        guard.mark_succeeded()

    logging.info(
        "encrypted backup import success mode=%s tables=%d",
        mode,
        len(imported_counts),
    )
    return ImportResult(
        mode=mode,
        imported_tables=imported_counts,
        folder_index_reset=True,
    )


def parse_encrypted_backup_manifest(input_path: str | Path) -> BackupManifestInfo:
    input_file = Path(input_path)
    _require_bounded_backup_file(input_file)
    blob = input_file.read_bytes()
    try:
        manifest = parse_backup_manifest(blob)
    except BackupFormatError as exc:
        raise _classify_format_error(exc) from exc
    return BackupManifestInfo.from_manifest(manifest)


def _require_bounded_backup_file(path: Path) -> None:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BackupCorruptedError("backup file is invalid or corrupted") from exc
    if size <= 0 or size > MAX_BACKUP_FILE_BYTES:
        raise BackupCorruptedError("backup file is invalid or corrupted")


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
                tables[table] = [
                    dict(row)
                    for row in rows
                    if row["key"] in MIGRATABLE_SETTINGS
                ]
            else:
                tables[table] = [dict(row) for row in rows]
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    payload = json.dumps(
        {
            "format": PAYLOAD_FORMAT,
            "version": PAYLOAD_VERSION,
            "created_at": _utc_now(),
            "app_version": APP_VERSION,
            "schema_version": SCHEMA_VERSION,
            "schema_fingerprint": current_schema_fingerprint,
            "tables": tables,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > MAX_BACKUP_PAYLOAD_BYTES:
        raise SecureBackupError("backup payload exceeds supported size")
    return payload


def _parse_and_validate_payload(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_BACKUP_PAYLOAD_BYTES:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logging.warning(
            "encrypted backup payload json parse failed: %s",
            type(exc).__name__,
        )
        raise BackupCorruptedError("backup file is invalid or corrupted") from exc
    if not isinstance(data, dict) or data.get("format") != PAYLOAD_FORMAT:
        raise BackupCorruptedError("backup file is invalid or corrupted")

    payload_version = data.get("version")
    schema_version = str(data.get("schema_version") or "")
    fingerprint = str(data.get("schema_fingerprint") or "")
    if payload_version == PAYLOAD_VERSION:
        if schema_version != SCHEMA_VERSION:
            raise BackupVersionNotSupportedError("backup version is not supported")
        expected_tables = set(EXPORT_TABLES)
        required_fingerprint = expected_schema_fingerprint()
    elif payload_version == 4:
        expected_tables = set(EXPORT_TABLES_V4)
        legacy_fingerprints = {
            "10": _schema_v10_fingerprint(),
            **_LEGACY_BACKUP_SCHEMA_FINGERPRINTS,
        }
        if schema_version not in legacy_fingerprints:
            raise BackupVersionNotSupportedError("backup version is not supported")
        required_fingerprint = legacy_fingerprints[schema_version]
    else:
        raise BackupVersionNotSupportedError("backup version is not supported")

    if fingerprint != required_fingerprint:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    tables = data.get("tables")
    if not isinstance(tables, dict) or set(tables) != expected_tables:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    for rows in tables.values():
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise BackupCorruptedError("backup file is invalid or corrupted")
    if payload_version == PAYLOAD_VERSION:
        _validate_inference_job_rows(tables["activity_inference_job"])
    return data


def _validate_inference_job_rows(rows: list[dict[str, Any]]) -> None:
    expected_columns = {
        "activity_id",
        "reason",
        "attempt_count",
        "available_at",
        "last_error_code",
        "created_at",
        "updated_at",
    }
    for row in rows:
        if set(row) != expected_columns:
            raise BackupCorruptedError("backup file is invalid or corrupted")
        if str(row.get("reason") or "") not in inference_jobs.REASONS:
            raise BackupCorruptedError("backup file is invalid or corrupted")
        error_code = row.get("last_error_code")
        if error_code is not None and str(error_code) not in inference_jobs.ERROR_CODES:
            raise BackupCorruptedError("backup file is invalid or corrupted")
        try:
            if int(row.get("activity_id")) <= 0 or int(row.get("attempt_count")) < 0:
                raise ValueError
            for key in ("available_at", "created_at", "updated_at"):
                datetime.strptime(str(row.get(key) or ""), TIME_FORMAT)
        except (TypeError, ValueError) as exc:
            raise BackupCorruptedError("backup file is invalid or corrupted") from exc


def _replace_import(data: dict[str, Any]) -> dict[str, int]:
    """Replace business data and restore or upgrade durable inference jobs."""

    payload_version = int(data["version"])
    source_tables = EXPORT_TABLES if payload_version == PAYLOAD_VERSION else EXPORT_TABLES_V4
    staging_path: str | None = None
    try:
        fd, staging_path = tempfile.mkstemp(
            prefix="worktrace-import-",
            suffix=".sqlite",
        )
        os.close(fd)
        staging = sqlite3.connect(staging_path)
        staging.row_factory = sqlite3.Row
        staging.execute("PRAGMA foreign_keys = ON")
        try:
            staging.executescript(read_schema_sql())
            staging.executescript(read_internal_schema_sql())
            staging.executescript(read_schema_indexes_sql())
            staging.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
            imported = _load_import_tables(staging, data["tables"], source_tables)
            seed_defaults(staging)
            _reset_derived_folder_index(staging)
            _validate_staging_database(staging)
            if payload_version == 4:
                inference_jobs.seed_legacy_import_jobs(staging)
            staging.commit()
        except Exception:
            staging.rollback()
            raise
        finally:
            staging.close()

        replacement_values = None
        with get_connection() as live:
            live.execute("BEGIN IMMEDIATE")
            replacement_floor = capture_replacement_generation_floor(live)
            _delete_all_rows(live)
            live.execute("DELETE FROM activity_resource_repair_job")
            source = sqlite3.connect(staging_path)
            source.row_factory = sqlite3.Row
            try:
                for table in EXPORT_TABLES:
                    _insert_rows(
                        live,
                        table,
                        [
                            dict(row)
                            for row in source.execute(f"SELECT * FROM {table}")
                        ],
                    )
            finally:
                source.close()
            seed_defaults(live)
            _reset_derived_folder_index(live)
            timestamp = now_str()
            for key, value in (
                ("user_paused", "true"),
                ("collector_status", "paused"),
                ("clipboard_capture_enabled", "false"),
            ):
                live.execute(
                    "UPDATE settings SET value = ?, updated_at = ? WHERE key = ?",
                    (value, timestamp, key),
                )
            _validate_staging_database(live)
            replacement_values = publish_database_replacement(
                live,
                minimum_values=replacement_floor,
            )
            live.commit()
        if replacement_values is None:
            raise RuntimeError("database_replacement_generation_missing")
        database_key = get_db_key()
        try:
            publish_replacement_committed(database_key, replacement_values)
        except Exception:
            logging.exception("database replacement generation publication failed")
            clear_generation_clock(database_key)
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


def _load_import_tables(
    conn: sqlite3.Connection,
    tables: dict[str, Any],
    table_names: tuple[str, ...],
) -> dict[str, int]:
    imported: dict[str, int] = {}
    for table in table_names:
        rows = tables.get(table, [])
        if table == "settings":
            rows = [
                row for row in rows if row.get("key") in MIGRATABLE_SETTINGS
            ]
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
    try:
        validate_staging_database(conn)
    except BackupValidationError as exc:
        raise BackupCorruptedError("backup file is invalid or corrupted") from exc


def _delete_all_rows(conn: sqlite3.Connection) -> None:
    for table in _DELETE_ORDER:
        conn.execute(f"DELETE FROM {table}")


def _insert_rows(
    conn: sqlite3.Connection,
    table: str,
    rows: list[dict[str, Any]],
) -> int:
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
    return [
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    ]


def _read_and_decrypt(blob: bytes, passphrase: str) -> bytes:
    try:
        parse_backup_manifest(blob)
    except BackupFormatError as exc:
        raise _classify_format_error(exc) from exc
    try:
        payload = decrypt_encrypted_backup(blob, passphrase)
    except BackupFormatError as exc:
        logging.warning(
            "encrypted backup decrypt failed: %s",
            type(exc).__name__,
        )
        raise BackupDecryptionError(
            "could not decrypt backup or wrong passphrase"
        ) from exc
    if len(payload) > MAX_BACKUP_PAYLOAD_BYTES:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    return payload


def _classify_format_error(exc: BackupFormatError) -> SecureBackupError:
    if "version" in str(exc).lower():
        return BackupVersionNotSupportedError("backup version is not supported")
    return BackupCorruptedError("backup file is invalid or corrupted")


@lru_cache(maxsize=1)
def _schema_v10_fingerprint() -> str:
    """Derive the published v10 fingerprint without retaining copied schema files."""

    reference = sqlite3.connect(":memory:")
    reference.row_factory = sqlite3.Row
    try:
        reference.executescript(read_schema_sql())
        reference.executescript(read_internal_schema_sql())
        reference.executescript(read_schema_indexes_sql())
        reference.execute("DROP TABLE activity_inference_job")
        return schema_fingerprint(reference)
    finally:
        reference.close()


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00",
        "Z",
    )


__all__ = [
    "BACKUP_FILE_SUFFIX",
    "MAX_BACKUP_FILE_BYTES",
    "MAX_BACKUP_PAYLOAD_BYTES",
    "BackupCorruptedError",
    "BackupDecryptionError",
    "BackupImportInProgressError",
    "BackupManifestInfo",
    "BackupVersionNotSupportedError",
    "EXCLUDED_TABLES",
    "EXPORT_TABLES",
    "EXPORT_TABLES_V4",
    "ImportResult",
    "MIGRATABLE_SETTINGS",
    "SECURE_IMPORT_COORDINATOR",
    "SecureImportCoordinator",
    "SecureImportPhase",
    "SecureBackupError",
    "export_encrypted_backup",
    "import_encrypted_backup",
    "is_secure_import_in_progress",
    "register_collector_pause_handler",
    "clear_collector_pause_handler",
    "register_collector_reset_handler",
    "clear_collector_reset_handler",
    "parse_encrypted_backup_manifest",
]
