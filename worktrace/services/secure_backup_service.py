"""Encrypted backup facade with an explicit payload compatibility matrix.

The stable encryption, staging, replacement and maintenance implementation lives
in ``secure_backup_core``. This facade owns portable payload versions and
normalizes supported legacy payloads before they enter that core.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from functools import lru_cache
from typing import Any

from ..constants import TIME_FORMAT
from . import secure_backup_core as _core

PAYLOAD_FORMAT = _core.PAYLOAD_FORMAT
PAYLOAD_VERSION = 5
SCHEMA_VERSION = str(_core.CURRENT_SCHEMA_VERSION)
BACKUP_FILE_SUFFIX = _core.BACKUP_FILE_SUFFIX
MAX_BACKUP_FILE_BYTES = _core.MAX_BACKUP_FILE_BYTES
MAX_BACKUP_PAYLOAD_BYTES = _core.MAX_BACKUP_PAYLOAD_BYTES
MIGRATABLE_SETTINGS = _core.MIGRATABLE_SETTINGS
EXCLUDED_TABLES = _core.EXCLUDED_TABLES

_V4_EXPORT_TABLES: tuple[str, ...] = tuple(_core.EXPORT_TABLES)
EXPORT_TABLES: tuple[str, ...] = (*_V4_EXPORT_TABLES, "activity_inference_job")
_V4_SCHEMA8_FINGERPRINT = _core._LEGACY_BACKUP_SCHEMA_FINGERPRINTS["8"]
_JOB_INDEX_SQL = """CREATE INDEX IF NOT EXISTS idx_activity_inference_job_runnable
ON activity_inference_job(status, next_attempt_at, activity_id);

"""
_LEGACY_V10_INTERNAL_SCHEMA_SQL = """CREATE TABLE IF NOT EXISTS data_generation_state (
    namespace TEXT PRIMARY KEY CHECK(length(trim(namespace)) > 0),
    generation INTEGER NOT NULL CHECK(generation >= 0)
);

INSERT INTO data_generation_state(namespace, generation)
VALUES
    ('report_structure', 0),
    ('classification_catalog', 0),
    ('settings', 0),
    ('privacy_catalog', 0),
    ('database_replacement', 0)
ON CONFLICT(namespace) DO NOTHING;

CREATE TABLE IF NOT EXISTS activity_resource_repair_job (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    policy_version INTEGER NOT NULL CHECK(policy_version > 0),
    status TEXT NOT NULL CHECK(status IN ('pending', 'running', 'completed', 'failed')),
    cursor_activity_id INTEGER NOT NULL DEFAULT 0 CHECK(cursor_activity_id >= 0),
    processed_count INTEGER NOT NULL DEFAULT 0 CHECK(processed_count >= 0),
    repaired_count INTEGER NOT NULL DEFAULT 0 CHECK(repaired_count >= 0),
    failed_count INTEGER NOT NULL DEFAULT 0 CHECK(failed_count >= 0),
    unknown_count INTEGER NOT NULL DEFAULT 0 CHECK(unknown_count >= 0),
    last_error TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);
