"""Settings, backup, and privacy-gate WebView owner contracts."""

from __future__ import annotations

import os
import re
import sys

import pytest

pytestmark = [
    pytest.mark.contract,
    pytest.mark.webview_static,
    pytest.mark.security_privacy,
]

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import (  # noqa: E402
    REPO_ROOT,
    WEBVIEW_UI_DIR,
    func_body,
    html_section_by_id,
    read_js,
)

SETTINGS_BRIDGE_METHODS = {
    "acceptFirstRunNotice",
    "clearAllLocalData",
    "exportEncryptedBackup",
    "getFirstRunNotice",
    "getSettingsPrivacyStatus",
    "importEncryptedBackup",
    "previewEncryptedBackupManifest",
    "setClipboardCaptureEnabled",
}


def _settings_source() -> str:
    return read_js("settings.js")


def _app_function_is_exposed(source: str, name: str) -> bool:
    return bool(
        re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\(", source)
        and re.search(r"\bApp\." + re.escape(name) + r"\s*=", source)
    ) or bool(
        re.search(
            r"\bApp\." + re.escape(name) + r"\s*=\s*function\b",
            source,
        )
    )


def test_settings_page_resources_and_controls_are_complete() -> None:
    index = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    section = html_section_by_id(index, "page-settings")
    assert (WEBVIEW_UI_DIR / "js" / "settings.js").is_file()
    assert 'src="js/settings.js"' in index
    assert "设置与隐私" in section
    assert "管理本地隐私设置" in section

    required_ids = (
        "settings-error",
        "settings-loading",
        "settings-status",
        "settings-clipboard-toggle",
        "settings-clipboard-toggle-status",
        "settings-backup-passphrase",
        "settings-backup-passphrase-confirm",
        "settings-backup-export-btn",
        "settings-backup-manifest-btn",
        "settings-backup-status",
        "settings-backup-manifest",
        "settings-backup-import-passphrase",
        "settings-backup-import-confirm",
        "settings-backup-import-btn",
        "settings-backup-import-status",
        "settings-clear-confirm",
        "settings-clear-local-data-btn",
        "settings-clear-status",
        "settings-privacy-notice-status",
        "settings-privacy-notice-btn",
        "first-run-notice-overlay",
        "first-run-notice-accept-btn",
        "first-run-notice-close-btn",
    )
    for dom_id in required_ids:
        assert 'id="' + dom_id + '"' in index

    for forbidden_id in (
        "settings-save-btn",
        "settings-set-path-btn",
        "settings-import-btn",
        "settings-clear-btn",
        "settings-clear-all-btn",
        "settings-export-btn",
        "settings-manifest-btn",
        "settings-refresh-btn",
    ):
        assert forbidden_id not in section


def test_settings_resource_is_packaged() -> None:
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "settings.js" in spec


def test_settings_uses_only_fixed_allowed_bridge_capabilities() -> None:
    source = _settings_source()
    calls = set(re.findall(r"\bApp\.bridge\.([A-Za-z0-9_]+)\s*\(", source))
    assert calls == SETTINGS_BRIDGE_METHODS
    assert "App.callBridge" not in source
    assert "window.pywebview" not in source
    assert "invokeBridge(" not in source


def test_settings_has_no_network_storage_or_unsafe_dom_paths() -> None:
    source = _settings_source()
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "navigator.clipboard",
        "innerHTML",
        "err.message",
        "error.message",
        "e.message",
    ):
        assert forbidden not in source
    assert "textContent" in source


def test_settings_operation_state_has_one_cross_operation_guard() -> None:
    core = read_js("core.js")
    source = _settings_source()
    flags = (
        "settingsLoading",
        "settingsWriteInProgress",
        "settingsBackupExportInProgress",
        "settingsBackupManifestInProgress",
        "settingsBackupImportInProgress",
        "settingsClearAllInProgress",
    )
    for flag in flags:
        assert "App." + flag in core

    guard = func_body(source, "anySettingsOperationInProgress")
    for flag in flags:
        assert "App." + flag in guard

    for operation in (
        "exportEncryptedBackup",
        "previewEncryptedBackupManifest",
        "importEncryptedBackup",
        "clearAllLocalData",
    ):
        assert "anySettingsOperationInProgress()" in func_body(source, operation)


def test_settings_loading_and_clipboard_controls_have_separate_semantics() -> None:
    source = _settings_source()
    load_body = func_body(source, "loadSettingsPrivacyStatus")
    assert "App.settingsLoading" in load_body
    assert "App.settingsRequestToken" in load_body
    assert "App.bridge.getSettingsPrivacyStatus()" in load_body
    assert "renderSettingsStatus" in load_body

    controls = func_body(source, "setSettingsControlsDisabled")
    assert "!App.settingsLoaded" in controls
    backup_controls = func_body(source, "setSettingsBackupControlsDisabled")
    danger_controls = func_body(source, "setSettingsDangerControlsDisabled")
    assert "settingsLoaded" not in backup_controls
    assert "settingsLoaded" not in danger_controls
    assert "disabled" in backup_controls
    assert "disabled" in danger_controls

    toggle = func_body(source, "setCaptureEnabled")
    assert "App.settingsWriteInProgress" in toggle
    assert "App.bridge.setClipboardCaptureEnabled" in toggle


