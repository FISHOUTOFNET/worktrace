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
    "clearAllLocalData",
    "exportEncryptedBackup",
    "getSettingsPrivacyStatus",
    "importEncryptedBackup",
    "previewEncryptedBackupManifest",
    "recoverDatabaseMaintenance",
    "setClipboardCaptureEnabled",
    "setFDWorkEnabled",
    "setLaunchAtLogin",
}

SETTINGS_OWNER_FILES = (
    "settings_presentation.js",
    "settings_transient_ui.js",
    "settings_data_operations.js",
    "settings_backup_recovery.js",
    "settings.js",
)


def _settings_source() -> str:
    return read_js("settings.js")


def _presentation_source() -> str:
    return read_js("settings_presentation.js")


def _transient_source() -> str:
    return read_js("settings_transient_ui.js")


def _operations_source() -> str:
    return read_js("settings_data_operations.js")


def _backup_recovery_source() -> str:
    return read_js("settings_backup_recovery.js")


def _privacy_source() -> str:
    return read_js("privacy_notice.js")


def _all_settings_sources() -> str:
    return "\n".join(read_js(filename) for filename in SETTINGS_OWNER_FILES)


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
    index = (WEBVIEW_UI_DIR / "index_fd_work_v5.html").read_text(encoding="utf-8")
    section = html_section_by_id(index, "page-settings")
    positions = []
    for filename in SETTINGS_OWNER_FILES:
        assert (WEBVIEW_UI_DIR / "js" / filename).is_file()
        match = re.search(
            r'src="js/' + re.escape(filename) + r'\?v=[0-9a-f]+"',
            index,
        )
        assert match is not None
        positions.append(match.start())
    assert positions == sorted(positions)
    assert "设置与隐私" in section
    assert "管理本地数据、采集和备份" not in section
    for category in ("常规", "隐私", "数据与备份", "高级"):
        assert category in section
    assert 'data-settings-section="collection"' not in section
    assert 'id="settings-section-collection"' not in section

    required_ids = (
        "settings-error",
        "settings-loading",
        "settings-status",
        "settings-clipboard-toggle",
        "settings-clipboard-toggle-status",
        "settings-launch-at-login-toggle",
        "settings-launch-at-login-toggle-status",
        "settings-fd-work-toggle",
        "settings-fd-work-toggle-status",
        "settings-fd-work-reconnect",
        "settings-backup-passphrase",
        "settings-backup-passphrase-confirm",
        "settings-backup-export-btn",
        "settings-backup-manifest-btn",
        "settings-backup-status",
        "settings-backup-manifest",
        "settings-backup-import-passphrase",
        "settings-backup-passphrase-reveal",
        "settings-backup-passphrase-confirm-reveal",
        "settings-backup-import-passphrase-reveal",
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
        "first-run-notice-retry-btn",
    )
    for dom_id in required_ids:
        assert 'id="' + dom_id + '"' in index

    for forbidden_id in (
        "settings-backup-import-confirm",
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


def test_settings_toggle_layout_and_copy_contract() -> None:
    index = (WEBVIEW_UI_DIR / "index_fd_work_v5.html").read_text(encoding="utf-8")
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    source = _presentation_source()

    for status_id, checkbox_id in (
        (
            "settings-launch-at-login-toggle-status",
            "settings-launch-at-login-toggle",
        ),
        ("settings-clipboard-toggle-status", "settings-clipboard-toggle"),
        ("settings-fd-work-toggle-status", "settings-fd-work-toggle"),
    ):
        row = re.search(
            r'<label[^>]*for="' + re.escape(checkbox_id) + r'"[^>]*>(.*?)</label>',
            index,
            re.DOTALL,
        )
        assert row is not None
        assert row.group(1).index(f'id="{status_id}"') < row.group(1).index(
            f'id="{checkbox_id}"'
        )
        assert f'id="{status_id}" class="toggle-status"' in row.group(1)

    assert "关闭主窗口后 WorkTrace 会继续在通知区域后台运行。" not in index
    assert "settings-help" not in index
    assert ".settings-help" not in styles

    toggle_wrap = re.search(r"\.toggle-wrap\s*\{([^}]*)\}", styles)
    assert toggle_wrap is not None
    assert "justify-self: end" in toggle_wrap.group(1)
    assert "justify-content: flex-end" in toggle_wrap.group(1)
    assert "align-items: center" in toggle_wrap.group(1)

    toggle_status = re.search(r"\.toggle-status\s*\{([^}]*)\}", styles)
    assert toggle_status is not None
    assert "text-align: right" in toggle_status.group(1)
    assert "white-space: nowrap" in toggle_status.group(1)

    assert '"仅安装版可用"' in func_body(source, "renderLaunchAtLoginToggle")


def test_settings_resource_is_packaged() -> None:
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    for filename in SETTINGS_OWNER_FILES:
        assert filename in spec


def test_settings_uses_only_fixed_allowed_bridge_capabilities() -> None:
    source = _all_settings_sources()
    calls = set(re.findall(r"\bApp\.bridge\.([A-Za-z0-9_]+)\s*\(", source))
    assert calls == SETTINGS_BRIDGE_METHODS
    assert "App.callBridge" not in source
    assert "window.pywebview" not in source
    assert "invokeBridge(" not in source


def test_settings_has_no_network_storage_or_unsafe_dom_paths() -> None:
    source = _all_settings_sources()
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
    assert "textContent" in _presentation_source()


def test_settings_operation_state_has_one_cross_operation_guard() -> None:
    source = _all_settings_sources()
    operations = _operations_source()
    backup = _backup_recovery_source()
    retired_flags = (
        "settingsLoading",
        "settingsWriteInProgress",
        "launchAtLoginWriteInProgress",
        "settingsBackupExportInProgress",
        "settingsBackupManifestInProgress",
        "settingsBackupImportInProgress",
        "settingsClearAllInProgress",
        "recoveryInProgress",
    )
    for flag in retired_flags:
        assert "App." + flag not in source

    assert "var activeOperations = {};" in operations
    assert 'var blockingOperation = "";' in operations
    assert "function runExclusive" in operations
    assert "exclusive && isBusy()" in operations
    assert "activeOperations" not in backup

    for operation in (
        "exportEncryptedBackup",
        "previewEncryptedBackupManifest",
        "importEncryptedBackup",
        "clearAllLocalData",
    ):
        body = func_body(backup, operation)
        assert "operations.isUnavailable()" in body
        assert "operations.runExclusive" in body

    recovery = func_body(backup, "recoverDatabaseMaintenance")
    assert 'operations.runExclusive("recovery"' in recovery
    assert "requestAuthoritativeRecoveryRefresh" in recovery


def test_settings_loading_and_clipboard_controls_have_separate_semantics() -> None:
    source = _settings_source()
    presentation = _presentation_source()
    operations = _operations_source()
    load_body = func_body(source, "loadSettingsPrivacyStatus")
    assert "var showLoading" in load_body
    assert "if (showLoading)" in load_body
    assert "settingsLoading = true" in load_body
    assert "settingsLoadPromise" in load_body
    assert "settingsRequestToken" in load_body
    assert "App.bridge.getSettingsPrivacyStatus()" in load_body
    assert "acceptSettingsSnapshot" in load_body

    controls = func_body(presentation, "setSettingsControlsState")
    assert "!loaded" in controls
    backup_controls = func_body(presentation, "setSettingsBackupControlsDisabled")
    danger_controls = func_body(presentation, "setSettingsDangerControlsDisabled")
    assert "settingsLoaded" not in backup_controls
    assert "settingsLoaded" not in danger_controls
    assert "disabled" in backup_controls
    assert "disabled" in danger_controls

    toggle = func_body(operations, "setCaptureEnabled")
    assert 'runMutation("clipboard_write"' in toggle
    assert "App.bridge.setClipboardCaptureEnabled" in toggle
    assert 'operationIs("launch_at_login_write")' not in toggle
    launch_toggle = func_body(operations, "setLaunchAtLoginEnabled")
    assert 'runMutation("launch_at_login_write"' in launch_toggle
    assert "App.bridge.setLaunchAtLogin" in launch_toggle
    assert 'operationIs("clipboard_write")' not in launch_toggle


def test_settings_status_and_manifest_render_through_safe_helpers() -> None:
    source = _presentation_source()
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
        "setSettingsDangerControlsDisabled",
    ):
        assert name in source

    backup = _backup_recovery_source()
    for name in (
        "exportEncryptedBackup",
        "previewEncryptedBackupManifest",
        "importEncryptedBackup",
        "clearAllLocalData",
    ):
        assert "function " + name in backup


