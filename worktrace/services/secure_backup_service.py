"""Current-format encrypted backup and secure replace-import owner."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..constants import APP_VERSION
from ..database_content_manifest import (
    BACKUP_TABLES,
    DELETE_ORDER,
    TABLE_NAMES,
)
from ..database_replacement_unit_of_work import DatabaseReplacementUnitOfWork
from ..db import (
    CURRENT_SCHEMA_VERSION,
    expected_schema_fingerprint,
    get_connection,
    now_str,
    read_internal_schema_sql,
    read_schema_indexes_sql,
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
from . import database_maintenance_service
from .secure_backup_validation import BackupValidationError, validate_staging_database

PAYLOAD_FORMAT = "worktrace-local-data"
PAYLOAD_VERSION = 6
SCHEMA_VERSION = str(CURRENT_SCHEMA_VERSION)
BACKUP_FILE_SUFFIX = ".wtbackup"
MAX_BACKUP_FILE_BYTES = 512 * 1024 * 1024
MAX_BACKUP_PAYLOAD_BYTES = 384 * 1024 * 1024

EXPORT_TABLES: tuple[str, ...] = BACKUP_TABLES
EXCLUDED_TABLES: frozenset[str] = frozenset(TABLE_NAMES) - frozenset(EXPORT_TABLES)
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


class SecureBackupError(Exception):
    """Base error for encrypted backup operations."""


class BackupDecryptionError(SecureBackupError):
    """Could not decrypt the backup or the passphrase was wrong."""


class BackupCorruptedError(SecureBackupError):
    """The backup is malformed or violates current schema semantics."""


class BackupVersionNotSupportedError(SecureBackupError):
    """The payload or schema version is not supported by this build."""


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
    maintenance_status: dict[str, object] = field(default_factory=dict)


def export_encrypted_backup(output_path: str | Path, passphrase: str) -> Path:
    """Export a current-format backup from a coordinator-owned snapshot."""

    if not passphrase:
        raise SecureBackupError("passphrase is required")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with database_maintenance_service.consistent_snapshot(
        "encrypted_backup_export"
    ):
        payload = _build_export_payload_under_snapshot()
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
    blob = input_file.read_bytes()
    payload = _read_and_decrypt(blob, passphrase)
    data = _parse_and_validate_payload(payload)
    try:
        with database_maintenance_service.database_replacement("secure_import"):
            imported_counts = _replace_import(data)
    except database_maintenance_service.MaintenanceInProgressError as exc:
        raise BackupImportInProgressError(
            "another destructive operation is already in progress"
        ) from exc

    status = database_maintenance_service.maintenance_status().to_dict()
    logging.info(
        "encrypted backup import success mode=%s tables=%d restored=%s",
        mode,
        len(imported_counts),
        status["maintenance_restored"],
    )
    return ImportResult(
        mode=mode,
        imported_tables=imported_counts,
        folder_index_reset=True,
        maintenance_status=status,
    )


def parse_encrypted_backup_manifest(input_path: str | Path) -> BackupManifestInfo:
    input_file = Path(input_path)
    _require_bounded_backup_file(input_file)
    try:
        manifest = parse_backup_manifest(input_file.read_bytes())
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


def _build_export_payload_under_snapshot() -> bytes:
    """Build payload while the caller owns the maintenance snapshot capability."""

    tables: dict[str, list[dict[str, Any]]] = {}
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        current_fingerprint = schema_fingerprint(conn)
        if current_fingerprint != expected_schema_fingerprint():
            raise SecureBackupError("database_schema_incompatible")
        for table in EXPORT_TABLES:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            if table == "settings":
                tables[table] = [
                    dict(row) for row in rows if row["key"] in MIGRATABLE_SETTINGS
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
            "schema_fingerprint": current_fingerprint,
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
    if data.get("version") != PAYLOAD_VERSION:
        raise BackupVersionNotSupportedError("backup version is not supported")
    if str(data.get("schema_version") or "") != SCHEMA_VERSION:
        raise BackupVersionNotSupportedError("backup version is not supported")
    if str(data.get("schema_fingerprint") or "") != expected_schema_fingerprint():
        raise BackupCorruptedError("backup file is invalid or corrupted")
    tables = data.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(EXPORT_TABLES):
        raise BackupCorruptedError("backup file is invalid or corrupted")
    for rows in tables.values():
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise BackupCorruptedError("backup file is invalid or corrupted")
    return data


def _replace_import(data: dict[str, Any]) -> dict[str, int]:
    """Stage and validate current data, then replace live contents atomically."""

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

        # Live replacement goes through DatabaseReplacementUnitOfWork so the
        # epoch bump, commit and process-local publication have one owner.
        with DatabaseReplacementUnitOfWork() as replacement_uow:
            live = replacement_uow.connection
            _delete_all_rows(live)
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
            _validate_staging_database(live)
        return imported
    except BackupCorruptedError:
        raise
    except BackupValidationError as exc:
        raise BackupCorruptedError("backup file is invalid or corrupted") from exc
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
) -> dict[str, int]:
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
        SET status = 'pending', valid_from = NULL,
            active_generation = NULL, building_generation = NULL,
            build_status = NULL, last_error = NULL,
            last_indexed_at = NULL, last_checked_at = NULL,
            file_count = 0, error_message = NULL,
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
    for table in DELETE_ORDER:
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
        raise BackupCorruptedError("backup file is invalid or corrupted")
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
    "ImportResult",
    "MIGRATABLE_SETTINGS",
    "PAYLOAD_FORMAT",
    "PAYLOAD_VERSION",
    "SCHEMA_VERSION",
    "SecureBackupError",
    "export_encrypted_backup",
    "import_encrypted_backup",
    "parse_encrypted_backup_manifest",
]
