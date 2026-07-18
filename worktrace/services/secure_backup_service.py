"""Versioned encrypted backup facade with exact inference obligations."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from ..constants import APP_VERSION
from ..db import (
    CURRENT_SCHEMA_VERSION,
    expected_schema_fingerprint,
    get_connection,
    get_db_key,
    now_str,
    read_internal_schema_sql,
    read_schema_indexes_sql,
    read_schema_sql,
    schema_fingerprint,
    seed_defaults,
)
from ..generation_clock import clear as clear_generation_clock
from ..generation_clock import publish_replacement_committed
from ..security.backup_format import create_encrypted_backup
from . import activity_inference_job_repository as inference_jobs
from . import secure_backup_core as _core
from .database_replacement_generation_service import (
    capture_replacement_generation_floor,
    publish_database_replacement,
)

PAYLOAD_FORMAT = _core.PAYLOAD_FORMAT
PAYLOAD_VERSION = 5
SCHEMA_VERSION = str(CURRENT_SCHEMA_VERSION)
BACKUP_FILE_SUFFIX = _core.BACKUP_FILE_SUFFIX
MAX_BACKUP_FILE_BYTES = _core.MAX_BACKUP_FILE_BYTES
MAX_BACKUP_PAYLOAD_BYTES = _core.MAX_BACKUP_PAYLOAD_BYTES

EXPORT_TABLES_V4: tuple[str, ...] = tuple(_core.EXPORT_TABLES)
EXPORT_TABLES: tuple[str, ...] = (
    *EXPORT_TABLES_V4,
    "activity_inference_job",
)
EXCLUDED_TABLES = _core.EXCLUDED_TABLES
MIGRATABLE_SETTINGS = _core.MIGRATABLE_SETTINGS

SecureBackupError = _core.SecureBackupError
BackupDecryptionError = _core.BackupDecryptionError
BackupCorruptedError = _core.BackupCorruptedError
BackupVersionNotSupportedError = _core.BackupVersionNotSupportedError
BackupImportInProgressError = _core.BackupImportInProgressError
BackupManifestInfo = _core.BackupManifestInfo
ImportResult = _core.ImportResult
SecureImportPhase = _core.SecureImportPhase
SecureImportCoordinator = _core.SecureImportCoordinator
SECURE_IMPORT_COORDINATOR = _core.SECURE_IMPORT_COORDINATOR

register_collector_pause_handler = _core.register_collector_pause_handler
clear_collector_pause_handler = _core.clear_collector_pause_handler
register_collector_reset_handler = _core.register_collector_reset_handler
clear_collector_reset_handler = _core.clear_collector_reset_handler
is_secure_import_in_progress = _core.is_secure_import_in_progress
parse_encrypted_backup_manifest = _core.parse_encrypted_backup_manifest


def export_encrypted_backup(output_path: str | Path, passphrase: str) -> Path:
    if not passphrase:
        raise SecureBackupError("passphrase is required")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = _build_export_payload()
    blob = create_encrypted_backup(payload, passphrase, APP_VERSION)
    _core._atomic_write_bytes(out, blob)
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
    _core._require_bounded_backup_file(input_file)
    with SECURE_IMPORT_COORDINATOR.acquire(reason="secure_import") as guard:
        blob = input_file.read_bytes()
        payload = _core._read_and_decrypt(blob, passphrase)
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
        expected_tables = set(EXPORT_TABLES)
        if schema_version != SCHEMA_VERSION:
            raise BackupVersionNotSupportedError("backup version is not supported")
        required_fingerprint = expected_schema_fingerprint()
    elif payload_version == 4:
        expected_tables = set(EXPORT_TABLES_V4)
        legacy_fingerprints = {
            "10": _schema_v10_fingerprint(),
            **dict(_core._LEGACY_BACKUP_SCHEMA_FINGERPRINTS),
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
    return data


def _replace_import(data: dict[str, Any]) -> dict[str, int]:
    """Replace business data and restore or rebuild inference obligations."""

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
            imported = _load_import_tables(
                staging,
                data["tables"],
                source_tables,
            )
            seed_defaults(staging)
            if payload_version == 4:
                inference_jobs.seed_legacy_import_jobs(staging)
            _core._reset_derived_folder_index(staging)
            _core._validate_staging_database(staging)
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
            live.execute("DELETE FROM activity_inference_job")
            _core._delete_all_rows(live)
            live.execute("DELETE FROM activity_resource_repair_job")
            source = sqlite3.connect(staging_path)
            source.row_factory = sqlite3.Row
            try:
                for table in EXPORT_TABLES:
                    _core._insert_rows(
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
            _core._reset_derived_folder_index(live)
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
            _core._validate_staging_database(live)
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
        imported[table] = _core._insert_rows(conn, table, rows)
    return imported


@lru_cache(maxsize=1)
def _schema_v10_fingerprint() -> str:
    reference = sqlite3.connect(":memory:")
    reference.row_factory = sqlite3.Row
    try:
        package = resources.files("worktrace")
        reference.executescript(
            package.joinpath("schema_v10.sql").read_text(encoding="utf-8")
        )
        reference.executescript(
            package.joinpath("schema_internal_v10.sql").read_text(encoding="utf-8")
        )
        reference.executescript(
            package.joinpath("schema_indexes_v10.sql").read_text(encoding="utf-8")
        )
        return schema_fingerprint(reference)
    finally:
        reference.close()


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
    "clear_collector_pause_handler",
    "clear_collector_reset_handler",
    "export_encrypted_backup",
    "import_encrypted_backup",
    "is_secure_import_in_progress",
    "parse_encrypted_backup_manifest",
    "register_collector_pause_handler",
    "register_collector_reset_handler",
]