def test_settings_exposes_transient_reset_without_clearing_authoritative_state() -> None:
    source = _transient_source()
    assert _app_function_is_exposed(source, "resetSettingsTransientUi")
    reset = func_body(source, "resetSettingsTransientUi")
    for dom_id in (
        "settings-backup-passphrase",
        "settings-backup-passphrase-confirm",
        "settings-backup-import-passphrase",
        "settings-clear-confirm",
    ):
        assert dom_id in reset
    assert "renderBackupManifest(null" in reset
    assert "privacyNoticeMode" not in reset
    assert "hideFirstRunNotice" not in reset
    for preserved in (
        "settingsLoaded =",
        "lastSettingsStatus =",
        "settingsBackupExportInProgress =",
        "settingsBackupImportInProgress =",
        "settingsClearAllInProgress =",
        "recoveryInProgress =",
        "privacyGateState =",
    ):
        assert preserved not in reset


def test_backup_export_keeps_passphrases_local_and_clears_inputs() -> None:
    body = func_body(_backup_recovery_source(), "exportEncryptedBackup")
    assert "var passphrase" in body
    assert "var confirmation" in body
    assert "App.bridge.exportEncryptedBackup(passphrase, confirmation)" in body
    assert 'passInput.value = ""' in body
    assert 'confirmInput.value = ""' in body
    assert "App.passphrase" not in body
    assert "App.confirmPassphrase" not in body
    assert "App.backupPassphrase" not in body


