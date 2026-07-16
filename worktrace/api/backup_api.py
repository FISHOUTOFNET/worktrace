"""Encrypted backup facade for the UI.

The facade acquires a consistent runtime snapshot for export. Import remains
owned by the secure backup service's destructive replacement coordinator.
"""

from __future__ import annotations

from pathlib import Path

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


def export_encrypted_backup(output_path: str | Path, passphrase: str) -> str:
    with consistent_snapshot():
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
) -> ImportResult:
    return secure_backup_service.import_encrypted_backup(input_path, passphrase, mode)


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
