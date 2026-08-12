"""Presentation-safe application service decorators for external-state warnings."""

from __future__ import annotations

from ..api.application_capabilities import (
    BackupApplicationService,
    SettingsApplicationService,
)


def _surface_external_warning(result: dict) -> dict:
    payload = dict(result)
    warning = str(payload.get("external_state_warning") or "").strip()
    if payload.get("ok") is True and warning:
        message = str(payload.get("message") or "").strip()
        payload["message"] = f"{message}；{warning}" if message else warning
    return payload


class WarningAwareSettingsApplicationService(SettingsApplicationService):
    def clear_all_local_data_for_webview(self, confirm_text):
        return _surface_external_warning(
            super().clear_all_local_data_for_webview(confirm_text)
        )


class WarningAwareBackupApplicationService(BackupApplicationService):
    def import_encrypted_backup_for_webview(
        self,
        input_path,
        passphrase,
        confirm_text,
    ):
        return _surface_external_warning(
            super().import_encrypted_backup_for_webview(
                input_path,
                passphrase,
                confirm_text,
            )
        )


__all__ = [
    "WarningAwareBackupApplicationService",
    "WarningAwareSettingsApplicationService",
]
