"""Settings / Privacy status facade + bridge tests.

These tests verify the named settings/privacy capabilities and assert that
read-only status payloads do not expose paths, clipboard content, passphrases,
tracebacks, or unintended write-side actions.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import patch

import pytest

from tests.support import runtime_state_fixture
from tests.support.application import build_test_bridge
from worktrace.api import settings_api
from worktrace.api.backup_api import BackupManifestInfo
from worktrace.api.settings_api import (
    accept_first_run_notice_for_webview,
    clear_all_local_data_for_webview,
    export_encrypted_backup_for_webview,
    get_first_run_notice_for_webview,
    get_settings_privacy_status,
    import_encrypted_backup_for_webview,
    preview_encrypted_backup_manifest_for_webview,
    set_clipboard_capture_enabled_for_webview,
)
from worktrace.services import database_maintenance_service, privacy_gate_service
from worktrace.services.installation_metadata_store import set_privacy_notice_version
from worktrace.services.secure_backup_service import (
    BackupCorruptedError,
    BackupDecryptionError,
    BackupImportInProgressError,
    BackupVersionNotSupportedError,
    ImportResult,
    SecureBackupError,
)
from worktrace.services.settings_service import set_setting

pytestmark = [pytest.mark.security_privacy, pytest.mark.integration, pytest.mark.db]


def _set_notice_accepted(accepted: bool) -> None:
    set_privacy_notice_version("1" if accepted else "")


SENSITIVE_EXPORT_PATH = "C:\\TestSettings-Alpha-7Q2\\exports"
SENSITIVE_CLIPBOARD_TOKEN = "TestClipboard-Epsilon-Secret-1W4"
SENSITIVE_PASSPHRASE = "TestPassphrase-Delta-Secret-9XK"

MAINTENANCE_KEYS = {
    "maintenance_in_progress",
    "maintenance_restored",
    "recovery_blocked",
    "blocked_reason",
    "collector_running",
    "collector_status",
    "user_paused",
}


def test_api_returns_success_payload_with_required_keys(temp_db) -> None:
    result = get_settings_privacy_status()
    assert isinstance(result, dict)
    assert result.get("ok") is True
    status = result.get("status")
    assert isinstance(status, dict)
    for key in (
        "page",
        "storage_model",
        "clipboard_capture_enabled",
        "export_path_configured",
        *sorted(MAINTENANCE_KEYS),
        "encrypted_backup",
        "destructive_actions",
        "first_run_notice",
    ):
        assert key in status, f"status missing required key: {key}"
    assert status["page"] == "settings_privacy"
    assert status["storage_model"] == "local_only"


def test_api_clipboard_capture_enabled_reflects_setting(temp_db) -> None:
    set_setting("clipboard_capture_enabled", "false")
    assert get_settings_privacy_status()["status"]["clipboard_capture_enabled"] is False
    set_setting("clipboard_capture_enabled", "true")
    assert get_settings_privacy_status()["status"]["clipboard_capture_enabled"] is True


def test_api_export_path_configured_is_bool_and_does_not_leak_path(temp_db) -> None:
    set_setting("export_path", "")
    status_empty = get_settings_privacy_status()["status"]
    assert status_empty["export_path_configured"] is False
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    result = get_settings_privacy_status()
    assert result["status"]["export_path_configured"] is True
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_EXPORT_PATH not in serialized
    assert "C:\\" not in serialized
    assert "TestSettings-Alpha" not in serialized


def test_api_maintenance_fields_have_exact_types(temp_db) -> None:
    status = get_settings_privacy_status()["status"]
    assert type(status["maintenance_in_progress"]) is bool
    assert type(status["maintenance_restored"]) is bool
    assert type(status["recovery_blocked"]) is bool
    assert status["blocked_reason"] is None or isinstance(status["blocked_reason"], str)
    assert type(status["collector_running"]) is bool
    assert isinstance(status["collector_status"], str)
    assert type(status["user_paused"]) is bool


def test_api_maintenance_in_progress_reflects_canonical_gate(temp_db) -> None:
    with database_maintenance_service.consistent_snapshot("settings_status_contract"):
        status = get_settings_privacy_status()["status"]
        assert status["maintenance_in_progress"] is True
        assert status["maintenance_restored"] is False
        assert status["recovery_blocked"] is False
    status = get_settings_privacy_status()["status"]
    assert status["maintenance_in_progress"] is False
    assert status["maintenance_restored"] is True
    assert status["recovery_blocked"] is False


def test_failed_closed_is_blocked_but_not_reported_as_in_progress(temp_db) -> None:
    coordinator = database_maintenance_service.MAINTENANCE_COORDINATOR
    coordinator._latch_fail_closed("test_restore_failed")
    try:
        status = get_settings_privacy_status()["status"]
        assert status["maintenance_in_progress"] is False
        assert status["maintenance_restored"] is False
        assert status["recovery_blocked"] is True
        assert status["blocked_reason"] == "test_restore_failed"
    finally:
        with coordinator._state_lock:
            coordinator._blocked_reason = None
            coordinator._phase = database_maintenance_service.MaintenancePhase.IDLE


def test_api_encrypted_backup_availability_fields_are_present(temp_db) -> None:
    enc = get_settings_privacy_status()["status"]["encrypted_backup"]
    assert enc == {
        "supported": True,
        "export_available_in_webview": True,
        "import_available_in_webview": True,
        "manifest_preview_available_in_webview": True,
    }


def test_api_destructive_clear_all_availability_is_true(temp_db) -> None:
    destructive = get_settings_privacy_status()["status"]["destructive_actions"]
    assert destructive["clear_all_local_data_available_in_webview"] is True


def test_api_payload_is_json_serializable(temp_db) -> None:
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    set_setting("clipboard_capture_enabled", "true")
    result = get_settings_privacy_status()
    assert json.loads(json.dumps(result, ensure_ascii=False))["ok"] is True


def test_api_payload_does_not_leak_sensitive_tokens(temp_db) -> None:
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    set_setting("clipboard_capture_enabled", "true")
    runtime_state_fixture.set_setting(
        "current_activity_snapshot",
        '{"clipboard":"' + SENSITIVE_CLIPBOARD_TOKEN + '"}',
    )
    serialized = json.dumps(get_settings_privacy_status(), ensure_ascii=False)
    for token in (
        SENSITIVE_EXPORT_PATH,
        SENSITIVE_CLIPBOARD_TOKEN,
        SENSITIVE_PASSPHRASE,
        "current_activity_snapshot",
        "window_title",
        "file_path_hint",
        "path_hint",
        "passphrase",
        ".wtbackup",
        "Traceback",
        "sqlite3.",
    ):
        assert token not in serialized


def test_api_does_not_call_write_actions_during_status_read(temp_db) -> None:
    assert not hasattr(settings_api, "set_setting_value")
    with patch.object(settings_api, "clear_all_local_data") as mock_clear, patch.object(
        settings_api, "set_clipboard_capture_enabled"
    ) as mock_set_clip, patch(
        "worktrace.api.backup_api.export_encrypted_backup"
    ) as mock_export, patch(
        "worktrace.api.backup_api.import_encrypted_backup"
    ) as mock_import, patch(
        "worktrace.api.backup_api.parse_encrypted_backup_manifest"
    ) as mock_manifest:
        get_settings_privacy_status()
        mock_clear.assert_not_called()
        mock_set_clip.assert_not_called()
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()


def test_api_does_not_change_schema(temp_db) -> None:
    from worktrace.db import get_connection

    with get_connection() as conn:
        expected_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    get_settings_privacy_status()
    with get_connection() as conn:
        actual_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert expected_tables == actual_tables


def test_bridge_method_exists_on_composed_webview_bridge() -> None:
    assert callable(getattr(build_test_bridge(), "get_settings_privacy_status", None))


def test_bridge_returns_narrow_success_payload(temp_db) -> None:
    result = build_test_bridge().get_settings_privacy_status()
    assert set(result) == {"ok", "status"}
    assert result["ok"] is True
    assert set(result["status"]) == {
        "page",
        "storage_model",
        "clipboard_capture_enabled",
        "export_path_configured",
        *MAINTENANCE_KEYS,
        "encrypted_backup",
        "destructive_actions",
        "first_run_notice",
    }