"""
_ALLOWED_JOB_REASONS = {"closed_activity", "legacy_retry"}
_ALLOWED_JOB_STATUSES = {"pending", "failed"}
_ALLOWED_JOB_ERROR_CODES = {
    "data_repair_required",
    "database_busy",
    "database_generation_changed",
    "secure_import_in_progress",
    "unexpected_failure",
}

_core.PAYLOAD_VERSION = PAYLOAD_VERSION
_core.SCHEMA_VERSION = SCHEMA_VERSION
_core.EXPORT_TABLES = EXPORT_TABLES
_core._DELETE_ORDER = (
    "activity_inference_job",
    *_core._DELETE_ORDER,
)


@lru_cache(maxsize=1)
def _legacy_v10_schema_fingerprint() -> str:
    reference = sqlite3.connect(":memory:")
    reference.row_factory = sqlite3.Row
    try:
        reference.executescript(_core.read_schema_sql())
        reference.executescript(_LEGACY_V10_INTERNAL_SCHEMA_SQL)
        reference.executescript(
            _core.read_schema_indexes_sql().replace(_JOB_INDEX_SQL, "")
        )
        return _core.schema_fingerprint(reference)
    finally:
        reference.close()


def _parse_and_validate_payload(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_BACKUP_PAYLOAD_BYTES:
        raise _core.BackupCorruptedError("backup file is invalid or corrupted")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _core.BackupCorruptedError(
            "backup file is invalid or corrupted"
        ) from exc
    if not isinstance(data, dict) or data.get("format") != PAYLOAD_FORMAT:
        raise _core.BackupCorruptedError("backup file is invalid or corrupted")

    version = data.get("version")
    schema_version = str(data.get("schema_version") or "")
    fingerprint = str(data.get("schema_fingerprint") or "")
    matrix: dict[tuple[object, str], tuple[str, tuple[str, ...]]] = {
        (5, SCHEMA_VERSION): (_core.expected_schema_fingerprint(), EXPORT_TABLES),
        (4, "10"): (_legacy_v10_schema_fingerprint(), _V4_EXPORT_TABLES),
        (4, "8"): (_V4_SCHEMA8_FINGERPRINT, _V4_EXPORT_TABLES),
    }
    contract = matrix.get((version, schema_version))
    if contract is None:
        raise _core.BackupVersionNotSupportedError(
            "backup version is not supported"
        )
    required_fingerprint, required_tables = contract
    if fingerprint != required_fingerprint:
        raise _core.BackupCorruptedError("backup file is invalid or corrupted")

    tables = data.get("tables")
    if not isinstance(tables, dict) or set(tables) != set(required_tables):
        raise _core.BackupCorruptedError("backup file is invalid or corrupted")
    for rows in tables.values():
        if not isinstance(rows, list) or any(
            not isinstance(row, dict) for row in rows
        ):
            raise _core.BackupCorruptedError("backup file is invalid or corrupted")

    if version == 5:
        return data
    return _normalize_v4_payload(data)


def _normalize_v4_payload(data: dict[str, Any]) -> dict[str, Any]:
    tables = {
        str(name): [dict(row) for row in rows]
        for name, rows in dict(data["tables"]).items()
    }
    activities = {
        int(row["id"]): row
        for row in tables["activity_log"]
        if row.get("id") is not None
    }
    jobs: list[dict[str, Any]] = []
    seen: set[int] = set()
    for assignment in tables["activity_project_assignment"]:
        try:
            activity_id = int(assignment["activity_id"])
            confidence = int(assignment.get("confidence") or 0)
        except (KeyError, TypeError, ValueError) as exc:
            raise _core.BackupCorruptedError(
                "backup file is invalid or corrupted"
            ) from exc
        if confidence != -1:
            continue
        assignment["confidence"] = 0
        activity = activities.get(activity_id)
        if not _legacy_retry_eligible(activity, assignment) or activity_id in seen:
            continue
        timestamp = str(
            activity.get("updated_at")
            or activity.get("end_time")
            or activity.get("created_at")
            or ""
        )
        jobs.append(
            {
                "activity_id": activity_id,
                "reason": "legacy_retry",
                "status": "pending",
                "attempt_count": 0,
                "next_attempt_at": None,
                "last_error_code": None,
                "created_at": timestamp,
                "updated_at": timestamp,
            }
        )
        seen.add(activity_id)
    tables["activity_inference_job"] = jobs
    normalized = dict(data)
    normalized["tables"] = tables
    return normalized


def _legacy_retry_eligible(
    activity: dict[str, Any] | None,
    assignment: dict[str, Any],
) -> bool:
    if activity is None:
        return False
    return bool(
        activity.get("end_time") is not None
        and str(activity.get("status") or "") == "normal"
        and not int(activity.get("is_hidden") or 0)
        and not int(activity.get("is_deleted") or 0)
        and not int(assignment.get("is_manual") or 0)
        and str(assignment.get("source") or "") == "uncategorized"
    )


def _validate_staging_database_with_jobs(conn: sqlite3.Connection) -> None:
    _ORIGINAL_STAGING_VALIDATOR(conn)
    if conn.execute(
        "SELECT 1 FROM activity_project_assignment WHERE confidence < 0 LIMIT 1"
    ).fetchone():
        raise _core.BackupValidationError("legacy inference sentinel")
    rows = conn.execute(
        """
        SELECT job.*, activity.end_time, activity.status AS activity_status,
               activity.is_hidden, activity.is_deleted,
               assignment.is_manual, assignment.source AS assignment_source
        FROM activity_inference_job job
        JOIN activity_log activity ON activity.id = job.activity_id
        LEFT JOIN activity_project_assignment assignment
          ON assignment.activity_id = job.activity_id
        ORDER BY job.activity_id
        """
    ).fetchall()
    for row in rows:
        if str(row["reason"] or "") not in _ALLOWED_JOB_REASONS:
            raise _core.BackupValidationError("inference job reason")
        status = str(row["status"] or "")
        if status not in _ALLOWED_JOB_STATUSES:
            raise _core.BackupValidationError("inference job status")
        attempts = int(row["attempt_count"] or 0)
        if attempts < 0:
            raise _core.BackupValidationError("inference job attempts")
        error_code = row["last_error_code"]
        if error_code is not None and str(error_code) not in _ALLOWED_JOB_ERROR_CODES:
            raise _core.BackupValidationError("inference job error")
        if status == "failed" and (attempts <= 0 or error_code is None):
            raise _core.BackupValidationError("inference job failed state")
        for key in ("created_at", "updated_at"):
            _require_timestamp(row[key])
        if row["next_attempt_at"] is not None:
            _require_timestamp(row["next_attempt_at"])
        if (
            row["end_time"] is None
            or str(row["activity_status"] or "") != "normal"
            or int(row["is_hidden"] or 0)
            or int(row["is_deleted"] or 0)
            or int(row["is_manual"] or 0)
            or str(row["assignment_source"] or "") == "midnight_anchor"
        ):
            raise _core.BackupValidationError("inference job activity")


def _require_timestamp(value: object) -> None:
    try:
        datetime.strptime(str(value or ""), TIME_FORMAT)
    except (TypeError, ValueError) as exc:
        raise _core.BackupValidationError("inference job timestamp") from exc


_ORIGINAL_STAGING_VALIDATOR = _core.validate_staging_database
_core.validate_staging_database = _validate_staging_database_with_jobs
_core._parse_and_validate_payload = _parse_and_validate_payload

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

export_encrypted_backup = _core.export_encrypted_backup
import_encrypted_backup = _core.import_encrypted_backup
parse_encrypted_backup_manifest = _core.parse_encrypted_backup_manifest
is_secure_import_in_progress = _core.is_secure_import_in_progress
register_collector_pause_handler = _core.register_collector_pause_handler
clear_collector_pause_handler = _core.clear_collector_pause_handler
register_collector_reset_handler = _core.register_collector_reset_handler
clear_collector_reset_handler = _core.clear_collector_reset_handler


def __getattr__(name: str):
    return getattr(_core, name)


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