def test_settings_status_and_manifest_render_through_safe_helpers() -> None:
    source = _settings_source()
    status_line = func_body(source, "setStatusLine")
    assert "textContent" in status_line
    assert "hidden" in status_line

    manifest = func_body(source, "renderBackupManifest")
    assert "createElement" in manifest
    assert "textContent" in manifest
    assert "appendChild" in manifest
    assert "innerHTML" not in manifest

    for name in (
        "setSettingsBackupStatus",
        "setSettingsImportStatus",
        "setSettingsClearStatus",
        "renderBackupManifest",
        "exportEncryptedBackup",
        "previewEncryptedBackupManifest",
        "importEncryptedBackup",
        "clearAllLocalData",
        "setSettingsDangerControlsDisabled",
    ):
        assert _app_function_is_exposed(source, name)


def test_backup_export_keeps_passphrases_local_and_clears_inputs() -> None:
    body = func_body(_settings_source(), "exportEncryptedBackup")
    assert "var passphrase" in body
    assert "var confirmation" in body
    assert "App.bridge.exportEncryptedBackup(passphrase, confirmation)" in body
    assert 'passInput.value = ""' in body
    assert 'confirmInput.value = ""' in body
    assert "App.passphrase" not in body
    assert "App.confirmPassphrase" not in body
    assert "App.backupPassphrase" not in body


def test_import_and_clear_replace_data_through_one_generation_reset() -> None:
    source = _settings_source()
    for name, bridge_method in (
        ("importEncryptedBackup", "importEncryptedBackup"),
        ("clearAllLocalData", "clearAllLocalData"),
    ):
        body = func_body(source, name)
        assert "App.bridge." + bridge_method in body
        assert 'App.resetClientGeneration("database_replacement")' in body
        assert "loadSettingsPrivacyStatus()" in body
        assert "App.refreshAll" in body
        assert "renderBackupManifest(null" in body

    import_body = func_body(source, "importEncryptedBackup")
    assert 'passInput.value = ""' in import_body
    assert 'confirmInput.value = ""' in import_body
    clear_body = func_body(source, "clearAllLocalData")
    assert 'confirmInput.value = ""' in clear_body


def test_destructive_operations_require_explicit_confirmation_literals() -> None:
    source = _settings_source()
    assert 'IMPORT_CONFIRM_LITERAL = "导入并替换"' in source
    assert 'CLEAR_CONFIRM_LITERAL = "清空本地数据"' in source
    assert "confirmation.trim() !== IMPORT_CONFIRM_LITERAL" in source
    assert "confirmation.trim() !== CLEAR_CONFIRM_LITERAL" in source


def test_first_run_notice_is_fail_closed_and_mode_safe() -> None:
    source = _settings_source()
    render = func_body(source, "renderFirstRunNotice")
    assert 'mode === "view"' in render
    assert 'mode !== "view"' in render
    assert ".hidden" in render
    assert "textContent" in render

    blocking = func_body(source, "showFirstRunNoticeBlockingError")
    assert 'textContent = ""' in blocking
    assert "disabled = true" in blocking
    assert "hidden = true" in blocking

    load = func_body(source, "loadFirstRunNotice")
    assert "App.bridge.getFirstRunNotice()" in load
    assert "showFirstRunNoticeBlockingError" in load
    assert "App.firstRunNoticeRequired = true" in load

    hide = func_body(source, "hideFirstRunNotice")
    assert "App.bridge" not in hide
    assert "App.firstRunNoticeViewingFromSettings = false" in hide

    accept = func_body(source, "acceptFirstRunNotice")
    assert "App.bridge.acceptFirstRunNotice()" in accept
    assert "App.firstRunNoticeAcceptInProgress" in accept
    assert "App.refreshAll" in accept
    assert "loadSettingsPrivacyStatus()" in accept


def test_settings_buttons_are_bound_to_named_capabilities() -> None:
    body = func_body(read_js("init.js"), "initButtons")
    bindings = (
        ("settings-clipboard-toggle", "App.handleCaptureToggleChange"),
        ("settings-backup-export-btn", "App.exportEncryptedBackup"),
        ("settings-backup-manifest-btn", "App.previewEncryptedBackupManifest"),
        ("settings-backup-import-btn", "App.importEncryptedBackup"),
        ("settings-clear-local-data-btn", "App.clearAllLocalData"),
        ("first-run-notice-accept-btn", "App.acceptFirstRunNotice"),
        ("settings-privacy-notice-btn", "App.openPrivacyNoticeFromSettings"),
    )
    for dom_id, capability in bindings:
        assert dom_id in body
        assert capability in body
    assert "first-run-notice-close-btn" in body
    assert "App.firstRunNoticeViewingFromSettings" in body
    assert "App.hideFirstRunNotice" in body


def test_settings_styles_are_scoped() -> None:
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for selector in (
        ".settings-header",
        ".settings-loading",
        ".settings-error",
        ".settings-card",
        ".settings-backup-row",
        ".settings-backup-input",
        ".settings-backup-status",
        ".settings-backup-manifest",
        ".first-run-notice-overlay",
        ".first-run-notice-dialog",
        ".first-run-notice-error",
        ".settings-privacy-notice-btn",
    ):
        assert selector in styles