def test_import_and_clear_replace_data_through_one_generation_reset() -> None:
    source = _backup_recovery_source()
    for name, bridge_method in (
        ("importEncryptedBackup", "importEncryptedBackup"),
        ("clearAllLocalData", "clearAllLocalData"),
    ):
        body = func_body(source, name)
        assert "App.bridge." + bridge_method in body
        assert "deps.afterDataReplacement()" in body
        assert "cancelManifestPreview()" in body

    replacement = func_body(_settings_source(), "afterDataReplacement")
    assert 'App.resetClientGeneration("database_replacement")' in replacement
    assert "requestSettingsRefresh()" in replacement
    assert "App.refreshAll" in replacement

    import_body = func_body(source, "importEncryptedBackup")
    assert 'passInput.value = ""' in import_body
    assert "App.openConfirmDialog" in import_body
    assert "IMPORT_CONFIRM_LITERAL" in import_body
    import_section = source[
        source.index("function importEncryptedBackup") :
        source.index("function clearAllLocalData")
    ]
    assert "confirmInput" not in import_section
    clear_body = func_body(source, "clearAllLocalData")
    assert 'confirmInput.value = ""' in clear_body


def test_destructive_operations_require_explicit_confirmation_literals() -> None:
    source = _backup_recovery_source()
    assert 'IMPORT_CONFIRM_LITERAL = "导入并替换"' in source
    assert 'CLEAR_CONFIRM_LITERAL = "清空本地数据"' in source
    import_body = func_body(source, "importEncryptedBackup")
    assert "App.bridge.importEncryptedBackup" in import_body
    assert "IMPORT_CONFIRM_LITERAL" in import_body
    assert "settings-backup-import-confirm" not in source
    assert "confirmation.trim() !== CLEAR_CONFIRM_LITERAL" in source


def test_credentials_use_compact_rows_and_momentary_reveal_controls() -> None:
    index = (WEBVIEW_UI_DIR / "index_fd_work_v5.html").read_text(encoding="utf-8")
    section = index[
        index.index('id="settings-backup-card"') :
        index.index('id="settings-recovery-card"')
    ]
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    source = _transient_source()

    assert section.count('class="credential-row"') == 3
    assert section.count('class="password-reveal-button"') == 3
    assert section.count('aria-label="按住查看口令"') == 3
    assert section.count('aria-pressed="false"') >= 3
    assert "form-grid" not in section
    assert "settings-backup-import-confirm" not in section
    assert "确认文字" not in section[
        section.index('id="settings-backup-card"') :
        section.index('id="settings-danger-card"')
    ]
    assert 'id="icon-eye"' in index and 'id="icon-eye-off"' in index
    assert "grid-template-columns: 72px minmax(0, 22ch)" in styles
    assert "max-width: 236px" in styles
    for event_name in (
        "pointerdown",
        "pointerup",
        "pointercancel",
        "pointerleave",
        "lostpointercapture",
        "keydown",
        "keyup",
        "pagehide",
    ):
        assert event_name in source
    assert 'event.key === "Escape"' in source
    assert "hideAllPasswordFields" in func_body(source, "resetSettingsTransientUi")
    assert "initPasswordRevealControls();" in func_body(source, "bindEvents")
    coordinator = _settings_source()
    assert "transientUi.hideAllPasswordFields()" in coordinator


