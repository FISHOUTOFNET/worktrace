"""Encrypted local backup export/import service.

This service bridges the ``worktrace.security.backup_format`` crypto
container with the real WorkTrace SQLite database. It produces a UTF-8 JSON
payload of the user-migratable tables, encrypts it into a ``.wtbackup`` file,
and restores it back into the local database.

Boundary rules (see docs/v0.2-local-security-design.md):

- The UI never imports this module directly. It goes through ``worktrace.api``.
- This service is the only place that imports both ``worktrace.db`` and
  ``worktrace.security.backup_format``.
- No runtime field-level encryption, no SQLCipher, no network, no merge import.
- Wrong passphrase, corrupted backup, or unsupported version never damage the
  current database. Decryption and payload validation happen before any DB
  mutation.
- Logs record only operation type, result, and exception type. They never
  include passphrase, decrypted payload, window title, path, note, copied text,
  or full ciphertext.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..constants import APP_VERSION
from ..db import get_connection, now_str, seed_defaults
from ..security.backup_format import (
    BACKUP_VERSION,
    BackupFormatError,
    BackupManifest,
    create_encrypted_backup,
    decrypt_encrypted_backup,
    parse_backup_manifest,
)
from ..services.settings_service import (
    clear_settings_cache,
    get_bool_setting,
    get_setting,
    set_setting,
)
from .runtime_activity_state_service import clear_runtime_activity_state


PAYLOAD_FORMAT = "worktrace-local-data"
PAYLOAD_VERSION = 1
SCHEMA_VERSION = "1"
BACKUP_FILE_SUFFIX = ".wtbackup"

# Tables exported and imported, in dependency-safe insert order (parents first).
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
    "project_session_override",
    "project_session_override_member",
    "activity_resource",
)

# Tables excluded from export (derived cache or runtime-only).
EXCLUDED_TABLES: frozenset[str] = frozenset({"folder_rule_file_index"})

# Settings keys that are runtime/machine state and must not be migrated.
# After import, ``seed_defaults`` re-creates them with default values.
NON_MIGRATABLE_SETTINGS: frozenset[str] = frozenset(
    {
        "current_activity_snapshot",
        "pending_short_seconds",
        "pending_short_carry_provenance",
        "collector_status",
        "last_collector_heartbeat",
        "last_shutdown_at",
        "user_paused",
        "secure_import_in_progress",
    }
)

# Setting key used to block collector writes during a secure import.
SECURE_IMPORT_GUARD_KEY = "secure_import_in_progress"

# Delete order (children first) to respect foreign keys.
_DELETE_ORDER: tuple[str, ...] = (
    "activity_resource",
    "project_session_override_member",
    "project_session_override",
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
    """The backup version is not supported by this WorkTrace build."""


class BackupImportInProgressError(SecureBackupError):
    """Another secure import is already in progress."""


@dataclass(frozen=True)
class BackupManifestInfo:
    """Non-sensitive manifest info safe to show in the UI layer."""

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
    """Result of a successful encrypted backup import."""

    mode: str
    imported_tables: dict[str, int] = field(default_factory=dict)
    folder_index_reset: bool = False


def export_encrypted_backup(output_path: str | Path, passphrase: str) -> Path:
    """Export the current local database into an encrypted ``.wtbackup`` file.

    Reads real business data, serializes it as UTF-8 JSON, encrypts it with the
    given passphrase, and writes the file atomically (temp file + rename).
    """
    if not passphrase:
        raise SecureBackupError("passphrase is required")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    payload = _build_export_payload()
    blob = create_encrypted_backup(payload, passphrase, APP_VERSION)

    _atomic_write_bytes(out, blob)
    # Do not log the full path: it may contain sensitive folder names.
    logging.info("encrypted backup export success suffix=%s", BACKUP_FILE_SUFFIX)
    return out


def import_encrypted_backup(
    input_path: str | Path,
    passphrase: str,
    mode: str = "replace",
) -> ImportResult:
    """Import an encrypted ``.wtbackup`` file into the current local database.

    Only ``mode="replace"`` is supported. The import runs inside a
    ``secure_import_guard`` that pauses the collector and blocks collector
    writes for the duration of the DB replacement. Decryption and payload
    validation happen inside the guard so that, even on failure, the collector
    cannot write to the DB mid-import; on failure the prior pause/status
    state is restored and the DB is left untouched.
    """
    if not passphrase:
        raise SecureBackupError("passphrase is required")
    if mode != "replace":
        raise SecureBackupError(f"unsupported import mode: {mode}")

    blob = Path(input_path).read_bytes()

    with _secure_import_guard() as guard:
        # Decrypt and validate inside the guard so the collector is already
        # blocked. If decryption fails, the guard restores prior state on exit.
        payload = _read_and_decrypt(blob, passphrase)
        data = _parse_and_validate_payload(payload)
        imported_counts = _replace_import(data)
        # Mark the import as succeeded so the guard leaves the app paused
        # instead of restoring the prior state.
        guard.mark_succeeded()

    _invalidate_caches()
    logging.info(
        "encrypted backup import success mode=%s tables=%d",
        mode,
        len(imported_counts),
    )
    return ImportResult(mode=mode, imported_tables=imported_counts, folder_index_reset=True)


def parse_encrypted_backup_manifest(input_path: str | Path) -> BackupManifestInfo:
    """Parse the non-sensitive manifest from a ``.wtbackup`` file.

    Does not decrypt the payload and does not require a passphrase.
    """
    blob = Path(input_path).read_bytes()
    try:
        manifest = parse_backup_manifest(blob)
    except BackupFormatError as exc:
        raise _classify_format_error(exc) from exc
    return BackupManifestInfo.from_manifest(manifest)




@dataclass
class _ImportGuardState:
    """Mutable state held by the secure import guard.

    ``succeeded`` is set to True only after the DB replacement commits. On
    exit, the guard uses this flag to decide whether to leave the app paused
    (success) or restore the prior pause/status (failure).
    """

    prior_user_paused: bool
    prior_collector_status: str
    prior_snapshot: str
    succeeded: bool = False

    def mark_succeeded(self) -> None:
        self.succeeded = True


@contextmanager
def _secure_import_guard() -> Iterator[_ImportGuardState]:
    """Context manager that blocks collector writes during a secure import."""
    if get_bool_setting(SECURE_IMPORT_GUARD_KEY, False):
        logging.warning("encrypted backup import rejected: already in progress")
        raise BackupImportInProgressError("another encrypted backup import is already in progress")

    prior_user_paused = get_bool_setting("user_paused", False)
    prior_collector_status = get_setting("collector_status", "stopped") or "stopped"
    from ..collector.snapshot_publisher import DEFAULT_SNAPSHOT_PUBLISHER

    prior_snapshot = DEFAULT_SNAPSHOT_PUBLISHER.read_raw()

    set_setting("user_paused", "true")
    set_setting("collector_status", "paused")
    clear_runtime_activity_state("secure_import_guard_enter")
    set_setting(SECURE_IMPORT_GUARD_KEY, "true")
    clear_settings_cache()

    state = _ImportGuardState(
        prior_user_paused=prior_user_paused,
        prior_collector_status=prior_collector_status,
        prior_snapshot=prior_snapshot,
    )

    try:
        yield state
    except Exception as exc:
        # Restore prior state on failure. Do not log the exception message:
        # it may contain sensitive details from upstream layers.
        logging.warning(
            "encrypted backup import failed exc_type=%s", type(exc).__name__
        )
        set_setting("user_paused", "true" if prior_user_paused else "false")
        set_setting("collector_status", prior_collector_status)
        DEFAULT_SNAPSHOT_PUBLISHER.restore_raw(prior_snapshot)
        raise
    else:
        # On success, leave the app paused so the user can verify the imported
        # data before resuming recording. The DB replacement above re-seeds
        # default settings (including user_paused/collector_status), so we must
        # explicitly re-assert the paused state here.
        set_setting("user_paused", "true")
        set_setting("collector_status", "paused")
        clear_runtime_activity_state("secure_import_success")
        logging.info("encrypted backup import guard completed paused=true")
    finally:
        set_setting(SECURE_IMPORT_GUARD_KEY, "false")
        clear_settings_cache()


def is_secure_import_in_progress() -> bool:
    """True when a secure backup import is currently in progress.

    Collector and write paths check this to skip writes that would conflict
    with an in-progress DB replacement.
    """
    return get_bool_setting(SECURE_IMPORT_GUARD_KEY, False)


def _build_export_payload() -> bytes:
    """Read the current database and serialize migratable tables to JSON bytes."""
    tables: dict[str, list[dict[str, Any]]] = {}
    with get_connection() as conn:
        for table in EXPORT_TABLES:
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            if table == "settings":
                tables[table] = [
                    dict(row) for row in rows if row["key"] not in NON_MIGRATABLE_SETTINGS
                ]
            else:
                tables[table] = [dict(row) for row in rows]

    payload_dict = {
        "format": PAYLOAD_FORMAT,
        "version": PAYLOAD_VERSION,
        "created_at": _utc_now(),
        "app_version": APP_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tables": tables,
    }
    return json.dumps(payload_dict, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _parse_and_validate_payload(payload: bytes) -> dict[str, Any]:
    """Parse and validate the decrypted JSON payload.

    Raises BackupCorruptedError if the payload is not valid JSON or does not
    match the expected format/version/tables structure.
    """
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logging.warning("encrypted backup payload json parse failed: %s", type(exc).__name__)
        raise BackupCorruptedError("backup file is invalid or corrupted") from exc

    if not isinstance(data, dict):
        raise BackupCorruptedError("backup file is invalid or corrupted")
    if data.get("format") != PAYLOAD_FORMAT:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    if data.get("version") != PAYLOAD_VERSION:
        raise BackupVersionNotSupportedError("backup version is not supported")
    tables = data.get("tables")
    if not isinstance(tables, dict):
        raise BackupCorruptedError("backup file is invalid or corrupted")

    required = {"project", "activity_log", "settings"}
    missing = required - set(tables.keys())
    if missing:
        raise BackupCorruptedError("backup file is invalid or corrupted")

    for name, rows in tables.items():
        if not isinstance(rows, list):
            raise BackupCorruptedError("backup file is invalid or corrupted")
        for row in rows:
            if not isinstance(row, dict):
                raise BackupCorruptedError("backup file is invalid or corrupted")

    return data




def _replace_import(data: dict[str, Any]) -> dict[str, int]:
    """Replace all local data with the backup content inside one transaction.

    Returns a dict of table name -> imported row count.
    """
    tables = data["tables"]
    imported: dict[str, int] = {}

    with get_connection() as conn:
        _delete_all_rows(conn)
        for table in EXPORT_TABLES:
            rows = tables.get(table, [])
            if table == "settings":
                rows = [r for r in rows if r.get("key") not in NON_MIGRATABLE_SETTINGS]
            count = _insert_rows(conn, table, rows)
            imported[table] = count

        # Re-seed defaults so system projects and runtime-state settings exist.
        seed_defaults(conn)

        # Reset folder index: clear derived cache and mark all states pending.
        conn.execute("DELETE FROM folder_rule_file_index")
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = 'pending',
                valid_from = NULL,
                last_indexed_at = NULL,
                last_checked_at = NULL,
                file_count = 0,
                error_message = NULL,
                refresh_requested = 1,
                updated_at = ?
            """,
            (now_str(),),
        )

    return imported


