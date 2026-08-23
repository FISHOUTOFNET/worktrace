"""Settings frontend ownership boundaries."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


pytestmark = [
    pytest.mark.contract,
    pytest.mark.webview_static,
    pytest.mark.security_privacy,
]

ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "worktrace" / "webview_ui"
JS_ROOT = UI_ROOT / "js"

OWNER_FILES = (
    "settings_presentation.js",
    "settings_transient_ui.js",
    "settings_data_operations.js",
    "settings_backup_recovery.js",
    "settings.js",
)


def source(name: str) -> str:
    return (JS_ROOT / name).read_text(encoding="utf-8")


def test_settings_owner_modules_are_loaded_before_the_coordinator() -> None:
    index = (UI_ROOT / "index_fd_work_v5.html").read_text(encoding="utf-8")
    spec = (ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    positions = []
    for name in OWNER_FILES:
        assert (JS_ROOT / name).is_file()
        positions.append(index.index(f'src="js/{name}?v='))
        assert f"'{name}'" in spec
    assert positions == sorted(positions)


def test_settings_coordinator_does_not_own_dom_presentation_or_transient_ui() -> None:
    coordinator = source("settings.js")
    for forbidden in (
        "textContent",
        "createElement",
        "appendChild",
        "querySelector",
        "querySelectorAll",
        "password-reveal-button",
        "settings-backup-passphrase",
        "settings-backup-manifest",
        "settings-section-",
        "first-run-notice-overlay",
        "settingsPrivacyNoticeReturnFocus",
        "settingsBackupManifestViewToken",
    ):
        assert forbidden not in coordinator
    for render_name in (
        "renderSettingsStatus",
        "renderBackupManifest",
        "renderFirstRunNotice",
        "renderRecoveryCard",
    ):
        assert not re.search(rf"function\s+{render_name}\s*\(", coordinator)


def test_presentation_is_stateless_and_never_calls_the_bridge() -> None:
    presentation = source("settings_presentation.js")
    assert "textContent" in presentation
    assert "renderSettingsStatus" in presentation
    assert "renderBackupManifest" in presentation
    assert "renderFirstRunNotice" in presentation
    assert "App.bridge" not in presentation
    for forbidden in (
        "activeOperation",
        "settingsSnapshot",
        "lastSettingsStatus",
        "RequestToken",
        "InProgress",
    ):
        assert forbidden not in presentation


def test_transient_ui_owns_sections_passwords_and_notice_view_state_only() -> None:
    transient = source("settings_transient_ui.js")
    coordinator = source("settings.js")
    for required in (
        "initPasswordRevealControls",
        "resetSettingsSectionTransientUi",
        "initSettingsCategories",
        "resetSettingsTransientUi",
    ):
        assert required in transient
        assert not re.search(rf"function\s+{required}\s*\(", coordinator)
    for private_state in ("privacyNoticeViewToken", "privacyNoticeReturnFocus"):
        assert private_state in transient
        assert private_state not in coordinator
    assert "App.bridge" not in transient
    assert "settingsSnapshot" not in transient


def test_all_settings_commands_share_one_operation_state_owner() -> None:
    operations = source("settings_data_operations.js")
    backup = source("settings_backup_recovery.js")
    combined = "\n".join(source(name) for name in OWNER_FILES)
    assert "activeOperations" in operations
    assert "runExclusive" in operations
    assert "runExclusive" in backup
    for retired in (
        "settingsWriteInProgress",
        "launchAtLoginWriteInProgress",
        "fdWorkSettingsWriteInProgress",
        "settingsBackupExportInProgress",
        "settingsBackupManifestInProgress",
        "settingsBackupImportInProgress",
        "settingsClearAllInProgress",
        "recoveryInProgress",
    ):
        assert retired not in combined
    assert "activeOperations" not in backup
    assert "activeOperations" not in source("settings.js")


def test_authoritative_settings_snapshot_has_one_owner() -> None:
    coordinator = source("settings.js")
    assert "settingsSnapshot" in coordinator
    assert "lastSettingsStatus" not in "\n".join(source(name) for name in OWNER_FILES)
    for name in OWNER_FILES[:-1]:
        assert "settingsSnapshot" not in source(name)


def test_bridge_capabilities_are_partitioned_by_owner() -> None:
    calls = {
        name: set(re.findall(r"\bApp\.bridge\.([A-Za-z0-9_]+)\s*\(", source(name)))
        for name in OWNER_FILES
    }
    assert calls["settings_presentation.js"] == set()
    assert calls["settings_transient_ui.js"] == set()
    assert calls["settings.js"] == {
        "acceptFirstRunNotice",
        "getFirstRunNotice",
        "getSettingsPrivacyStatus",
    }
    assert calls["settings_data_operations.js"] == {
        "setClipboardCaptureEnabled",
        "setFDWorkEnabled",
        "setLaunchAtLogin",
    }
    assert calls["settings_backup_recovery.js"] == {
        "clearAllLocalData",
        "exportEncryptedBackup",
        "importEncryptedBackup",
        "previewEncryptedBackupManifest",
        "recoverDatabaseMaintenance",
    }


def test_init_and_composition_only_use_settings_capabilities() -> None:
    init = source("init_fd_work_v5.js")
    composition = source("ui_composition.js")
    for private in (
        "App.firstRunNoticeLoading",
        "App.firstRunNoticeLoaded",
        "App.firstRunNoticeRequired",
        "App.firstRunNoticeAcceptInProgress",
        "App.firstRunNoticeViewingFromSettings",
        "App.privacyGateState",
        "App.settingsLoading",
        "App.settingsLoaded",
        "App.lastSettingsStatus",
    ):
        assert private not in init
        assert private not in composition
    assert "App.settings.privacy" in init
    assert "showSettingsError" not in composition
    assert "clearSettingsError" not in composition
    assert "reconnectFDWorkThroughSharedSession" not in composition


def test_backup_recovery_keeps_security_literals_and_secrets_local() -> None:
    backup = source("settings_backup_recovery.js")
    assert 'IMPORT_CONFIRM_LITERAL = "导入并替换"' in backup
    assert 'CLEAR_CONFIRM_LITERAL = "清空本地数据"' in backup
    assert "passphrase" in backup
    for forbidden in (
        "App.passphrase",
        "App.confirmPassphrase",
        "App.backupPassphrase",
        "localStorage",
        "sessionStorage",
        "innerHTML",
    ):
        assert forbidden not in backup
