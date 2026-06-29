"""Phase 6A / 6B — Settings / Privacy status facade + bridge tests.

These tests verify the ``settings_api.get_settings_privacy_status`` facade,
the ``settings_api.set_clipboard_capture_enabled_for_webview`` write facade,
and the corresponding ``WebViewBridge`` methods. They assert the read-only
status payload and the clipboard capture toggle write payload never leak
paths, clipboard content, passphrases, tracebacks, or any unintended
write-side action surface.
"""

from __future__ import annotations

import inspect
import json
from unittest.mock import patch

import pytest

from worktrace.api import settings_api
from worktrace.api.settings_api import (
    get_settings_privacy_status,
    set_clipboard_capture_enabled_for_webview,
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
    assert status["phase"] == "6A"
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


def test_api_encrypted_backup_availability_fields_are_false(temp_db) -> None:
    status = get_settings_privacy_status()["status"]
    enc = status["encrypted_backup"]
    assert isinstance(enc, dict)
    assert enc["supported"] is True
    assert enc["export_available_in_webview"] is False
    assert enc["import_available_in_webview"] is False
    assert enc["manifest_preview_available_in_webview"] is False


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
