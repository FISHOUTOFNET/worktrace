"""Encrypted backup facade for the UI.

Backup consistency and replacement maintenance are owned by the application
use cases in ``secure_backup_service`` rather than by this transport facade.
"""

from __future__ import annotations

from pathlib import Path

from ..services import secure_backup_service
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