def test_danger_zone_removes_only_its_local_divider_and_status_gap() -> None:
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    global_row = re.search(r"\.setting-row\s*\{([^}]*)\}", styles)
    danger_row = re.search(r"\.danger-zone \.setting-row\s*\{([^}]*)\}", styles)
    clear_status = re.search(r"#settings-clear-status\s*\{([^}]*)\}", styles)
    danger = re.search(r"\.danger-zone\s*\{([^}]*)\}", styles)
    assert global_row is not None and "border-bottom: 1px solid" in global_row.group(1)
    assert danger_row is not None
    assert "border-bottom: 0" in danger_row.group(1)
    assert "padding-bottom: 4px" in danger_row.group(1)
    assert clear_status is not None
    assert "margin: 4px 0 0" in clear_status.group(1)
    assert "min-height: 0" in clear_status.group(1)
    assert danger is not None
    assert "border: 1px solid #e4aaa5" in danger.group(1)
    assert "background: #fffafa" in danger.group(1)


def test_first_run_notice_is_fail_closed_and_mode_safe() -> None:
    source = _privacy_source()
    render = func_body(source, "renderNotice")
    assert 'mode === "view"' in render
    assert 'mode !== "view"' in render
    assert ".hidden" in render
    assert "textContent" in render
    assert "first-run-notice-retry-btn" in render

    blocking = func_body(source, "renderBlockingError")
    assert 'textContent = ""' in blocking
    assert "disabled = true" in blocking
    assert "hidden = true" in blocking
    assert "first-run-notice-retry-btn" in blocking

    load = func_body(source, "loadGate")
    assert "App.bridge.getFirstRunNotice()" in load
    assert "showBlockingError" in load
    assert 'setGateState("acceptance_required")' in load

    gate = func_body(source, "setGateState")
    assert "gateState = String" in gate
    assert "App." not in gate

    hide = func_body(source, "hideNotice")
    assert "App.bridge" not in hide
    assert 'noticeMode = ""' in hide

    accept = func_body(source, "acceptGate")
    assert "App.bridge.acceptFirstRunNotice()" in accept
    assert "noticeAccepting" in accept
    assert "App.continueStartupAfterPrivacyGate" not in accept
    assert "loadSettingsPrivacyStatus" not in accept


def test_settings_buttons_are_bound_to_named_capabilities() -> None:
    coordinator = func_body(_settings_source(), "bindSettingsEvents")
    assert "operations.bindEvents()" in coordinator
    assert "backupRecovery.bindEvents()" in coordinator
    assert "transientUi.bindEvents" in coordinator
    operations = func_body(_operations_source(), "bindEvents")
    for dom_id in (
        "settings-clipboard-toggle",
        "settings-launch-at-login-toggle",
        "settings-fd-work-toggle",
        "settings-fd-work-reconnect",
    ):
        assert dom_id in operations
    backup = func_body(_backup_recovery_source(), "bindEvents")
    for dom_id in (
        "settings-backup-export-btn",
        "settings-backup-manifest-btn",
        "settings-backup-import-btn",
        "settings-clear-local-data-btn",
        "settings-recovery-btn",
    ):
        assert dom_id in backup
    transient = func_body(_transient_source(), "bindEvents")
    assert "settings-privacy-notice-btn" in transient
    assert "first-run-notice-close-btn" not in transient
    global_bindings = func_body(read_js("init_fd_work_v5.js"), "initButtons")
    assert "first-run-notice-accept-btn" in global_bindings
    assert "App.privacyNotice.acceptGate" in global_bindings
    assert "first-run-notice-retry-btn" in global_bindings
    assert "App.privacyNotice.retryGate" in global_bindings


def test_settings_styles_are_scoped() -> None:
    styles = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for selector in (
        ".settings-layout",
        ".settings-categories",
        ".settings-content",
        ".settings-section",
        ".setting-row",
        ".settings-backup-card",
        ".backup-manifest",
        ".first-run-dialog",
        ".danger-zone",
    ):
        assert selector in styles
