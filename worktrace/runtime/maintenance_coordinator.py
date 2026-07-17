"""Explicit composition-root owner for runtime maintenance capabilities."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..services import secure_backup_service
from ..services.runtime_snapshot_barrier import consistent_snapshot

if TYPE_CHECKING:
    from .app_runtime import AppRuntime


class RuntimeMaintenanceCoordinator:
    """Coordinate backup/export maintenance with one concrete AppRuntime."""

    def __init__(self, runtime: "AppRuntime") -> None:
        self._runtime = runtime

    def export_encrypted_backup(self, output_path: str | Path, passphrase: str) -> Path:
        with consistent_snapshot(self._runtime.quiesce_collection_now):
            return secure_backup_service.export_encrypted_backup(
                output_path,
                passphrase,
            )

    def import_encrypted_backup(
        self,
        input_path: str | Path,
        passphrase: str,
        mode: str = "replace",
    ) -> secure_backup_service.ImportResult:
        return secure_backup_service.import_encrypted_backup(
            input_path,
            passphrase,
            mode,
            pause_handler=self._runtime.quiesce_collection_now,
            reset_handler=self._runtime.reset_collection_runtime_now,
        )

    def parse_encrypted_backup_manifest(
        self,
        input_path: str | Path,
    ) -> secure_backup_service.BackupManifestInfo:
        return secure_backup_service.parse_encrypted_backup_manifest(input_path)

    def is_secure_import_in_progress(self) -> bool:
        return secure_backup_service.is_secure_import_in_progress()


__all__ = ["RuntimeMaintenanceCoordinator"]
