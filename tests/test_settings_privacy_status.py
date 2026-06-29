"""Phase 6A / 6B / 6C — Settings / Privacy status facade + bridge tests.

These tests verify the ``settings_api.get_settings_privacy_status`` facade,
the ``settings_api.set_clipboard_capture_enabled_for_webview`` write facade,
the ``settings_api.export_encrypted_backup_for_webview`` and
``settings_api.preview_encrypted_backup_manifest_for_webview`` facades, and
the corresponding ``WebViewBridge`` methods. They assert the read-only
status payload and the clipboard capture toggle / backup export / manifest
preview write payloads never leak paths, clipboard content, passphrases,
tracebacks, or any unintended write-side action surface.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import patch

import pytest

from worktrace.api import settings_api
from worktrace.api.backup_api import BackupManifestInfo
from worktrace.api.settings_api import (
    export_encrypted_backup_for_webview,
    get_settings_privacy_status,
    preview_encrypted_backup_manifest_for_webview,
    set_clipboard_capture_enabled_for_webview,
)
from worktrace.services.secure_backup_service import (
    BackupCorruptedError,
    BackupVersionNotSupportedError,
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
        "phase",
        "storage_model",
        "clipboard_capture_enabled",
        "export_path_configured",
        "secure_import_in_progress",
        "encrypted_backup",
        "destructive_actions",
    ):
        assert key in status, f"status missing required key: {key}"
    assert status["page"] == "settings_privacy"
    assert status["phase"] == "6C"
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


def test_api_encrypted_backup_availability_fields_match_phase_6c(temp_db) -> None:
    # Phase 6C: export + manifest preview are now available in WebView;
    # import remains unavailable (planned for Phase 6D).
    status = get_settings_privacy_status()["status"]
    enc = status["encrypted_backup"]
    assert isinstance(enc, dict)
    assert enc["supported"] is True
    assert enc["export_available_in_webview"] is True
    assert enc["import_available_in_webview"] is False
    assert enc["manifest_preview_available_in_webview"] is True


def test_api_destructive_clear_all_availability_is_false(temp_db) -> None:
    status = get_settings_privacy_status()["status"]
    destructive = status["destructive_actions"]
    assert isinstance(destructive, dict)
    assert destructive["clear_all_local_data_available_in_webview"] is False


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
        "WebViewBridge must expose get_settings_privacy_status for Phase 6A"
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
        "phase",
        "storage_model",
        "clipboard_capture_enabled",
        "export_path_configured",
        "secure_import_in_progress",
        "encrypted_backup",
        "destructive_actions",
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


# --- Phase 6B: API write facade -----------------------------------------


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


# --- Phase 6B: Bridge write method --------------------------------------


def test_bridge_write_method_exists_on_composed_webview_bridge() -> None:
    bridge = WebViewBridge()
    method = getattr(bridge, "set_clipboard_capture_enabled", None)
    assert callable(method), (
        "WebViewBridge must expose set_clipboard_capture_enabled for Phase 6B"
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


# --- Phase 6C: API export facade ---------------------------------------


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


# --- Phase 6C: API manifest preview facade -----------------------------


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


# --- Phase 6C: Bridge export + manifest methods ------------------------


def test_bridge_export_method_exists() -> None:
    bridge = WebViewBridge()
    method = getattr(bridge, "export_encrypted_backup", None)
    assert callable(method), (
        "WebViewBridge must expose export_encrypted_backup for Phase 6C"
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
        "WebViewBridge must expose preview_encrypted_backup_manifest for Phase 6C"
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
