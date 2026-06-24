"""Encrypted backup facade for the UI.

Wraps ``secure_backup_service`` so the UI can export/import ``.wtbackup`` files
without importing ``worktrace.security`` or ``worktrace.db`` directly.
"""

from __future__ import annotations

from pathlib import Path

from ..services import secure_backup_service
from ..services.secure_backup_service import (
    BackupCorruptedError,
    BackupDecryptionError,
    BackupManifestInfo,
    BackupVersionNotSupportedError,
    ImportResult,
    SecureBackupError,
)


def export_encrypted_backup(output_path: str | Path, passphrase: str) -> str:
    """Export the current local database to an encrypted ``.wtbackup`` file.

    Returns the absolute path of the written file as a string.
    """
    return str(secure_backup_service.export_encrypted_backup(output_path, passphrase))


def import_encrypted_backup(
    input_path: str | Path,
    passphrase: str,
    mode: str = "replace",
) -> ImportResult:
    """Import an encrypted ``.wtbackup`` file into the current local database."""
    return secure_backup_service.import_encrypted_backup(input_path, passphrase, mode)


def parse_encrypted_backup_manifest(input_path: str | Path) -> BackupManifestInfo:
    """Parse the non-sensitive manifest from a ``.wtbackup`` file.

    Does not decrypt the payload and does not require a passphrase.
    """
    return secure_backup_service.parse_encrypted_backup_manifest(input_path)


__all__ = [
    "BackupCorruptedError",
    "BackupDecryptionError",
    "BackupManifestInfo",
    "BackupVersionNotSupportedError",
    "ImportResult",
    "SecureBackupError",
    "export_encrypted_backup",
    "import_encrypted_backup",
    "parse_encrypted_backup_manifest",
]