def _delete_all_rows(conn: sqlite3.Connection) -> None:
    for table in _DELETE_ORDER:
        conn.execute(f"DELETE FROM {table}")


def _insert_rows(conn: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    # Use the current schema's columns so a backup from a slightly different
    # schema version does not break import. Extra backup columns are ignored;
    # missing columns fall back to schema defaults.
    schema_columns = _table_columns(conn, table)
    if not schema_columns:
        return 0

    col_clause = ", ".join(f'"{c}"' for c in schema_columns)
    placeholders = ", ".join("?" for _ in schema_columns)
    sql = f'INSERT INTO {table} ({col_clause}) VALUES ({placeholders})'

    inserted = 0
    for row in rows:
        values = [row.get(col) for col in schema_columns]
        conn.execute(sql, values)
        inserted += 1
    return inserted


def _table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row["name"] for row in rows]




def _read_and_decrypt(blob: bytes, passphrase: str) -> bytes:
    """Decrypt a backup blob, mapping crypto errors to service errors.

    The manifest is parsed first (without decryption) so version/structure
    errors are classified before any decryption attempt.
    """
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
    message = str(exc).lower()
    if "version" in message:
        return BackupVersionNotSupportedError("backup version is not supported")
    return BackupCorruptedError("backup file is invalid or corrupted")




def _invalidate_caches() -> None:
    """Invalidate service-layer caches after a replace import."""
    from .context_service import invalidate_context_recompute_cache
    from .folder_rule_service import invalidate_folder_rule_cache
    from .privacy_service import clear_exclude_rules_cache
    from .project_inference_service import invalidate_keyword_rule_cache
    from .project_service import invalidate_uncategorized_project_cache
    from .settings_service import clear_settings_cache

    clear_settings_cache()
    clear_exclude_rules_cache()
    invalidate_uncategorized_project_cache()
    invalidate_folder_rule_cache()
    invalidate_keyword_rule_cache()
    invalidate_context_recompute_cache()




def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to path via a temp file then atomic rename."""
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
    "SECURE_IMPORT_GUARD_KEY",
    "SecureBackupError",
    "export_encrypted_backup",
    "import_encrypted_backup",
    "is_secure_import_in_progress",
    "parse_encrypted_backup_manifest",
]
