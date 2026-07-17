"""Encrypted backup facade with explicit runtime capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..services import secure_backup_service
from ..services.runtime_snapshot_barrier import consistent_snapshot
from ..services.secure_backup_service import (
    BackupCorruptedError,
    BackupDecryptionError,
    BackupImportInProgressError,
    BackupManifestInfo,
    BackupVersionNotSupportedError,
    ImportResult,
    SecureBackupError,
)
from ..services.settings_service import get_setting


def _inactive_runtime_quiesce(timeout_seconds: float = 5.0) -> dict[str, Any]:
    if (get_setting("collector_status", "stopped") or "stopped") == "running":
        return {"ok": False, "error": "runtime_quiesce_capability_required"}
    return {"ok": True, "collector_active": False}


def export_encrypted_backup(
    output_path: str | Path,
    passphrase: str,
    *,
    quiesce_handler: Any | None = None,
) -> str:
    handler = quiesce_handler or _inactive_runtime_quiesce
    with consistent_snapshot(handler):
        return str(
            secure_backup_service.export_encrypted_backup(
                output_path,
                passphrase,
            )
        )


def import_encrypted_backup(
    input_path: str | Path,
    passphrase: str,
    mode: str = "replace",
    *,
    pause_handler: Any | None = None,
    reset_handler: Any | None = None,
) -> ImportResult:
    return secure_backup_service.import_encrypted_backup(
        input_path,
        passphrase,
        mode,
        pause_handler=pause_handler,
        reset_handler=reset_handler,
    )


def parse_encrypted_backup_manifest(input_path: str | Path) -> BackupManifestInfo:
    return secure_backup_service.parse_encrypted_backup_manifest(input_path)


def is_secure_import_in_progress() -> bool:
    return secure_backup_service.is_secure_import_in_progress()


__all__ = [
    "BackupCorruptedError",
    "BackupDecryptionError",
    "BackupImportInProgressError",
    "BackupManifestInfo",
    "BackupVersionNotSupportedError",
    "ImportResult",
    "SecureBackupError",
    "export_encrypted_backup",
    "import_encrypted_backup",
    "is_secure_import_in_progress",
    "parse_encrypted_backup_manifest",
]
