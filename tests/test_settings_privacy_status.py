"""Settings / Privacy status facade + bridge tests.

These tests verify the ``settings_api.get_settings_privacy_status`` facade,
the ``settings_api.set_clipboard_capture_enabled_for_webview`` write facade,
the ``settings_api.export_encrypted_backup_for_webview`` and
``settings_api.preview_encrypted_backup_manifest_for_webview`` facades, the
backup import ``settings_api.import_encrypted_backup_for_webview`` and
``settings_api.clear_all_local_data_for_webview`` facades, the first-run notice
``settings_api.get_first_run_notice_for_webview`` and
``settings_api.accept_first_run_notice_for_webview`` facades, and the
corresponding ``WebViewBridge`` methods. They assert the read-only status
payload and the clipboard capture toggle / backup export / manifest preview
/ backup import / clear-all / first-run notice write payloads never leak
paths, clipboard content, passphrases, tracebacks, or any unintended
write-side action surface.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import patch

import pytest

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
from worktrace.services.secure_backup_service import (
    BackupCorruptedError,
    BackupDecryptionError,
    BackupImportInProgressError,
    BackupVersionNotSupportedError,
    ImportResult,
    SecureBackupError,
)
from worktrace.services.settings_service import set_setting
from worktrace.webview_ui.bridge import WebViewBridge


# Distinctive sensitive markers used to verify the payload never echoes
# paths, clipboards, or passphrases even when those values are stored in
# the database-backed settings or filesystem.
SENSITIVE_EXPORT_PATH = "C:\\TestSettings-Alpha-7Q2\\exports"
SENSITIVE_CLIPBOARD_TOKEN = "TestClipboard-Epsilon-Secret-1W4"
SENSITIVE_PASSPHRASE = "TestPassphrase-Delta-Secret-9XK"


# --- API success payload -------------------------------------------------


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
        "secure_import_in_progress",
        "encrypted_backup",
        "destructive_actions",
        "first_run_notice",
    ):
        assert key in status, f"status missing required key: {key}"
    assert status["page"] == "settings_privacy"
    assert status["storage_model"] == "local_only"


def test_api_clipboard_capture_enabled_reflects_setting(temp_db) -> None:
    set_setting("clipboard_capture_enabled", "false")
    status_false = get_settings_privacy_status()["status"]
    assert status_false["clipboard_capture_enabled"] is False

    set_setting("clipboard_capture_enabled", "true")
    status_true = get_settings_privacy_status()["status"]
    assert status_true["clipboard_capture_enabled"] is True


def test_api_export_path_configured_is_bool_and_does_not_leak_path(temp_db) -> None:
    # Unset export path → False. Never echo the empty path string either.
    set_setting("export_path", "")
    status_empty = get_settings_privacy_status()["status"]
    assert isinstance(status_empty["export_path_configured"], bool)
    assert status_empty["export_path_configured"] is False
    serialized = json.dumps(get_settings_privacy_status(), ensure_ascii=False)
    assert SENSITIVE_EXPORT_PATH not in serialized

    # Configured export path → True, but the path string itself must never
    # appear in the payload.
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    result = get_settings_privacy_status()
    status = result["status"]
    assert isinstance(status["export_path_configured"], bool)
    assert status["export_path_configured"] is True
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_EXPORT_PATH not in serialized
    # Also forbid raw "export_path" key collisions and basename leakage.
    assert "C:\\\\" not in serialized
    assert "TestSettings-Alpha" not in serialized


def test_api_secure_import_in_progress_field_is_bool(temp_db) -> None:
    # The facade reads this through backup_api.is_secure_import_in_progress.
    # The field must always be a bool regardless of the underlying state.
    result = get_settings_privacy_status()
    status = result["status"]
    assert isinstance(status["secure_import_in_progress"], bool)


def test_api_secure_import_in_progress_reflects_backup_guard(temp_db) -> None:
    set_setting("secure_import_in_progress", "true")
    status = get_settings_privacy_status()["status"]
    assert status["secure_import_in_progress"] is True

    set_setting("secure_import_in_progress", "false")
    status = get_settings_privacy_status()["status"]
    assert status["secure_import_in_progress"] is False


def test_api_encrypted_backup_availability_fields_are_present(temp_db) -> None:
    # Export, manifest preview, and import are all available in WebView.
    status = get_settings_privacy_status()["status"]
    enc = status["encrypted_backup"]
    assert isinstance(enc, dict)
    assert enc["supported"] is True
    assert enc["export_available_in_webview"] is True
    assert enc["import_available_in_webview"] is True
    assert enc["manifest_preview_available_in_webview"] is True


def test_api_destructive_clear_all_availability_is_true(temp_db) -> None:
    # clear-all-local-data is available in WebView behind the explicit
    # Chinese confirmation literal.
    status = get_settings_privacy_status()["status"]
    destructive = status["destructive_actions"]
    assert isinstance(destructive, dict)
    assert destructive["clear_all_local_data_available_in_webview"] is True


def test_api_payload_is_json_serializable(temp_db) -> None:
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    set_setting("clipboard_capture_enabled", "true")
    set_setting("secure_import_in_progress", "true")
    result = get_settings_privacy_status()
    # Must round-trip through JSON without raising. This catches any
    # Path / datetime / set / bytes / non-serializable leak.
    serialized = json.dumps(result, ensure_ascii=False)
    parsed = json.loads(serialized)
    assert parsed["ok"] is True


def test_api_payload_does_not_leak_sensitive_tokens(temp_db) -> None:
    # Even when sensitive values are stored in settings, the payload must
    # never carry path strings, clipboard content, or passphrases.
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    set_setting("clipboard_capture_enabled", "true")
    set_setting("current_activity_snapshot", '{"clipboard":"' + SENSITIVE_CLIPBOARD_TOKEN + '"}')
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
        assert token not in serialized, f"payload leaks sensitive token: {token!r}"


def test_api_does_not_call_write_actions_during_status_read(temp_db) -> None:
    # The status read must never invoke any write-side action: no backup
    # export / import / manifest, no clear_all_local_data, no set_setting_value
    # / set_clipboard_capture_enabled. Mock each callable and assert the
    # status read leaves them untouched.
    with patch.object(settings_api, "clear_all_local_data") as mock_clear, \
            patch.object(settings_api, "set_setting_value") as mock_set_value, \
            patch.object(settings_api, "set_clipboard_capture_enabled") as mock_set_clip, \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest:
        get_settings_privacy_status()
        mock_clear.assert_not_called()
        mock_set_value.assert_not_called()
        mock_set_clip.assert_not_called()
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()


def test_api_does_not_change_schema(temp_db) -> None:
    # The status read is a pure read; the schema must not change.
    from worktrace.db import get_connection

    expected_tables = {
        row[0]
        for row in get_connection()
        .execute("SELECT name FROM sqlite_master WHERE type='table'")
        .fetchall()
    }
    get_settings_privacy_status()
    actual_tables = {
        row[0]
        for row in get_connection()
        .execute("SELECT name FROM sqlite_master WHERE type='table'")
        .fetchall()
    }
    assert expected_tables == actual_tables


# --- Bridge --------------------------------------------------------------


def test_bridge_method_exists_on_composed_webview_bridge() -> None:
    """The composed WebViewBridge must expose get_settings_privacy_status."""
    bridge = WebViewBridge()
    method = getattr(bridge, "get_settings_privacy_status", None)
    assert callable(method), (
        "WebViewBridge must expose get_settings_privacy_status for settings privacy status contract"
    )


def test_bridge_returns_narrow_success_payload(temp_db) -> None:
    bridge = WebViewBridge()
    result = bridge.get_settings_privacy_status()
    assert isinstance(result, dict)
    assert result.get("ok") is True
    status = result.get("status")
    assert isinstance(status, dict)
    # The bridge payload must only contain the ok + status envelope. No
    # extra keys are allowed to leak from the underlying facade.
    assert set(result.keys()) == {"ok", "status"}
    assert set(status.keys()) == {
        "page",
        "storage_model",
        "clipboard_capture_enabled",
        "export_path_configured",
        "secure_import_in_progress",
        "encrypted_backup",
        "destructive_actions",
        "first_run_notice",
    }


def test_bridge_exception_collapses_to_generic_error(temp_db, caplog) -> None:
    # When the underlying facade raises, the bridge must collapse the
    # exception to the generic Chinese message without surfacing the
    # traceback, exception type, or any raw field.
    bridge = WebViewBridge()
    with patch.object(
        settings_api,
        "get_settings_privacy_status",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = bridge.get_settings_privacy_status()
    assert result == {"ok": False, "error": "加载设置状态失败"}
    # The bridge must not surface the raw exception text or passphrase in
    # the returned payload.
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_PASSPHRASE not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


def test_bridge_does_not_call_write_actions(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(settings_api, "clear_all_local_data") as mock_clear, \
            patch.object(settings_api, "set_setting_value") as mock_set_value, \
            patch.object(settings_api, "set_clipboard_capture_enabled") as mock_set_clip, \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest:
        bridge.get_settings_privacy_status()
        mock_clear.assert_not_called()
        mock_set_value.assert_not_called()
        mock_set_clip.assert_not_called()
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()


def test_bridge_method_signature_has_no_required_args() -> None:
    # The bridge method takes no required arguments; it is a pure read.
    bridge = WebViewBridge()
    sig = inspect.signature(bridge.get_settings_privacy_status)
    for name, param in sig.parameters.items():
        assert param.default is not inspect.Parameter.empty, (
            f"bridge.get_settings_privacy_status parameter {name!r} must "
            "have a default; the JS side calls it with no arguments"
        )


# --- API write facade -----------------------------------------


def test_api_write_true_success_status_reflects_setting(temp_db) -> None:
    set_setting("clipboard_capture_enabled", "false")
    result = set_clipboard_capture_enabled_for_webview(True)
    assert result["ok"] is True
    assert result["status"]["clipboard_capture_enabled"] is True


def test_api_write_false_success_status_reflects_setting(temp_db) -> None:
    set_setting("clipboard_capture_enabled", "true")
    result = set_clipboard_capture_enabled_for_webview(False)
    assert result["ok"] is True
    assert result["status"]["clipboard_capture_enabled"] is False


def test_api_write_success_payload_has_only_ok_and_status(temp_db) -> None:
    result = set_clipboard_capture_enabled_for_webview(True)
    assert set(result.keys()) == {"ok", "status"}


def test_api_write_success_payload_is_json_serializable(temp_db) -> None:
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    result = set_clipboard_capture_enabled_for_webview(True)
    serialized = json.dumps(result, ensure_ascii=False)
    parsed = json.loads(serialized)
    assert parsed["ok"] is True


def test_api_write_payload_does_not_leak_sensitive_tokens(temp_db) -> None:
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    set_setting("current_activity_snapshot", '{"clipboard":"' + SENSITIVE_CLIPBOARD_TOKEN + '"}')
    result = set_clipboard_capture_enabled_for_webview(True)
    serialized = json.dumps(result, ensure_ascii=False)
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
        assert token not in serialized, f"write payload leaks sensitive token: {token!r}"


@pytest.mark.parametrize(
    "bad_value",
    [
        None,
        "true",
        "false",
        "1",
        "0",
        1,
        0,
        [],
        {},
        (),
        set(),
        object(),
    ],
)
def test_api_write_rejects_non_bool(temp_db, bad_value) -> None:
    set_setting("clipboard_capture_enabled", "true")
    result = set_clipboard_capture_enabled_for_webview(bad_value)  # type: ignore[arg-type]
    assert result == {"ok": False, "error": "请选择有效的剪贴板记录状态"}


@pytest.mark.parametrize(
    "bad_value",
    [
        None,
        "true",
        "false",
        "1",
        "0",
        1,
        0,
        [],
        {},
        (),
        set(),
        object(),
    ],
)
def test_api_write_non_bool_does_not_change_setting(temp_db, bad_value) -> None:
    set_setting("clipboard_capture_enabled", "true")
    set_clipboard_capture_enabled_for_webview(bad_value)  # type: ignore[arg-type]
    assert settings_api.is_clipboard_capture_enabled() is True

    set_setting("clipboard_capture_enabled", "false")
    set_clipboard_capture_enabled_for_webview(bad_value)  # type: ignore[arg-type]
    assert settings_api.is_clipboard_capture_enabled() is False


def test_api_write_setter_exception_returns_generic_error(temp_db) -> None:
    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = set_clipboard_capture_enabled_for_webview(True)
    assert result == {"ok": False, "error": "设置剪贴板记录失败"}


def test_api_write_exception_payload_does_not_leak_raw_exception(temp_db) -> None:
    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = set_clipboard_capture_enabled_for_webview(True)
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_PASSPHRASE not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


def test_api_write_does_not_call_backup_actions(temp_db) -> None:
    with patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest:
        set_clipboard_capture_enabled_for_webview(True)
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()


def test_api_write_does_not_call_clear_all_local_data(temp_db) -> None:
    with patch.object(settings_api, "clear_all_local_data") as mock_clear:
        set_clipboard_capture_enabled_for_webview(True)
        mock_clear.assert_not_called()


def test_api_write_does_not_change_schema(temp_db) -> None:
    from worktrace.db import get_connection

    expected_tables = {
        row[0]
        for row in get_connection()
        .execute("SELECT name FROM sqlite_master WHERE type='table'")
        .fetchall()
    }
    set_clipboard_capture_enabled_for_webview(True)
    actual_tables = {
        row[0]
        for row in get_connection()
        .execute("SELECT name FROM sqlite_master WHERE type='table'")
        .fetchall()
    }
    assert expected_tables == actual_tables


# --- Bridge write method --------------------------------------


def test_bridge_write_method_exists_on_composed_webview_bridge() -> None:
    bridge = WebViewBridge()
    method = getattr(bridge, "set_clipboard_capture_enabled", None)
    assert callable(method), (
        "WebViewBridge must expose set_clipboard_capture_enabled for settings capture contract"
    )


def test_bridge_write_method_signature_has_one_required_param() -> None:
    bridge = WebViewBridge()
    sig = inspect.signature(bridge.set_clipboard_capture_enabled)
    params = list(sig.parameters.values())
    assert len(params) == 1, (
        "bridge.set_clipboard_capture_enabled must take exactly one parameter"
    )
    param = params[0]
    assert param.name == "enabled", (
        f"parameter must be named 'enabled', got {param.name!r}"
    )
    assert param.default is inspect.Parameter.empty, (
        "the 'enabled' parameter must be required (no default)"
    )
    assert param.kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), "the 'enabled' parameter must not be *args or **kwargs"


def test_bridge_write_true_success(temp_db) -> None:
    set_setting("clipboard_capture_enabled", "false")
    bridge = WebViewBridge()
    result = bridge.set_clipboard_capture_enabled(True)
    assert result["ok"] is True
    assert result["status"]["clipboard_capture_enabled"] is True


def test_bridge_write_false_success(temp_db) -> None:
    set_setting("clipboard_capture_enabled", "true")
    bridge = WebViewBridge()
    result = bridge.set_clipboard_capture_enabled(False)
    assert result["ok"] is True
    assert result["status"]["clipboard_capture_enabled"] is False


def test_bridge_write_success_payload_has_only_ok_and_status(temp_db) -> None:
    bridge = WebViewBridge()
    result = bridge.set_clipboard_capture_enabled(True)
    assert set(result.keys()) == {"ok", "status"}


@pytest.mark.parametrize(
    "bad_value",
    [
        None,
        "true",
        "false",
        "1",
        "0",
        1,
        0,
        [],
        {},
        (),
        set(),
        object(),
    ],
)
def test_bridge_write_rejects_non_bool(temp_db, bad_value) -> None:
    set_setting("clipboard_capture_enabled", "true")
    bridge = WebViewBridge()
    result = bridge.set_clipboard_capture_enabled(bad_value)
    assert result == {"ok": False, "error": "请选择有效的剪贴板记录状态"}


@pytest.mark.parametrize(
    "bad_value",
    [
        None,
        "true",
        "false",
        "1",
        "0",
        1,
        0,
        [],
        {},
        (),
        set(),
        object(),
    ],
)
def test_bridge_write_non_bool_does_not_change_setting(temp_db, bad_value) -> None:
    set_setting("clipboard_capture_enabled", "true")
    bridge = WebViewBridge()
    bridge.set_clipboard_capture_enabled(bad_value)
    assert settings_api.is_clipboard_capture_enabled() is True

    set_setting("clipboard_capture_enabled", "false")
    bridge.set_clipboard_capture_enabled(bad_value)
    assert settings_api.is_clipboard_capture_enabled() is False


def test_bridge_write_api_exception_returns_generic_error(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled_for_webview",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = bridge.set_clipboard_capture_enabled(True)
    assert result == {"ok": False, "error": "设置剪贴板记录失败"}


def test_bridge_write_payload_does_not_leak_sensitive_tokens(temp_db) -> None:
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    set_setting("current_activity_snapshot", '{"clipboard":"' + SENSITIVE_CLIPBOARD_TOKEN + '"}')
    bridge = WebViewBridge()
    result = bridge.set_clipboard_capture_enabled(True)
    serialized = json.dumps(result, ensure_ascii=False)
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
        assert token not in serialized, f"bridge write payload leaks: {token!r}"


def test_bridge_write_api_exception_payload_does_not_leak(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled_for_webview",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = bridge.set_clipboard_capture_enabled(True)
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_PASSPHRASE not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


def test_bridge_write_does_not_call_backup_actions(temp_db) -> None:
    bridge = WebViewBridge()
    with patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest:
        bridge.set_clipboard_capture_enabled(True)
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()


def test_bridge_write_does_not_call_clear_all_local_data(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(settings_api, "clear_all_local_data") as mock_clear:
        bridge.set_clipboard_capture_enabled(True)
        mock_clear.assert_not_called()


def test_bridge_write_api_ok_false_passes_error_through(temp_db) -> None:
    # When the API facade returns ok=false with a stable Chinese error,
    # the bridge must pass that error through unchanged.
    bridge = WebViewBridge()
    api_result = {"ok": False, "error": "请选择有效的剪贴板记录状态"}
    with patch.object(
        settings_api,
        "set_clipboard_capture_enabled_for_webview",
        return_value=api_result,
    ):
        result = bridge.set_clipboard_capture_enabled(True)
    assert result == api_result


# --- API export facade ---------------------------------------


def test_api_export_success_returns_narrow_payload(temp_db) -> None:
    # Mock the backend export so no real file is written. The facade must
    # append .wtbackup if missing and return only ok / filename / message.
    with patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export:
        result = export_encrypted_backup_for_webview(
            "C:\\backups\\worktrace-backup",
            SENSITIVE_PASSPHRASE,
            SENSITIVE_PASSPHRASE,
        )
    assert result.get("ok") is True
    assert set(result.keys()) == {"ok", "filename", "message"}
    assert result["filename"] == "worktrace-backup.wtbackup"
    assert result["message"] == "加密备份已导出"
    # The backend must have been called with the .wtbackup-suffixed path.
    called_path = mock_export.call_args.args[0]
    assert called_path.lower().endswith(".wtbackup")
    # The returned filename must be the basename only — never the full path.
    serialized = json.dumps(result, ensure_ascii=False)
    assert "C:\\\\" not in serialized
    assert "backups" not in serialized
    assert SENSITIVE_PASSPHRASE not in serialized


def test_api_export_success_preserves_existing_wtbackup_suffix(temp_db) -> None:
    # When the user-chosen path already ends with .wtbackup (any case),
    # the facade must not append a second suffix.
    with patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export:
        result = export_encrypted_backup_for_webview(
            "C:\\backups\\My-Backup.WTBACKUP",
            SENSITIVE_PASSPHRASE,
            SENSITIVE_PASSPHRASE,
        )
    assert result.get("ok") is True
    assert result["filename"] == "My-Backup.WTBACKUP"
    called_path = mock_export.call_args.args[0]
    assert called_path == "C:\\backups\\My-Backup.WTBACKUP"


@pytest.mark.parametrize(
    "bad_path",
    [None, "", "   ", "\t\n", True, False, 1, 0, [], {}, (), set(), object()],
)
def test_api_export_rejects_invalid_output_path(temp_db, bad_path) -> None:
    result = export_encrypted_backup_for_webview(
        bad_path,  # type: ignore[arg-type]
        SENSITIVE_PASSPHRASE,
        SENSITIVE_PASSPHRASE,
    )
    assert result == {"ok": False, "error": "请选择有效的备份保存位置"}


@pytest.mark.parametrize(
    "bad_passphrase",
    [None, "", "   ", "\t\n", True, False, 1, 0, [], {}, (), set(), object()],
)
def test_api_export_rejects_invalid_passphrase(temp_db, bad_passphrase) -> None:
    result = export_encrypted_backup_for_webview(
        "C:\\backups\\worktrace-backup.wtbackup",
        bad_passphrase,  # type: ignore[arg-type]
        bad_passphrase if isinstance(bad_passphrase, str) else SENSITIVE_PASSPHRASE,
    )
    assert result == {"ok": False, "error": "请输入备份口令"}


def test_api_export_rejects_mismatched_confirm_passphrase(temp_db) -> None:
    result = export_encrypted_backup_for_webview(
        "C:\\backups\\worktrace-backup.wtbackup",
        SENSITIVE_PASSPHRASE,
        SENSITIVE_PASSPHRASE + "-typo",
    )
    assert result == {"ok": False, "error": "两次输入的备份口令不一致"}


def test_api_export_failure_collapses_to_generic_error(temp_db) -> None:
    # The service layer may raise an exception that carries sensitive
    # material in its message; the facade must collapse it to the stable
    # Chinese message and never leak the raw exception / path / passphrase.
    secret_msg = (
        "SECRET_PATH C:\\leak\\path SECRET_PASSPHRASE "
        + SENSITIVE_PASSPHRASE
        + " sqlite3.OperationalError"
    )
    with patch(
        "worktrace.api.backup_api.export_encrypted_backup",
        side_effect=RuntimeError(secret_msg),
    ):
        result = export_encrypted_backup_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup",
            SENSITIVE_PASSPHRASE,
            SENSITIVE_PASSPHRASE,
        )
    assert result == {"ok": False, "error": "导出加密备份失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        SENSITIVE_PASSPHRASE,
        "SECRET_PATH",
        "SECRET_PASSPHRASE",
        "RuntimeError",
        "Traceback",
        "sqlite3.",
        "C:\\\\leak",
        "leak\\\\path",
    ):
        assert token not in serialized, f"export failure leaks: {token!r}"


def test_api_export_does_not_call_import_or_manifest_or_clear_or_set(temp_db) -> None:
    with patch("worktrace.api.backup_api.export_encrypted_backup"), \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest, \
            patch.object(settings_api, "clear_all_local_data") as mock_clear, \
            patch.object(settings_api, "set_setting_value") as mock_set_value:
        export_encrypted_backup_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup",
            SENSITIVE_PASSPHRASE,
            SENSITIVE_PASSPHRASE,
        )
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()
        mock_clear.assert_not_called()
        mock_set_value.assert_not_called()


# --- API manifest preview facade -----------------------------


def _fake_manifest_info() -> BackupManifestInfo:
    return BackupManifestInfo(
        version=1,
        app_version="0.2.0",
        created_at="2026-06-29T12:00:00Z",
        kdf_algorithm="scrypt",
        payload_format="sqlite",
        payload_alg="aes-256-gcm",
    )


def test_api_manifest_success_returns_display_safe_payload(temp_db) -> None:
    with patch(
        "worktrace.api.backup_api.parse_encrypted_backup_manifest",
        return_value=_fake_manifest_info(),
    ):
        result = preview_encrypted_backup_manifest_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup"
        )
    assert result.get("ok") is True
    assert set(result.keys()) == {"ok", "filename", "manifest"}
    assert result["filename"] == "worktrace-backup.wtbackup"
    manifest = result["manifest"]
    assert set(manifest.keys()) == {
        "version",
        "app_version",
        "created_at",
        "kdf_algorithm",
        "payload_format",
        "payload_alg",
    }
    assert manifest["version"] == 1
    assert manifest["app_version"] == "0.2.0"
    assert manifest["created_at"] == "2026-06-29T12:00:00Z"
    assert manifest["kdf_algorithm"] == "scrypt"
    assert manifest["payload_format"] == "sqlite"
    assert manifest["payload_alg"] == "aes-256-gcm"
    # The full path must never appear in the payload.
    serialized = json.dumps(result, ensure_ascii=False)
    assert "C:\\\\" not in serialized
    assert "backups" not in serialized
    # No salt / ciphertext / payload / database content keys either.
    for forbidden in ("salt", "ciphertext", "payload_data", "db_content", "passphrase"):
        assert forbidden not in serialized, f"manifest leaks: {forbidden!r}"


@pytest.mark.parametrize(
    "bad_path",
    [None, "", "   ", "\t\n", True, False, 1, 0, [], {}, (), set(), object(),
     "C:\\backups\\worktrace-backup.csv",
     "C:\\backups\\worktrace-backup.zip",
     "C:\\backups\\worktrace-backup"],
)
def test_api_manifest_rejects_invalid_path(temp_db, bad_path) -> None:
    result = preview_encrypted_backup_manifest_for_webview(
        bad_path  # type: ignore[arg-type]
    )
    assert result == {"ok": False, "error": "请选择有效的加密备份文件"}


@pytest.mark.parametrize(
    "exc",
    [
        BackupCorruptedError("SECRET_CIPHERTEXT " + SENSITIVE_PASSPHRASE),
        BackupVersionNotSupportedError("v999 SECRET_SALT"),
        RuntimeError("SECRET_PATH C:\\leak " + SENSITIVE_PASSPHRASE + " sqlite3."),
    ],
)
def test_api_manifest_failure_collapses_to_generic_error(temp_db, exc) -> None:
    with patch(
        "worktrace.api.backup_api.parse_encrypted_backup_manifest",
        side_effect=exc,
    ):
        result = preview_encrypted_backup_manifest_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup"
        )
    assert result == {"ok": False, "error": "读取备份清单失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        SENSITIVE_PASSPHRASE,
        "SECRET_CIPHERTEXT",
        "SECRET_SALT",
        "SECRET_PATH",
        "RuntimeError",
        "BackupCorrupted",
        "BackupVersionNotSupported",
        "Traceback",
        "sqlite3.",
        "C:\\\\leak",
    ):
        assert token not in serialized, f"manifest failure leaks: {token!r}"


def test_api_manifest_does_not_call_import_or_export_or_clear_or_set(temp_db) -> None:
    with patch(
        "worktrace.api.backup_api.parse_encrypted_backup_manifest",
        return_value=_fake_manifest_info(),
    ), \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch.object(settings_api, "clear_all_local_data") as mock_clear, \
            patch.object(settings_api, "set_setting_value") as mock_set_value:
        preview_encrypted_backup_manifest_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup"
        )
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_clear.assert_not_called()
        mock_set_value.assert_not_called()


def test_api_manifest_does_not_require_passphrase(temp_db) -> None:
    # The manifest preview facade must accept a single path argument and
    # never require a passphrase parameter.
    sig = inspect.signature(preview_encrypted_backup_manifest_for_webview)
    params = list(sig.parameters.values())
    assert len(params) == 1
    assert params[0].name == "input_path"
    with patch(
        "worktrace.api.backup_api.parse_encrypted_backup_manifest",
        return_value=_fake_manifest_info(),
    ):
        result = preview_encrypted_backup_manifest_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup"
        )
    assert result["ok"] is True


# --- Bridge export + manifest methods ------------------------


def test_bridge_export_method_exists() -> None:
    bridge = WebViewBridge()
    method = getattr(bridge, "export_encrypted_backup", None)
    assert callable(method), (
        "WebViewBridge must expose export_encrypted_backup for encrypted backup contract"
    )


def test_bridge_export_method_signature_has_two_required_params() -> None:
    bridge = WebViewBridge()
    sig = inspect.signature(bridge.export_encrypted_backup)
    params = list(sig.parameters.values())
    assert len(params) == 2, (
        "bridge.export_encrypted_backup must take exactly two parameters"
    )
    for idx, name in enumerate(("passphrase", "confirm_passphrase")):
        param = params[idx]
        assert param.name == name, (
            f"parameter {idx} must be named {name!r}, got {param.name!r}"
        )
        assert param.default is inspect.Parameter.empty, (
            f"parameter {name!r} must be required (no default)"
        )
        assert param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ), f"parameter {name!r} must not be *args or **kwargs"


def test_bridge_preview_method_exists() -> None:
    bridge = WebViewBridge()
    method = getattr(bridge, "preview_encrypted_backup_manifest", None)
    assert callable(method), (
        "WebViewBridge must expose preview_encrypted_backup_manifest for encrypted backup contract"
    )


def test_bridge_preview_method_signature_has_zero_params() -> None:
    bridge = WebViewBridge()
    sig = inspect.signature(bridge.preview_encrypted_backup_manifest)
    params = list(sig.parameters.values())
    assert len(params) == 0, (
        "bridge.preview_encrypted_backup_manifest must take zero parameters"
    )


class _FakeWindow:
    """Minimal fake pywebview window for bridge dialog tests."""

    def __init__(self, dialog_result):
        self._dialog_result = dialog_result
        self.create_file_dialog_calls: list[dict] = []

    def create_file_dialog(self, dialog_type, **kwargs):
        self.create_file_dialog_calls.append(
            {"dialog_type": dialog_type, **kwargs}
        )
        if isinstance(self._dialog_result, Exception):
            raise self._dialog_result
        return self._dialog_result


def test_bridge_export_cancel_returns_stable_message(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(None))
    result = bridge.export_encrypted_backup(SENSITIVE_PASSPHRASE, SENSITIVE_PASSPHRASE)
    assert result == {"ok": False, "error": "已取消导出"}
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_PASSPHRASE not in serialized


def test_bridge_export_cancel_empty_list_returns_stable_message(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow([]))
    result = bridge.export_encrypted_backup(SENSITIVE_PASSPHRASE, SENSITIVE_PASSPHRASE)
    assert result == {"ok": False, "error": "已取消导出"}


def test_bridge_export_success_returns_narrow_payload(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    with patch("worktrace.api.backup_api.export_encrypted_backup"):
        result = bridge.export_encrypted_backup(
            SENSITIVE_PASSPHRASE, SENSITIVE_PASSPHRASE
        )
    assert result.get("ok") is True
    assert set(result.keys()) == {"ok", "filename", "message"}
    assert result["filename"] == "worktrace-backup.wtbackup"
    assert result["message"] == "加密备份已导出"
    serialized = json.dumps(result, ensure_ascii=False)
    assert "C:\\\\" not in serialized
    assert "backups" not in serialized
    assert SENSITIVE_PASSPHRASE not in serialized


def test_bridge_export_success_with_string_path(temp_db) -> None:
    # pywebview may return a bare string instead of a tuple/list.
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow("C:\\backups\\worktrace-backup.wtbackup"))
    with patch("worktrace.api.backup_api.export_encrypted_backup"):
        result = bridge.export_encrypted_backup(
            SENSITIVE_PASSPHRASE, SENSITIVE_PASSPHRASE
        )
    assert result.get("ok") is True
    assert result["filename"] == "worktrace-backup.wtbackup"


def test_bridge_export_dialog_exception_collapses(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(RuntimeError("dialog boom " + SENSITIVE_PASSPHRASE)))
    result = bridge.export_encrypted_backup(
        SENSITIVE_PASSPHRASE, SENSITIVE_PASSPHRASE
    )
    assert result == {"ok": False, "error": "导出加密备份失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_PASSPHRASE not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


def test_bridge_export_api_exception_collapses(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    with patch.object(
        settings_api,
        "export_encrypted_backup_for_webview",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = bridge.export_encrypted_backup(
            SENSITIVE_PASSPHRASE, SENSITIVE_PASSPHRASE
        )
    assert result == {"ok": False, "error": "导出加密备份失败"}


def test_bridge_export_does_not_call_import_or_clear(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    with patch("worktrace.api.backup_api.export_encrypted_backup"), \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch.object(settings_api, "clear_all_local_data") as mock_clear, \
            patch.object(settings_api, "set_setting_value") as mock_set_value:
        bridge.export_encrypted_backup(SENSITIVE_PASSPHRASE, SENSITIVE_PASSPHRASE)
        mock_import.assert_not_called()
        mock_clear.assert_not_called()
        mock_set_value.assert_not_called()


def test_bridge_export_uses_save_dialog_with_wtbackup_filter(temp_db) -> None:
    # The save dialog must be constrained to .wtbackup files and offer a
    # sensible default filename.
    bridge = WebViewBridge()
    fake_window = _FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",))
    bridge.set_window(fake_window)
    with patch("worktrace.api.backup_api.export_encrypted_backup"):
        bridge.export_encrypted_backup(SENSITIVE_PASSPHRASE, SENSITIVE_PASSPHRASE)
    assert len(fake_window.create_file_dialog_calls) == 1
    call = fake_window.create_file_dialog_calls[0]
    assert call["file_types"] == ("WorkTrace Backup (*.wtbackup)",)
    assert call.get("save_filename") == "worktrace-backup.wtbackup"


def test_bridge_preview_cancel_returns_stable_message(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(None))
    result = bridge.preview_encrypted_backup_manifest()
    assert result == {"ok": False, "error": "已取消读取备份清单"}


def test_bridge_preview_cancel_empty_list_returns_stable_message(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow([]))
    result = bridge.preview_encrypted_backup_manifest()
    assert result == {"ok": False, "error": "已取消读取备份清单"}


def test_bridge_preview_success_returns_narrow_payload(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    with patch(
        "worktrace.api.backup_api.parse_encrypted_backup_manifest",
        return_value=_fake_manifest_info(),
    ):
        result = bridge.preview_encrypted_backup_manifest()
    assert result.get("ok") is True
    assert set(result.keys()) == {"ok", "filename", "manifest"}
    assert result["filename"] == "worktrace-backup.wtbackup"
    manifest = result["manifest"]
    assert set(manifest.keys()) == {
        "version",
        "app_version",
        "created_at",
        "kdf_algorithm",
        "payload_format",
        "payload_alg",
    }
    serialized = json.dumps(result, ensure_ascii=False)
    assert "C:\\\\" not in serialized
    assert "backups" not in serialized


def test_bridge_preview_success_with_string_path(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow("C:\\backups\\worktrace-backup.wtbackup"))
    with patch(
        "worktrace.api.backup_api.parse_encrypted_backup_manifest",
        return_value=_fake_manifest_info(),
    ):
        result = bridge.preview_encrypted_backup_manifest()
    assert result.get("ok") is True
    assert result["filename"] == "worktrace-backup.wtbackup"


def test_bridge_preview_dialog_exception_collapses(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(RuntimeError("dialog boom " + SENSITIVE_PASSPHRASE)))
    result = bridge.preview_encrypted_backup_manifest()
    assert result == {"ok": False, "error": "读取备份清单失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_PASSPHRASE not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


def test_bridge_preview_api_exception_collapses(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    with patch.object(
        settings_api,
        "preview_encrypted_backup_manifest_for_webview",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = bridge.preview_encrypted_backup_manifest()
    assert result == {"ok": False, "error": "读取备份清单失败"}


def test_bridge_preview_does_not_call_import_or_export_or_clear(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    with patch(
        "worktrace.api.backup_api.parse_encrypted_backup_manifest",
        return_value=_fake_manifest_info(),
    ), \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch.object(settings_api, "clear_all_local_data") as mock_clear, \
            patch.object(settings_api, "set_setting_value") as mock_set_value:
        bridge.preview_encrypted_backup_manifest()
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_clear.assert_not_called()
        mock_set_value.assert_not_called()


def test_bridge_preview_uses_open_dialog_with_wtbackup_filter(temp_db) -> None:
    bridge = WebViewBridge()
    fake_window = _FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",))
    bridge.set_window(fake_window)
    with patch(
        "worktrace.api.backup_api.parse_encrypted_backup_manifest",
        return_value=_fake_manifest_info(),
    ):
        bridge.preview_encrypted_backup_manifest()
    assert len(fake_window.create_file_dialog_calls) == 1
    call = fake_window.create_file_dialog_calls[0]
    assert call["file_types"] == ("WorkTrace Backup (*.wtbackup)",)
    # The open dialog must NOT pass save_filename.
    assert "save_filename" not in call


# --- API import facade --------------------------------------


def test_api_import_success_returns_narrow_payload(temp_db) -> None:
    # Mock the backend import so no real file is read. The facade must
    # aggregate the imported_tables dict into display-safe counts only;
    # the raw dict / table names must never appear in the payload.
    fake_result = ImportResult(
        mode="replace",
        imported_tables={"activity_log": 5, "project": 2, "settings": 1},
        folder_index_reset=True,
    )
    with patch(
        "worktrace.api.backup_api.import_encrypted_backup",
        return_value=fake_result,
    ) as mock_import:
        result = import_encrypted_backup_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup",
            SENSITIVE_PASSPHRASE,
            "导入并替换",
        )
    # The backend must have been called in replace mode.
    args, kwargs = mock_import.call_args
    assert args[0] == "C:\\backups\\worktrace-backup.wtbackup"
    assert args[1] == SENSITIVE_PASSPHRASE
    assert kwargs.get("mode") == "replace" or args[-1] == "replace"
    # Narrow payload: only ok / message / imported_table_count /
    # imported_row_count / folder_index_reset.
    assert result.get("ok") is True
    assert set(result.keys()) == {
        "ok",
        "message",
        "imported_table_count",
        "imported_row_count",
        "folder_index_reset",
    }
    assert result["message"] == "加密备份已导入，WorkTrace 已暂停，请检查数据后手动恢复记录"
    assert result["imported_table_count"] == 3
    assert result["imported_row_count"] == 8
    assert result["folder_index_reset"] is True
    # The raw table-name dict and table names must never leak.
    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in (
        "activity_log",
        "project",
        "settings",
        "imported_tables",
        "C:\\\\backups",
        SENSITIVE_PASSPHRASE,
        "Traceback",
        "sqlite3.",
    ):
        assert forbidden not in serialized, f"import payload leaks: {forbidden!r}"


@pytest.mark.parametrize(
    "bad_path",
    [None, "", "   ", "\t\n", True, False, 1, 0, [], {}, (), set(), object(),
     "C:\\backups\\worktrace-backup.csv",
     "C:\\backups\\worktrace-backup.zip",
     "C:\\backups\\worktrace-backup"],
)
def test_api_import_rejects_invalid_input_path(temp_db, bad_path) -> None:
    result = import_encrypted_backup_for_webview(
        bad_path,  # type: ignore[arg-type]
        SENSITIVE_PASSPHRASE,
        "导入并替换",
    )
    assert result == {"ok": False, "error": "请选择有效的加密备份文件"}


@pytest.mark.parametrize(
    "bad_passphrase",
    [None, "", "   ", "\t\n", True, False, 1, 0, [], {}, (), set(), object()],
)
def test_api_import_rejects_invalid_passphrase(temp_db, bad_passphrase) -> None:
    result = import_encrypted_backup_for_webview(
        "C:\\backups\\worktrace-backup.wtbackup",
        bad_passphrase,  # type: ignore[arg-type]
        "导入并替换",
    )
    assert result == {"ok": False, "error": "请输入备份口令"}


@pytest.mark.parametrize(
    "bad_confirm",
    [None, "", "   ", "\t\n", True, False, 1, 0, [], {}, (), set(), object(),
     "导入", "替换", "确认导入"],
)
def test_api_import_rejects_invalid_confirm_text(temp_db, bad_confirm) -> None:
    result = import_encrypted_backup_for_webview(
        "C:\\backups\\worktrace-backup.wtbackup",
        SENSITIVE_PASSPHRASE,
        bad_confirm,  # type: ignore[arg-type]
    )
    assert result == {"ok": False, "error": "请输入确认文字：导入并替换"}


@pytest.mark.parametrize(
    "exc, expected_message",
    [
        (BackupImportInProgressError("SECRET " + SENSITIVE_PASSPHRASE),
         "已有加密备份导入正在进行"),
        (BackupDecryptionError("SECRET_CIPHERTEXT " + SENSITIVE_PASSPHRASE),
         "备份口令错误或文件已损坏"),
        (BackupCorruptedError("SECRET_SALT " + SENSITIVE_PASSPHRASE),
         "备份口令错误或文件已损坏"),
        (BackupVersionNotSupportedError("v999 SECRET " + SENSITIVE_PASSPHRASE),
         "备份文件版本不受支持"),
        (SecureBackupError("generic SECRET " + SENSITIVE_PASSPHRASE),
         "导入加密备份失败"),
        (RuntimeError("SECRET_PATH C:\\leak " + SENSITIVE_PASSPHRASE + " sqlite3."),
         "导入加密备份失败"),
        (ValueError("SECRET_VALUE " + SENSITIVE_PASSPHRASE),
         "导入加密备份失败"),
    ],
)
def test_api_import_failure_collapses_to_stable_message(temp_db, exc, expected_message) -> None:
    with patch(
        "worktrace.api.backup_api.import_encrypted_backup",
        side_effect=exc,
    ):
        result = import_encrypted_backup_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup",
            SENSITIVE_PASSPHRASE,
            "导入并替换",
        )
    assert result == {"ok": False, "error": expected_message}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        SENSITIVE_PASSPHRASE,
        "SECRET_CIPHERTEXT",
        "SECRET_SALT",
        "SECRET_PATH",
        "SECRET_VALUE",
        "SECRET",
        "RuntimeError",
        "ValueError",
        "BackupImportInProgress",
        "BackupDecryption",
        "BackupCorrupted",
        "BackupVersionNotSupported",
        "SecureBackup",
        "Traceback",
        "sqlite3.",
        "C:\\\\leak",
    ):
        assert token not in serialized, f"import failure leaks: {token!r}"


def test_api_import_exception_payload_does_not_leak_raw_exception(temp_db) -> None:
    secret_msg = (
        "SECRET_PATH C:\\leak\\path SECRET_PASSPHRASE "
        + SENSITIVE_PASSPHRASE
        + " sqlite3.OperationalError"
    )
    with patch(
        "worktrace.api.backup_api.import_encrypted_backup",
        side_effect=RuntimeError(secret_msg),
    ):
        result = import_encrypted_backup_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup",
            SENSITIVE_PASSPHRASE,
            "导入并替换",
        )
    assert result == {"ok": False, "error": "导入加密备份失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        SENSITIVE_PASSPHRASE,
        "SECRET_PATH",
        "SECRET_PASSPHRASE",
        "RuntimeError",
        "Traceback",
        "sqlite3.",
        "C:\\\\leak",
        "leak\\\\path",
        "C:\\\\backups",
    ):
        assert token not in serialized, f"import exception leaks: {token!r}"


def test_api_import_does_not_call_export_or_manifest_or_clear_or_set(temp_db) -> None:
    fake_result = ImportResult(
        mode="replace",
        imported_tables={"activity_log": 1},
        folder_index_reset=False,
    )
    with patch(
        "worktrace.api.backup_api.import_encrypted_backup",
        return_value=fake_result,
    ), \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest, \
            patch.object(settings_api, "clear_all_local_data") as mock_clear, \
            patch.object(settings_api, "set_setting_value") as mock_set_value:
        import_encrypted_backup_for_webview(
            "C:\\backups\\worktrace-backup.wtbackup",
            SENSITIVE_PASSPHRASE,
            "导入并替换",
        )
        mock_export.assert_not_called()
        mock_manifest.assert_not_called()
        mock_clear.assert_not_called()
        mock_set_value.assert_not_called()


def test_api_import_round_trip_smoke(temp_db, tmp_path) -> None:
    # No-mock round-trip: export a real .wtbackup, mutate the DB, then
    # import the file back through the WebView facade. Asserts the
    # success payload is narrow, the post-import state is paused, and
    # secure_import_in_progress ends at False.
    from worktrace.services import activity_service, secure_backup_service
    from worktrace.services.settings_service import (
        get_bool_setting,
        get_setting,
    )

    # Seed data and export an encrypted backup.
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    backup_path = tmp_path / "round-trip.wtbackup"
    secure_backup_service.export_encrypted_backup(str(backup_path), SENSITIVE_PASSPHRASE)
    assert backup_path.is_file()

    # Mutate the DB so we can prove the import replaced it.
    activity_service.create_activity(
        "ExtraApp", "extra.exe", "Extra", start_time="2026-06-19 09:00:00"
    )

    # Reset the post-export running state so we can prove the import
    # leaves the app paused.
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    set_setting("secure_import_in_progress", "false")

    result = import_encrypted_backup_for_webview(
        str(backup_path), SENSITIVE_PASSPHRASE, "导入并替换"
    )
    assert result.get("ok") is True
    assert set(result.keys()) == {
        "ok",
        "message",
        "imported_table_count",
        "imported_row_count",
        "folder_index_reset",
    }
    assert result["imported_table_count"] >= 1
    assert result["imported_row_count"] >= 1
    # The post-import state must be paused with the guard cleared.
    assert get_bool_setting("secure_import_in_progress", False) is False
    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status", "") == "paused"
    # The payload must not leak path / passphrase / table dict.
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        SENSITIVE_PASSPHRASE,
        str(backup_path),
        "round-trip.wtbackup",
        "imported_tables",
        "activity_log",
        "project",
        "Traceback",
    ):
        assert token not in serialized, f"import smoke leaks: {token!r}"


# --- Bridge import method -----------------------------------


def test_bridge_import_method_exists() -> None:
    bridge = WebViewBridge()
    method = getattr(bridge, "import_encrypted_backup", None)
    assert callable(method), (
        "WebViewBridge must expose import_encrypted_backup for destructive settings contract"
    )


def test_bridge_import_method_signature_has_two_required_params() -> None:
    bridge = WebViewBridge()
    sig = inspect.signature(bridge.import_encrypted_backup)
    params = list(sig.parameters.values())
    assert len(params) == 2, (
        "bridge.import_encrypted_backup must take exactly two parameters"
    )
    for idx, name in enumerate(("passphrase", "confirm_text")):
        param = params[idx]
        assert param.name == name, (
            f"parameter {idx} must be named {name!r}, got {param.name!r}"
        )
        assert param.default is inspect.Parameter.empty, (
            f"parameter {name!r} must be required (no default)"
        )
        assert param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ), f"parameter {name!r} must not be *args or **kwargs"


def test_bridge_import_cancel_returns_stable_message(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(None))
    result = bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
    assert result == {"ok": False, "error": "已取消导入"}
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_PASSPHRASE not in serialized


def test_bridge_import_cancel_empty_list_returns_stable_message(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow([]))
    result = bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
    assert result == {"ok": False, "error": "已取消导入"}


def test_bridge_import_success_returns_narrow_payload(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    fake_result = ImportResult(
        mode="replace",
        imported_tables={"activity_log": 4, "project": 1},
        folder_index_reset=True,
    )
    with patch(
        "worktrace.api.backup_api.import_encrypted_backup",
        return_value=fake_result,
    ):
        result = bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
    assert result.get("ok") is True
    assert set(result.keys()) == {
        "ok",
        "message",
        "imported_table_count",
        "imported_row_count",
        "folder_index_reset",
    }
    assert result["imported_table_count"] == 2
    assert result["imported_row_count"] == 5
    assert result["folder_index_reset"] is True
    serialized = json.dumps(result, ensure_ascii=False)
    for forbidden in (
        "C:\\\\backups",
        "backups",
        SENSITIVE_PASSPHRASE,
        "activity_log",
        "project",
        "imported_tables",
    ):
        assert forbidden not in serialized, f"bridge import leaks: {forbidden!r}"


def test_bridge_import_success_with_string_path(temp_db) -> None:
    # pywebview may return a bare string instead of a tuple/list.
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow("C:\\backups\\worktrace-backup.wtbackup"))
    fake_result = ImportResult(
        mode="replace",
        imported_tables={"activity_log": 1},
        folder_index_reset=False,
    )
    with patch(
        "worktrace.api.backup_api.import_encrypted_backup",
        return_value=fake_result,
    ):
        result = bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
    assert result.get("ok") is True
    assert result["imported_row_count"] == 1


def test_bridge_import_dialog_exception_collapses(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(RuntimeError("dialog boom " + SENSITIVE_PASSPHRASE)))
    result = bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
    assert result == {"ok": False, "error": "导入加密备份失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    assert SENSITIVE_PASSPHRASE not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


def test_bridge_import_api_exception_collapses(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    with patch.object(
        settings_api,
        "import_encrypted_backup_for_webview",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
    assert result == {"ok": False, "error": "导入加密备份失败"}


def test_bridge_import_api_ok_false_passes_error_through(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    api_result = {"ok": False, "error": "备份口令错误或文件已损坏"}
    with patch.object(
        settings_api,
        "import_encrypted_backup_for_webview",
        return_value=api_result,
    ):
        result = bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
    assert result == api_result


def test_bridge_import_does_not_call_export_or_manifest_or_clear(temp_db) -> None:
    bridge = WebViewBridge()
    bridge.set_window(_FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",)))
    fake_result = ImportResult(
        mode="replace",
        imported_tables={"activity_log": 1},
        folder_index_reset=False,
    )
    with patch(
        "worktrace.api.backup_api.import_encrypted_backup",
        return_value=fake_result,
    ), \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest, \
            patch.object(settings_api, "clear_all_local_data") as mock_clear, \
            patch.object(settings_api, "set_setting_value") as mock_set_value:
        bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
        mock_export.assert_not_called()
        mock_manifest.assert_not_called()
        mock_clear.assert_not_called()
        mock_set_value.assert_not_called()


def test_bridge_import_uses_open_dialog_with_wtbackup_filter(temp_db) -> None:
    bridge = WebViewBridge()
    fake_window = _FakeWindow(("C:\\backups\\worktrace-backup.wtbackup",))
    bridge.set_window(fake_window)
    fake_result = ImportResult(
        mode="replace",
        imported_tables={"activity_log": 1},
        folder_index_reset=False,
    )
    with patch(
        "worktrace.api.backup_api.import_encrypted_backup",
        return_value=fake_result,
    ):
        bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
    assert len(fake_window.create_file_dialog_calls) == 1
    call = fake_window.create_file_dialog_calls[0]
    assert call["file_types"] == ("WorkTrace Backup (*.wtbackup)",)
    # The open dialog must NOT pass save_filename.
    assert "save_filename" not in call


def test_bridge_import_payload_never_leaks_full_path_or_passphrase(temp_db) -> None:
    bridge = WebViewBridge()
    full_path = "C:\\" + SENSITIVE_EXPORT_PATH + "\\ SECRET " + SENSITIVE_PASSPHRASE + ".wtbackup"
    bridge.set_window(_FakeWindow((full_path,)))
    fake_result = ImportResult(
        mode="replace",
        imported_tables={"activity_log": 1},
        folder_index_reset=False,
    )
    with patch(
        "worktrace.api.backup_api.import_encrypted_backup",
        return_value=fake_result,
    ):
        result = bridge.import_encrypted_backup(SENSITIVE_PASSPHRASE, "导入并替换")
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        SENSITIVE_PASSPHRASE,
        SENSITIVE_EXPORT_PATH,
        "SECRET",
        full_path,
        "Traceback",
    ):
        assert token not in serialized, f"bridge import leaks: {token!r}"


# --- API clear-all facade -----------------------------------


def test_api_clear_success_returns_narrow_payload(temp_db) -> None:
    # Mock the underlying export_service.clear_all_local_data so no real
    # reset runs; assert confirm=True is forwarded and the payload is
    # narrow (ok / message / status when status refresh succeeds).
    with patch.object(
        settings_api.export_service, "clear_all_local_data"
    ) as mock_clear:
        result = clear_all_local_data_for_webview("清空本地数据")
    mock_clear.assert_called_once_with(confirm=True)
    assert result.get("ok") is True
    # status is optional but the message must always be present.
    assert result["message"] == "本地数据已清空"
    # When status is present it must be JSON-serializable.
    serialized = json.dumps(result, ensure_ascii=False)
    parsed = json.loads(serialized)
    assert parsed["ok"] is True
    # The payload must never carry raw exception / path / clipboard
    # content / note. Note: ``clipboard_capture_enabled`` is a legitimate
    # status boolean field name, not clipboard content; we forbid the
    # ``clipboard_content`` token instead of the bare ``clipboard``
    # substring to avoid a false positive on the field name.
    for forbidden in (
        "Traceback",
        "RuntimeError",
        "ValueError",
        "operation_in_progress",
        "C:\\\\",
        "clipboard_content",
        "window_title",
        "file_path_hint",
        "note",
    ):
        assert forbidden not in serialized, f"clear payload leaks: {forbidden!r}"


@pytest.mark.parametrize(
    "bad_confirm",
    [None, "", "   ", "\t\n", True, False, 1, 0, [], {}, (), set(), object(),
     "清空", "本地数据", "确认清空"],
)
def test_api_clear_rejects_invalid_confirmation(temp_db, bad_confirm) -> None:
    result = clear_all_local_data_for_webview(bad_confirm)  # type: ignore[arg-type]
    assert result == {"ok": False, "error": "请输入确认文字：清空本地数据"}


def test_api_clear_exception_collapses_to_generic_error(temp_db) -> None:
    with patch.object(
        settings_api.export_service,
        "clear_all_local_data",
        side_effect=RuntimeError("SECRET " + SENSITIVE_PASSPHRASE + " sqlite3."),
    ):
        result = clear_all_local_data_for_webview("清空本地数据")
    assert result == {"ok": False, "error": "清空本地数据失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        SENSITIVE_PASSPHRASE,
        "SECRET",
        "RuntimeError",
        "Traceback",
        "sqlite3.",
    ):
        assert token not in serialized, f"clear exception leaks: {token!r}"


def test_api_clear_does_not_call_backup_actions_or_set_setting(temp_db) -> None:
    with patch.object(settings_api.export_service, "clear_all_local_data"), \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest, \
            patch.object(settings_api, "set_setting_value") as mock_set_value:
        clear_all_local_data_for_webview("清空本地数据")
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()
        mock_set_value.assert_not_called()


def test_api_clear_round_trip_smoke(temp_db) -> None:
    # No-mock round-trip: seed business data, run clear-all through the
    # WebView facade, then assert the system-default project / settings
    # are re-seeded, business data is dropped, secure_import_in_progress
    # ends at False, user_paused is True, collector_status is paused, and
    # the payload does not leak internal info.
    from worktrace.services import activity_service
    from worktrace.services.settings_service import (
        get_bool_setting,
        get_setting,
    )

    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")

    result = clear_all_local_data_for_webview("清空本地数据")
    assert result.get("ok") is True
    assert result["message"] == "本地数据已清空"

    # Post-clear state.
    assert get_bool_setting("secure_import_in_progress", False) is False
    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status", "") == "paused"
    # Business data dropped.
    activities = activity_service.get_activities_by_range(
        "2026-06-18", "2026-06-18"
    )
    assert activities == []
    # System default project re-seeded.
    from worktrace.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM project WHERE created_by = 'system'"
        ).fetchall()
    assert rows, "clear-all must re-seed system default projects"

    # Payload must not leak internal info.
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        "Traceback",
        "RuntimeError",
        "operation_in_progress",
        "reset_database",
        "sqlite3.",
        SENSITIVE_PASSPHRASE,
    ):
        assert token not in serialized, f"clear smoke leaks: {token!r}"


# --- Bridge clear-all method --------------------------------


def test_bridge_clear_method_exists() -> None:
    bridge = WebViewBridge()
    method = getattr(bridge, "clear_all_local_data", None)
    assert callable(method), (
        "WebViewBridge must expose clear_all_local_data for destructive settings contract"
    )


def test_bridge_clear_method_signature_has_one_required_param() -> None:
    bridge = WebViewBridge()
    sig = inspect.signature(bridge.clear_all_local_data)
    params = list(sig.parameters.values())
    assert len(params) == 1, (
        "bridge.clear_all_local_data must take exactly one parameter"
    )
    param = params[0]
    assert param.name == "confirm_text", (
        f"parameter must be named 'confirm_text', got {param.name!r}"
    )
    assert param.default is inspect.Parameter.empty, (
        "parameter 'confirm_text' must be required (no default)"
    )
    assert param.kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), "parameter 'confirm_text' must not be *args or **kwargs"


def test_bridge_clear_success_calls_api_and_returns_narrow_payload(temp_db) -> None:
    bridge = WebViewBridge()
    api_result = {
        "ok": True,
        "message": "本地数据已清空",
        "status": {"page": "settings_privacy"},
    }
    with patch.object(
        settings_api,
        "clear_all_local_data_for_webview",
        return_value=api_result,
    ) as mock_api:
        result = bridge.clear_all_local_data("清空本地数据")
    mock_api.assert_called_once_with("清空本地数据")
    assert result.get("ok") is True
    assert result["message"] == "本地数据已清空"
    # status may be transparently passed through.
    assert result.get("status") == {"page": "settings_privacy"}


def test_bridge_clear_api_ok_false_passes_error_through(temp_db) -> None:
    bridge = WebViewBridge()
    api_result = {"ok": False, "error": "请输入确认文字：清空本地数据"}
    with patch.object(
        settings_api,
        "clear_all_local_data_for_webview",
        return_value=api_result,
    ):
        result = bridge.clear_all_local_data("not the literal")
    assert result == api_result


def test_bridge_clear_exception_collapses(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(
        settings_api,
        "clear_all_local_data_for_webview",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = bridge.clear_all_local_data("清空本地数据")
    assert result == {"ok": False, "error": "清空本地数据失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        SENSITIVE_PASSPHRASE,
        "RuntimeError",
        "Traceback",
    ):
        assert token not in serialized, f"bridge clear leaks: {token!r}"


def test_bridge_clear_does_not_call_backup_actions_directly(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(
        settings_api,
        "clear_all_local_data_for_webview",
        return_value={"ok": True, "message": "本地数据已清空"},
    ), \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest:
        bridge.clear_all_local_data("清空本地数据")
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()


# --- First-run notice API facade ----------------------------


def test_api_first_run_notice_default_is_false_for_new_db(temp_db) -> None:
    # A brand-new database seeds first_run_notice_accepted="false"; the
    # facade must report accepted=False.
    result = get_first_run_notice_for_webview()
    assert result.get("ok") is True
    assert result["accepted"] is False


def test_api_first_run_notice_returns_narrow_payload(temp_db) -> None:
    result = get_first_run_notice_for_webview()
    assert isinstance(result, dict)
    assert set(result.keys()) == {"ok", "accepted", "title", "highlights", "notice_text"}
    assert isinstance(result["accepted"], bool)
    assert isinstance(result["title"], str) and result["title"]
    assert isinstance(result["highlights"], list)
    for item in result["highlights"]:
        assert isinstance(item, str)


def test_api_first_run_notice_text_matches_privacy_notice_constant(temp_db) -> None:
    from worktrace.constants import PRIVACY_NOTICE_TEXT

    result = get_first_run_notice_for_webview()
    assert result["notice_text"] == PRIVACY_NOTICE_TEXT


def test_api_first_run_notice_highlights_match_expected_notice(temp_db) -> None:
    result = get_first_run_notice_for_webview()
    assert result["highlights"] == [
        "本地保存",
        "不截屏录屏",
        "不主动读正文",
        "用户可清空",
    ]


def test_api_first_run_notice_reflects_accepted_state(temp_db) -> None:
    set_setting("first_run_notice_accepted", "false")
    assert get_first_run_notice_for_webview()["accepted"] is False

    set_setting("first_run_notice_accepted", "true")
    assert get_first_run_notice_for_webview()["accepted"] is True


def test_api_first_run_notice_payload_is_json_serializable(temp_db) -> None:
    set_setting("first_run_notice_accepted", "true")
    result = get_first_run_notice_for_webview()
    serialized = json.dumps(result, ensure_ascii=False)
    parsed = json.loads(serialized)
    assert parsed["ok"] is True


def test_api_first_run_notice_payload_does_not_leak_sensitive_tokens(temp_db) -> None:
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    set_setting("current_activity_snapshot", '{"clipboard":"' + SENSITIVE_CLIPBOARD_TOKEN + '"}')
    serialized = json.dumps(get_first_run_notice_for_webview(), ensure_ascii=False)
    for token in (
        SENSITIVE_EXPORT_PATH,
        SENSITIVE_CLIPBOARD_TOKEN,
        SENSITIVE_PASSPHRASE,
        "current_activity_snapshot",
        "window_title",
        "file_path_hint",
        "first_run_notice_accepted",  # raw DB key must not leak
        "Traceback",
        "sqlite3.",
    ):
        assert token not in serialized, f"notice payload leaks: {token!r}"


def test_api_first_run_notice_fail_closed_on_accepted_read_exception(temp_db) -> None:
    # Strict fail-closed: when reading the accepted state raises, the
    # facade must NOT return a fallback notice body. It must return
    # ``{"ok": False, "error": "<stable Chinese>"}`` with NO title,
    # NO highlights, NO notice_text, and NO warning. The frontend must
    # show a blocking error overlay and must NOT allow the user to
    # accept. The collector and folder index worker are not started.
    with patch.object(
        settings_api,
        "first_run_notice_accepted",
        side_effect=RuntimeError("SECRET " + SENSITIVE_PASSPHRASE + " sqlite3."),
    ):
        result = get_first_run_notice_for_webview()
    # Strict fail-closed payload: only ok=False + stable error string.
    assert result == {
        "ok": False,
        "error": "隐私说明加载失败。为保护隐私，WorkTrace 暂不会启动记录。请重启应用或重新安装。",
    }
    # No notice body fields may be present (no fallback text from JS or
    # backend). The frontend must not render any notice body.
    for forbidden_key in ("title", "highlights", "notice_text", "warning", "accepted"):
        assert forbidden_key not in result, (
            f"fail-closed payload must not include notice body key: {forbidden_key!r}"
        )
    # The payload must not leak the raw exception / passphrase / SQL.
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (SENSITIVE_PASSPHRASE, "SECRET", "RuntimeError", "Traceback", "sqlite3."):
        assert token not in serialized, f"notice fail-closed leaks: {token!r}"


# --- First-run notice fail-closed + success path -----------


def test_api_first_run_notice_success_path_returns_full_notice_text(temp_db) -> None:
    # Normal success path: both accepted=True and accepted=False must
    # return the full notice body (title / highlights / notice_text)
    # so the frontend can always render the privacy notice text.
    for accepted_value in ("false", "true"):
        set_setting("first_run_notice_accepted", accepted_value)
        result = get_first_run_notice_for_webview()
        assert result.get("ok") is True
        assert result["accepted"] is (accepted_value == "true")
        assert isinstance(result["title"], str) and result["title"]
        assert isinstance(result["highlights"], list) and result["highlights"]
        for item in result["highlights"]:
            assert isinstance(item, str) and item
        assert isinstance(result["notice_text"], str) and result["notice_text"]
        # No warning field on the success path.
        assert "warning" not in result


def test_api_first_run_notice_does_not_call_write_actions(temp_db) -> None:
    with patch.object(settings_api, "accept_first_run_notice") as mock_accept, \
            patch.object(settings_api, "set_setting_value") as mock_set_value, \
            patch.object(settings_api, "clear_all_local_data") as mock_clear, \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest:
        get_first_run_notice_for_webview()
        mock_accept.assert_not_called()
        mock_set_value.assert_not_called()
        mock_clear.assert_not_called()
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()


def test_api_accept_first_run_notice_writes_accepted_true(temp_db) -> None:
    set_setting("first_run_notice_accepted", "false")
    assert get_first_run_notice_for_webview()["accepted"] is False
    result = accept_first_run_notice_for_webview()
    assert result == {"ok": True, "accepted": True, "message": "已确认隐私说明"}
    # The accept must persist; a subsequent read must see accepted=True
    # even with settings cache in play.
    assert get_first_run_notice_for_webview()["accepted"] is True


def test_api_accept_first_run_notice_consistent_with_status_read(temp_db) -> None:
    set_setting("first_run_notice_accepted", "false")
    accept_first_run_notice_for_webview()
    # Both the notice facade and the status facade must see accepted=True
    # in the same process after accept (cache invalidation).
    assert get_first_run_notice_for_webview()["accepted"] is True
    status = get_settings_privacy_status()["status"]
    assert status["first_run_notice"]["accepted"] is True


def test_api_accept_first_run_notice_is_idempotent(temp_db) -> None:
    set_setting("first_run_notice_accepted", "true")
    result = accept_first_run_notice_for_webview()
    assert result == {"ok": True, "accepted": True, "message": "已确认隐私说明"}
    # A second call still succeeds.
    result2 = accept_first_run_notice_for_webview()
    assert result2 == {"ok": True, "accepted": True, "message": "已确认隐私说明"}


def test_api_accept_first_run_notice_exception_collapses(temp_db) -> None:
    with patch.object(
        settings_api,
        "accept_first_run_notice",
        side_effect=RuntimeError("SECRET " + SENSITIVE_PASSPHRASE + " sqlite3."),
    ):
        result = accept_first_run_notice_for_webview()
    assert result == {"ok": False, "error": "确认隐私说明失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (SENSITIVE_PASSPHRASE, "SECRET", "RuntimeError", "Traceback", "sqlite3."):
        assert token not in serialized, f"accept exception leaks: {token!r}"


def test_api_accept_first_run_notice_does_not_call_collector(temp_db) -> None:
    with patch("worktrace.api.app_api.start_collector") as mock_start:
        accept_first_run_notice_for_webview()
        mock_start.assert_not_called()


def test_api_accept_first_run_notice_does_not_call_background_workers(temp_db) -> None:
    # accept_first_run_notice_for_webview only writes the accepted flag;
    # it must NOT start the folder index worker / background workers.
    # Starting workers is the bridge's responsibility after a successful
    # accept, gated on the privacy notice.
    with patch("worktrace.api.app_api.start_background_workers") as mock_workers:
        accept_first_run_notice_for_webview()
        mock_workers.assert_not_called()


def test_api_accept_first_run_notice_does_not_call_set_setting_value(temp_db) -> None:
    with patch.object(settings_api, "set_setting_value") as mock_set_value, \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest, \
            patch.object(settings_api, "clear_all_local_data") as mock_clear:
        accept_first_run_notice_for_webview()
        mock_set_value.assert_not_called()
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()
        mock_clear.assert_not_called()


def test_api_status_first_run_notice_subdict_is_display_safe(temp_db) -> None:
    set_setting("first_run_notice_accepted", "false")
    status = get_settings_privacy_status()["status"]
    sub = status["first_run_notice"]
    assert isinstance(sub, dict)
    assert set(sub.keys()) == {"accepted", "view_available_in_webview", "accept_required"}
    assert sub["accepted"] is False
    assert sub["view_available_in_webview"] is True
    assert sub["accept_required"] is True

    set_setting("first_run_notice_accepted", "true")
    status = get_settings_privacy_status()["status"]
    sub = status["first_run_notice"]
    assert sub["accepted"] is True
    assert sub["view_available_in_webview"] is True
    assert sub["accept_required"] is False


def test_api_status_does_not_expose_raw_first_run_setting_key(temp_db) -> None:
    serialized = json.dumps(get_settings_privacy_status(), ensure_ascii=False)
    assert "first_run_notice_accepted" not in serialized


# --- Bridge first-run notice methods ------------------------


def test_bridge_get_first_run_notice_method_exists() -> None:
    bridge = WebViewBridge()
    method = getattr(bridge, "get_first_run_notice", None)
    assert callable(method), "WebViewBridge must expose get_first_run_notice for startup gate contract"


def test_bridge_accept_first_run_notice_method_exists() -> None:
    bridge = WebViewBridge()
    method = getattr(bridge, "accept_first_run_notice", None)
    assert callable(method), "WebViewBridge must expose accept_first_run_notice for startup gate contract"


def test_bridge_first_run_notice_methods_have_no_required_args() -> None:
    bridge = WebViewBridge()
    for method_name in ("get_first_run_notice", "accept_first_run_notice"):
        sig = inspect.signature(getattr(bridge, method_name))
        for name, param in sig.parameters.items():
            assert param.default is not inspect.Parameter.empty, (
                f"bridge.{method_name} parameter {name!r} must have a default"
            )


def test_bridge_get_first_run_notice_returns_narrow_payload(temp_db) -> None:
    bridge = WebViewBridge()
    result = bridge.get_first_run_notice()
    assert isinstance(result, dict)
    assert result.get("ok") is True
    assert set(result.keys()) == {"ok", "accepted", "title", "highlights", "notice_text"}


def test_bridge_get_first_run_notice_exception_collapses(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(
        settings_api,
        "get_first_run_notice_for_webview",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = bridge.get_first_run_notice()
    assert result == {"ok": False, "error": "加载隐私说明失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (SENSITIVE_PASSPHRASE, "RuntimeError", "Traceback"):
        assert token not in serialized


def test_bridge_accept_first_run_notice_calls_collector_on_success(temp_db) -> None:
    bridge = WebViewBridge()
    set_setting("first_run_notice_accepted", "false")
    with patch("worktrace.api.app_api.start_collector") as mock_start:
        result = bridge.accept_first_run_notice()
    mock_start.assert_called_once()
    assert result.get("ok") is True
    assert result["accepted"] is True
    assert result["message"] == "已确认隐私说明"


def test_bridge_accept_first_run_notice_does_not_call_collector_on_api_failure(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(
        settings_api,
        "accept_first_run_notice_for_webview",
        return_value={"ok": False, "error": "确认隐私说明失败"},
    ), patch("worktrace.api.app_api.start_collector") as mock_start, \
            patch("worktrace.api.app_api.start_background_workers") as mock_workers:
        result = bridge.accept_first_run_notice()
    mock_start.assert_not_called()
    mock_workers.assert_not_called()
    assert result == {"ok": False, "error": "确认隐私说明失败"}


def test_bridge_accept_first_run_notice_exception_collapses(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(
        settings_api,
        "accept_first_run_notice_for_webview",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ):
        result = bridge.accept_first_run_notice()
    assert result == {"ok": False, "error": "确认隐私说明失败"}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (SENSITIVE_PASSPHRASE, "RuntimeError", "Traceback"):
        assert token not in serialized


def test_bridge_accept_first_run_notice_payload_does_not_leak(temp_db) -> None:
    bridge = WebViewBridge()
    set_setting("export_path", SENSITIVE_EXPORT_PATH)
    set_setting("first_run_notice_accepted", "false")
    result = bridge.accept_first_run_notice()
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (
        SENSITIVE_EXPORT_PATH,
        SENSITIVE_PASSPHRASE,
        "first_run_notice_accepted",
        "Traceback",
    ):
        assert token not in serialized, f"accept payload leaks: {token!r}"


def test_bridge_accept_first_run_notice_does_not_call_backup_or_set_setting(temp_db) -> None:
    bridge = WebViewBridge()
    with patch("worktrace.api.app_api.start_collector"), \
            patch.object(settings_api, "set_setting_value") as mock_set_value, \
            patch("worktrace.api.backup_api.export_encrypted_backup") as mock_export, \
            patch("worktrace.api.backup_api.import_encrypted_backup") as mock_import, \
            patch("worktrace.api.backup_api.parse_encrypted_backup_manifest") as mock_manifest, \
            patch.object(settings_api, "clear_all_local_data") as mock_clear:
        bridge.accept_first_run_notice()
        mock_set_value.assert_not_called()
        mock_export.assert_not_called()
        mock_import.assert_not_called()
        mock_manifest.assert_not_called()
        mock_clear.assert_not_called()


# --- toggle_pause first-run guard ---------------------------


def test_bridge_toggle_pause_does_not_start_collector_when_notice_unaccepted(temp_db) -> None:
    bridge = WebViewBridge()
    set_setting("first_run_notice_accepted", "false")
    with patch("worktrace.api.app_api.start_collector") as mock_start:
        result = bridge.toggle_pause()
    mock_start.assert_not_called()
    assert result == {"ok": False, "error": "请先确认隐私说明"}


def test_bridge_toggle_pause_does_not_mutate_pause_state_when_notice_unaccepted(temp_db) -> None:
    bridge = WebViewBridge()
    set_setting("first_run_notice_accepted", "false")
    set_setting("user_paused", "false")
    set_setting("collector_status", "stopped")
    bridge.toggle_pause()
    # None of the pause/status settings should have changed.
    from worktrace.services.settings_service import get_setting
    assert get_setting("user_paused", "") == "false"
    assert get_setting("collector_status", "") == "stopped"


def test_bridge_toggle_pause_fail_closed_on_notice_read_exception(temp_db) -> None:
    bridge = WebViewBridge()
    with patch.object(
        settings_api,
        "first_run_notice_accepted",
        side_effect=RuntimeError(SENSITIVE_PASSPHRASE),
    ), patch("worktrace.api.app_api.start_collector") as mock_start:
        result = bridge.toggle_pause()
    mock_start.assert_not_called()
    assert result == {"ok": False, "error": "请先确认隐私说明"}
    serialized = json.dumps(result, ensure_ascii=False)
    for token in (SENSITIVE_PASSPHRASE, "RuntimeError", "Traceback"):
        assert token not in serialized


def test_bridge_toggle_pause_works_after_notice_accepted(temp_db) -> None:
    bridge = WebViewBridge()
    set_setting("first_run_notice_accepted", "true")
    set_setting("user_paused", "true")
    set_setting("collector_status", "paused")
    with patch("worktrace.api.app_api.start_collector") as mock_start:
        result = bridge.toggle_pause()
    mock_start.assert_called_once()
    assert result.get("ok") is True
