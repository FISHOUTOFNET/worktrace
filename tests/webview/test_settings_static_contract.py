"""Settings / Privacy WebView static-contract tests.

These tests read the bundled frontend resources (``index.html`` /
``js/*.js`` / ``styles.css`` / ``WorkTrace.spec``) directly without starting
the GUI. They lock the Settings / Privacy page contracts (read-only status
foundation + clipboard capture toggle write + encrypted backup export +
encrypted backup manifest preview + encrypted backup import +
clear-all-local-data) and the first-run privacy notice gate (read-only
view from Settings): the required DOM ids must exist, ``settings.js`` must
be loaded in the correct order, and the JS may only call
``get_settings_privacy_status``, ``set_clipboard_capture_enabled``,
``export_encrypted_backup``, ``preview_encrypted_backup_manifest``,
``import_encrypted_backup``, ``clear_all_local_data``,
``get_first_run_notice``, and ``accept_first_run_notice`` (no save /
set-setting / parse-manifest / arbitrary file-dialog write paths).
"""

from __future__ import annotations

import os
import re
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import (
    REPO_ROOT, WEBVIEW_UI_DIR, JS_DIR, ALL_JS_FILES,
    read_resource, read_all_js, read_js,
)


# --- Page migration + sidebar nav ---------------------------------------


def test_index_html_settings_nav_entry_exists() -> None:
    """the sidebar nav must still contain the 设置与隐私 entry."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-page="settings"' in source
    assert "设置与隐私" in source


def test_index_html_settings_page_section_is_complete() -> None:
    """the page-settings section must not contain the old
    unavailable-feature placeholder copy."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-settings"')
    assert pos != -1, "page-settings section must exist"
    section = source[pos:pos + 1200]
    assert "WebView 迁移中" not in section
    # The page must announce its purpose in user language.
    assert "设置与隐私" in section
    assert "管理本地隐私设置" in section


def test_index_html_settings_page_no_refresh_status_text() -> None:
    """The Settings page must not contain a resident '刷新状态' button
    or label. Status is auto-refreshed on page entry and after operations."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-settings"')
    assert pos != -1
    end = source.find("</section>", pos)
    section = source[pos:end]
    assert "刷新状态" not in section, (
        "Settings page must not contain '刷新状态'; the refresh button "
        "has been removed"
    )


def test_index_html_settings_page_no_unavailable_write_text() -> None:
    """The Settings page must not contain unavailable write restriction
    copy like '其他写操作暂不开放'."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-settings"')
    assert pos != -1
    end = source.find("</section>", pos)
    section = source[pos:end]
    assert "其他写操作暂不开放" not in section, (
        "Settings page must not contain '其他写操作暂不开放'"
    )


def test_index_html_no_unavailable_feature_copy_in_main_ui() -> None:
    """The main UI (index.html user-visible DOM text) must NOT contain
    unavailable-feature copy. These phrases imply a future roadmap and should be
    removed or rewritten in user language. This test only checks
    user-visible DOM text in index.html, NOT JS comments, Python
    docstrings, docs, or test descriptions."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for forbidden in (
        "后续阶段",
        "暂未开放",
        "暂不开放",
        "暂不支持",
        "其他写操作暂不开放",
        "当前支持查看",
        "本阶段",
    ):
        assert forbidden not in source, (
            "index.html must not contain unavailable-feature copy: " + forbidden
        )


def test_index_html_settings_required_dom_ids() -> None:
    """The page-settings section must define the required DOM ids."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for dom_id in (
        "settings-error",
        "settings-loading",
        "settings-status",
        "settings-storage-card",
        "settings-privacy-card",
        "settings-backup-card",
        "settings-danger-card",
        # clipboard capture toggle control
        "settings-clipboard-toggle",
        "settings-clipboard-toggle-label",
        "settings-clipboard-toggle-status",
        # encrypted backup export + manifest preview controls
        "settings-backup-passphrase",
        "settings-backup-passphrase-confirm",
        "settings-backup-export-btn",
        "settings-backup-manifest-btn",
        "settings-backup-status",
        "settings-backup-manifest",
        # encrypted backup import + clear-all controls
        "settings-backup-import-passphrase",
        "settings-backup-import-confirm",
        "settings-backup-import-btn",
        "settings-backup-import-status",
        "settings-clear-confirm",
        "settings-clear-local-data-btn",
        "settings-clear-status",
    ):
        assert 'id="' + dom_id + '"' in source, (
            "index.html must define DOM id: " + dom_id
        )


# --- JS load order + packaging ------------------------------------------


def test_index_html_loads_settings_js() -> None:
    """index.html must load ``js/settings.js`` exactly once and
    in the position required by ``ALL_JS_FILES`` (between ``statistics.js``
    and ``rules.js``)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(
        r'<script\s+src="js/([^"]+)"\s*>\s*</script>', source
    )
    assert "settings.js" in scripts, "index.html must load js/settings.js"
    assert scripts.count("settings.js") == 1, (
        "index.html must load settings.js exactly once"
    )
    assert scripts == ALL_JS_FILES, (
        "index.html script order must match ALL_JS_FILES exactly"
    )


def test_all_js_files_includes_settings_js() -> None:
    """``ALL_JS_FILES`` must include ``settings.js`` between
    ``statistics.js`` and ``rules.js``."""
    assert "settings.js" in ALL_JS_FILES
    stats_idx = ALL_JS_FILES.index("statistics.js")
    settings_idx = ALL_JS_FILES.index("settings.js")
    rules_idx = ALL_JS_FILES.index("rules.js")
    assert stats_idx < settings_idx < rules_idx, (
        "settings.js must load after statistics.js and before rules.js"
    )


def test_worktrace_spec_bundles_settings_js() -> None:
    """``WorkTrace.spec`` must bundle ``settings.js`` so the
    PyInstaller build ships the new module."""
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "settings.js" in spec, (
        "WorkTrace.spec must include settings.js in datas"
    )


def test_settings_js_exists_on_disk() -> None:
    """the ``settings.js`` module file must exist on disk."""
    assert (JS_DIR / "settings.js").is_file(), (
        "worktrace/webview_ui/js/settings.js must exist"
    )


# --- JS contract: read-only status load ----------------------------------


def test_settings_js_defines_load_settings_privacy_status() -> None:
    """settings.js must define ``App.loadSettingsPrivacyStatus``
    and call ``App.callBridge("get_settings_privacy_status")``."""
    source = read_js("settings.js")
    assert "App.loadSettingsPrivacyStatus" in source
    assert 'App.callBridge("get_settings_privacy_status")' in source


def test_settings_js_only_calls_allowed_bridge_methods() -> None:
    """settings.js may only call ``get_settings_privacy_status``,
    ``set_clipboard_capture_enabled``, ``export_encrypted_backup``,
    ``preview_encrypted_backup_manifest``, ``import_encrypted_backup``,
    ``clear_all_local_data``, ``get_first_run_notice``, and
    ``accept_first_run_notice``. All other write-side bridge methods
    remain forbidden (``parse_encrypted_backup_manifest`` is the API
    facade name, not the bridge method; ``set_setting_value`` is the
    raw settings write facade and must not be called from JS)."""
    source = read_js("settings.js")
    # The eight allowed Settings bridge method names must be present.
    assert 'App.callBridge("get_settings_privacy_status")' in source
    assert 'App.callBridge("set_clipboard_capture_enabled"' in source
    assert 'App.callBridge("export_encrypted_backup"' in source
    assert 'App.callBridge("preview_encrypted_backup_manifest"' in source
    assert 'App.callBridge("import_encrypted_backup"' in source
    assert 'App.callBridge("clear_all_local_data"' in source
    # first-run notice gate + read-only view bridge methods.
    assert 'App.callBridge("get_first_run_notice")' in source
    assert 'App.callBridge("accept_first_run_notice")' in source
    # Every other write-side bridge method is still forbidden. Note:
    # ``parse_encrypted_backup_manifest`` is the API facade name, not the
    # bridge method name; the bridge method is ``preview_encrypted_backup_manifest``
    # and must not be confused with the parse facade. We check for
    # ``App.callBridge("<forbidden>"`` so forbidden names that appear in
    # comments / docstrings are not falsely flagged.
    for forbidden in (
        "parse_encrypted_backup_manifest",
        "set_setting_value",
        "save_settings",
    ):
        assert 'App.callBridge("' + forbidden + '"' not in source, (
            "settings.js must not call bridge method: " + forbidden
        )


def test_settings_js_does_not_use_network_or_storage_apis() -> None:
    """settings.js must not use any network, storage, or browser clipboard API."""
    source = read_js("settings.js")
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "navigator.clipboard",
    ):
        assert forbidden not in source, (
            "settings.js must not use: " + forbidden
        )


def test_settings_js_catch_does_not_read_error_message() -> None:
    """settings.js catch blocks must not read ``.message`` on
    the caught error (never surface raw exception text)."""
    source = read_js("settings.js")
    # ``.message`` access would appear as either ``err.message`` or
    # ``error.message`` in classic IIFE code.
    for forbidden in ("err.message", "error.message", "e.message"):
        assert forbidden not in source, (
            "settings.js must not read .message in catch: " + forbidden
        )


def test_settings_js_uses_text_content_not_inner_html() -> None:
    """settings.js dynamic rendering must use ``textContent``;
    ``innerHTML`` is forbidden for dynamic content."""
    source = read_js("settings.js")
    assert "textContent" in source
    assert "innerHTML" not in source


def test_settings_js_no_clickable_write_buttons() -> None:
    """The Settings / Privacy page must not surface any clickable save /
    clipboard-toggle write button. The encrypted backup export and manifest
    preview buttons are allowed, as is the scoped import button
    (``settings-backup-import-btn``) and the scoped clear-all button
    (``settings-clear-local-data-btn``). The precise allowed / forbidden
    DOM ids are locked by ``test_index_html_no_forbidden_settings_buttons``."""
    source = read_js("settings.js")
    lowered = source.lower()
    for forbidden in (
        "savebtn",
        "save_btn",
        "save-button",
        "toggleclipbtn",
        "toggle_clip_btn",
        "clipboardtogglebtn",
        "clipboard_toggle_btn",
    ):
        assert forbidden not in lowered, (
            "settings.js must not wire write button: " + forbidden
        )


def test_index_html_no_settings_write_buttons() -> None:
    """index.html page-settings must not include any
    save / path / file-dialog write button id, and must not include the
    ambiguous shortcut ids (without the ``-backup-`` / ``-clear-local-data``
    segments). The import/clear allows the scoped ``settings-backup-import-btn``
    and ``settings-clear-local-data-btn`` ids; the ambiguous shortcut ids
    ``settings-import-btn`` / ``settings-clear-btn`` /
    ``settings-clear-all-btn`` remain forbidden. The clipboard toggle is
    a checkbox (``settings-clipboard-toggle``), not a button; a
    ``settings-clipboard-toggle-btn`` id is still forbidden."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-settings"')
    assert pos != -1
    end = source.find("</section>", pos)
    section = source[pos:end]
    for forbidden in (
        "settings-save-btn",
        "settings-export-btn",
        "settings-import-btn",
        "settings-clear-btn",
        "settings-clear-all-btn",
        "settings-clipboard-toggle-btn",
        "settings-save-path-btn",
        "settings-set-path-btn",
        # explicit forbidden ids from the spec.
        "settings-path-btn",
        "settings-file-dialog-btn",
        "settings-manifest-btn",
    ):
        assert forbidden not in section, (
            "index.html page-settings must not contain write button id: "
            + forbidden
        )


def test_settings_js_state_variables_declared() -> None:
    """core.js must declare the settings state variables used by
    the lazy-load guard (settingsLoaded / settingsLoading /
    settingsRequestToken)."""
    source = read_js("core.js")
    for token in (
        "settingsLoaded",
        "settingsLoading",
        "settingsRequestToken",
    ):
        assert token in source, (
            "core.js must declare settings state variable: " + token
        )


def test_settings_js_lazy_load_in_switch_page() -> None:
    """switchPage must lazy-load the settings status when
    navigating to the page for the first time."""
    source = read_js("init.js")
    pos = source.find("function switchPage")
    assert pos != -1
    body = source[pos:pos + 3500]
    assert '"settings"' in body or "'settings'" in body
    assert "loadSettingsPrivacyStatus" in body


def test_settings_js_no_refresh_button_binding_in_init_buttons() -> None:
    """The settings-refresh-btn DOM id must not appear in init.js because
    the Settings page no longer has a resident refresh button. Status is
    auto-refreshed on page entry and after operations."""
    source = read_js("init.js")
    assert "settings-refresh-btn" not in source, (
        "init.js must not reference settings-refresh-btn; the refresh "
        "button has been removed from the Settings page"
    )


# --- Stylesheet ----------------------------------------------------------


def test_styles_css_has_settings_scoped_classes() -> None:
    """styles.css must scope the Settings / Privacy page CSS
    under ``settings-*`` classes."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (
        ".settings-header",
        ".settings-subtitle",
        ".settings-loading",
        ".settings-error",
        ".settings-status",
        ".settings-card",
        ".settings-storage-card",
        ".settings-privacy-card",
        ".settings-backup-card",
        ".settings-danger-card",
    ):
        assert cls in source, "styles.css must define class: " + cls


# --- clipboard capture toggle write contract ------------------


def test_core_js_declares_settings_write_in_progress() -> None:
    """core.js must declare ``settingsWriteInProgress`` so the
    toggle write guard is separate from the read-state ``settingsLoading``
    flag (a write in flight must not pollute the read-state guard)."""
    source = read_js("core.js")
    assert "settingsWriteInProgress" in source, (
        "core.js must declare settingsWriteInProgress"
    )


def test_settings_js_defines_toggle_write_helpers() -> None:
    """settings.js must define the toggle write helper functions
    (setSettingsControlsDisabled / setCaptureToggleStatus /
    renderCaptureToggle / setCaptureEnabled /
    handleCaptureToggleChange)."""
    source = read_js("settings.js")
    for name in (
        "setSettingsControlsDisabled",
        "setCaptureToggleStatus",
        "renderCaptureToggle",
        "setCaptureEnabled",
        "handleCaptureToggleChange",
    ):
        assert "function " + name in source, (
            "settings.js must define function: " + name
        )
        assert "App." + name in source, (
            "settings.js must expose App." + name
        )


def test_settings_js_toggle_change_handler_bound_in_init() -> None:
    """initButtons must bind the ``settings-clipboard-toggle``
    change event to ``App.handleCaptureToggleChange`` so the toggle
    write path is wired without a separate submit button."""
    source = read_js("init.js")
    pos = source.find("function initButtons")
    assert pos != -1
    body = source[pos:pos + 8000]
    assert "settings-clipboard-toggle" in body
    assert "handleCaptureToggleChange" in body
    assert '"change"' in body or "'change'" in body


def test_settings_js_disables_controls_during_load_and_write() -> None:
    """settings.js must disable the refresh button, the
    capture toggle, and the backup controls while any Settings operation
    is in flight. The backup operations use ``anySettingsOperationInProgress``
    which combines ``settingsLoading``, ``settingsWriteInProgress``,
    ``settingsBackupExportInProgress``, and ``settingsBackupManifestInProgress``;
    ``setSettingsLoading`` and ``renderCaptureToggle`` delegate to it so
    all four flags block every Settings control."""
    source = read_js("settings.js")
    # The shared disable helper must exist.
    pos = source.find("function setSettingsControlsDisabled")
    assert pos != -1
    # anySettingsOperationInProgress must exist and reference all four flags.
    any_pos = source.find("function anySettingsOperationInProgress")
    assert any_pos != -1
    any_body = source[any_pos:any_pos + 600]
    for flag in (
        "settingsLoading",
        "settingsWriteInProgress",
        "settingsBackupExportInProgress",
        "settingsBackupManifestInProgress",
    ):
        assert flag in any_body, (
            "anySettingsOperationInProgress must reference flag: " + flag
        )
    # setSettingsLoading must delegate to anySettingsOperationInProgress.
    loading_pos = source.find("function setSettingsLoading")
    assert loading_pos != -1
    loading_body = source[loading_pos:loading_pos + 600]
    assert "anySettingsOperationInProgress" in loading_body
    # renderCaptureToggle must also disable on the combined flag + not-yet-loaded.
    render_pos = source.find("function renderCaptureToggle")
    assert render_pos != -1
    render_body = source[render_pos:render_pos + 800]
    assert "anySettingsOperationInProgress" in render_body
    assert "settingsLoaded" in render_body


def test_settings_js_toggle_write_failure_recovers_state() -> None:
    """the toggle write path must restore the previous checked
    state (``!enabled``) on failure so the UI never shows a stale toggle.
    Both the data-failure branch (``!data``) and the catch block must
    contain the restore logic."""
    source = read_js("settings.js")
    pos = source.find("function setCaptureEnabled")
    assert pos != -1
    body = source[pos:pos + 2500]
    # The catch block must restore the toggle and show a stable error.
    assert "WRITE_ERROR_MESSAGE" in body
    assert "toggle.checked = !enabled" in body
    # The catch block must not read .message.
    for forbidden in ("err.message", "error.message", "e.message"):
        assert forbidden not in body, (
            "setCaptureEnabled must not read .message: " + forbidden
        )
    # The finally-style trailing .then must clear the write flag and
    # re-enable controls based on the read-state flag.
    assert "settingsWriteInProgress = false" in body


def test_settings_js_render_status_syncs_toggle() -> None:
    """renderSettingsStatus must call renderCaptureToggle so
    the toggle's checked / disabled / status text is re-synced from the
    latest status snapshot after both a successful read and a successful
    write."""
    source = read_js("settings.js")
    pos = source.find("function renderSettingsStatus")
    assert pos != -1
    body = source[pos:pos + 1200]
    assert "renderCaptureToggle" in body


def test_styles_css_has_toggle_classes() -> None:
    """styles.css must define the ``.settings-*`` toggle classes
    used by the clipboard capture toggle row."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (
        ".settings-toggle-row",
        ".settings-toggle-label",
        ".settings-toggle-control",
        ".settings-toggle-status",
    ):
        assert cls in source, (
            "styles.css must define toggle class: " + cls
        )


# --- encrypted backup export + manifest preview contract ------


def test_core_js_declares_settings_backup_state() -> None:
    """core.js must declare ``settingsBackupExportInProgress``
    and ``settingsBackupManifestInProgress`` as separate state flags so
    backup operations never race the clipboard toggle write."""
    source = read_js("core.js")
    assert "settingsBackupExportInProgress" in source, (
        "core.js must declare settingsBackupExportInProgress"
    )
    assert "settingsBackupManifestInProgress" in source, (
        "core.js must declare settingsBackupManifestInProgress"
    )


def test_settings_js_defines_backup_helpers() -> None:
    """settings.js must define and expose the backup helper
    functions (setSettingsBackupControlsDisabled / setSettingsBackupStatus
    / clearSettingsBackupStatus / renderBackupManifest /
    exportEncryptedBackup / previewEncryptedBackupManifest)."""
    source = read_js("settings.js")
    for name in (
        "setSettingsBackupControlsDisabled",
        "setSettingsBackupStatus",
        "clearSettingsBackupStatus",
        "renderBackupManifest",
        "exportEncryptedBackup",
        "previewEncryptedBackupManifest",
    ):
        assert "function " + name in source, (
            "settings.js must define function: " + name
        )
        assert "App." + name in source, (
            "settings.js must expose App." + name
        )


def test_settings_js_backup_catch_does_not_read_error_message() -> None:
    """the backup export / manifest preview catch blocks must
    not read ``.message`` on the caught error (never surface raw
    exception text)."""
    source = read_js("settings.js")
    # The whole module must not read .message in any catch.
    for forbidden in ("err.message", "error.message", "e.message"):
        assert forbidden not in source, (
            "settings.js must not read .message in catch: " + forbidden
        )


def test_settings_js_backup_render_uses_text_content() -> None:
    """renderBackupManifest must render manifest fields via
    ``textContent`` only; ``innerHTML`` is already forbidden module-wide."""
    source = read_js("settings.js")
    pos = source.find("function renderBackupManifest")
    assert pos != -1
    body = source[pos:pos + 1500]
    assert "textContent" in body
    assert "innerHTML" not in body
    assert "createElement" in body


def test_settings_js_backup_does_not_persist_passphrase() -> None:
    """the passphrase must never be saved to ``App`` global
    state. The export function reads the input values into local
    variables and clears the inputs after the call; it must NOT assign
    the passphrase to any ``App.`` property."""
    source = read_js("settings.js")
    pos = source.find("function exportEncryptedBackup")
    assert pos != -1
    body = source[pos:pos + 2500]
    # The passphrase must be read into a local variable, not App state.
    assert "var passphrase" in body
    assert "var confirmPassphrase" in body
    # The function must clear the password inputs after the call.
    assert "passInput.value = \"\"" in body or 'passInput.value = ""' in body
    assert "passConfirmInput.value = \"\"" in body or 'passConfirmInput.value = ""' in body
    # The function must NOT assign passphrase to any App.* property.
    # Look for "App.passphrase" or "App." followed by a passphrase-like
    # assignment pattern anywhere in the export function body.
    assert "App.passphrase" not in body
    assert "App.confirmPassphrase" not in body
    assert "App.backupPassphrase" not in body


def test_settings_js_backup_no_inner_html_in_manifest_render() -> None:
    """the manifest preview rendering must never use
    ``innerHTML``; only ``textContent`` and ``createElement`` are
    allowed for dynamic content."""
    source = read_js("settings.js")
    assert "innerHTML" not in source


def test_init_js_binds_backup_buttons() -> None:
    """initButtons must bind the ``settings-backup-export-btn``
    click event to ``App.exportEncryptedBackup`` and the
    ``settings-backup-manifest-btn`` click event to
    ``App.previewEncryptedBackupManifest``."""
    source = read_js("init.js")
    pos = source.find("function initButtons")
    assert pos != -1
    body = source[pos:pos + 10000]
    assert "settings-backup-export-btn" in body
    assert "exportEncryptedBackup" in body
    assert "settings-backup-manifest-btn" in body
    assert "previewEncryptedBackupManifest" in body


def test_styles_css_has_backup_scoped_classes() -> None:
    """styles.css must define the ``.settings-backup-*``
    scoped classes used by the encrypted backup export + manifest
    preview controls."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (
        ".settings-backup-row",
        ".settings-backup-label",
        ".settings-backup-input",
        ".settings-backup-actions",
        ".settings-backup-btn",
        ".settings-backup-status",
        ".settings-backup-manifest",
        ".settings-backup-manifest-filename",
        ".settings-backup-manifest-fields",
    ):
        assert cls in source, (
            "styles.css must define backup class: " + cls
        )


def test_index_html_no_forbidden_settings_buttons() -> None:
    """index.html page-settings must not include the forbidden
    write button ids (import / clear / clear-all / save / set-path).
    the ``settings-backup-export-btn`` and
    ``settings-backup-manifest-btn`` are the only allowed backup
    buttons; ``settings-export-btn`` / ``settings-manifest-btn``
    (without the ``-backup-`` segment) remain forbidden so no
    ambiguous shortcut ids are introduced."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-settings"')
    assert pos != -1
    end = source.find("</section>", pos)
    section = source[pos:end]
    for forbidden in (
        "settings-import-btn",
        "settings-clear-btn",
        "settings-clear-all-btn",
        "settings-save-btn",
        "settings-set-path-btn",
        # Ambiguous shortcuts without the -backup- segment remain
        # forbidden so the only backup entry points are the scoped ones.
        "settings-export-btn",
        "settings-manifest-btn",
    ):
        assert forbidden not in section, (
            "index.html page-settings must not contain forbidden id: "
            + forbidden
        )


def test_settings_js_backup_no_network_storage_clipboard() -> None:
    """the backup functions must not use any network, storage,
    or browser clipboard API. (Module-wide check; reaffirmed for the
    new functions.)"""
    source = read_js("settings.js")
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "navigator.clipboard",
    ):
        assert forbidden not in source, (
            "settings.js must not use: " + forbidden
        )


# --- encrypted backup import + clear-all-local-data contract ---


def test_core_js_declares_settings_import_and_clear_state() -> None:
    """core.js must declare ``settingsBackupImportInProgress``
    and ``settingsClearAllInProgress`` as separate state flags so an
    import / clear in flight never races the export / manifest / toggle
    write. These flags are distinct from the
    ``settingsWriteInProgress`` and the
    ``settingsBackupExportInProgress`` / ``settingsBackupManifestInProgress``
    flags."""
    source = read_js("core.js")
    assert "settingsBackupImportInProgress" in source, (
        "core.js must declare settingsBackupImportInProgress"
    )
    assert "settingsClearAllInProgress" in source, (
        "core.js must declare settingsClearAllInProgress"
    )


def test_settings_js_defines_import_and_clear_helpers() -> None:
    """settings.js must define and expose the import / clear
    helper functions (setSettingsImportStatus / clearSettingsImportStatus
    / setSettingsClearStatus / clearSettingsClearStatus /
    clearBackupManifestPreview / resetFrontendAfterLocalDataReplacement
    / importEncryptedBackup / clearAllLocalData / setSettingsDangerControlsDisabled)."""
    source = read_js("settings.js")
    for name in (
        "setSettingsImportStatus",
        "clearSettingsImportStatus",
        "setSettingsClearStatus",
        "clearSettingsClearStatus",
        "clearBackupManifestPreview",
        "resetFrontendAfterLocalDataReplacement",
        "importEncryptedBackup",
        "clearAllLocalData",
        "setSettingsDangerControlsDisabled",
    ):
        assert "function " + name in source, (
            "settings.js must define function: " + name
        )
        assert "App." + name in source, (
            "settings.js must expose App." + name
        )


def test_settings_js_any_settings_operation_in_progress_includes_6d_flags() -> None:
    """``anySettingsOperationInProgress`` must reference all six
    Settings operation flags (settingsLoading / settingsWriteInProgress /
    settingsBackupExportInProgress / settingsBackupManifestInProgress /
    settingsBackupImportInProgress / settingsClearAllInProgress) so any
    in-flight import / clear blocks every Settings control together with
    the read / toggle / export / manifest operations."""
    source = read_js("settings.js")
    pos = source.find("function anySettingsOperationInProgress")
    assert pos != -1
    body = source[pos:pos + 800]
    for flag in (
        "settingsLoading",
        "settingsWriteInProgress",
        "settingsBackupExportInProgress",
        "settingsBackupManifestInProgress",
        "settingsBackupImportInProgress",
        "settingsClearAllInProgress",
    ):
        assert flag in body, (
            "anySettingsOperationInProgress must reference flag: " + flag
        )


def test_settings_js_import_does_not_persist_passphrase() -> None:
    """the import passphrase must never be saved to ``App``
    global state. The import function reads the input values into local
    variables and clears the inputs after the call; it must NOT assign
    the passphrase to any ``App.`` property."""
    source = read_js("settings.js")
    pos = source.find("function importEncryptedBackup")
    assert pos != -1
    # Slice to the next top-level function so the body covers the whole
    # importEncryptedBackup implementation (the clearing code lives near
    # the end of the function, beyond a fixed 3000-char window). Use
    # ``\n    function `` to skip nested callback ``function (result)``
    # expressions inside the body.
    next_def = source.find("\n    function ", pos + 1)
    body = source[pos:next_def if next_def != -1 else pos + 6000]
    # The passphrase must be read into a local variable, not App state.
    assert "var passphrase" in body
    # The function must clear the passphrase input after the call.
    assert 'passInput.value = ""' in body
    # The function must NOT assign passphrase to any App.* property.
    assert "App.passphrase" not in body
    assert "App.importPassphrase" not in body
    assert "App.backupImportPassphrase" not in body


def test_settings_js_import_clear_catch_does_not_read_error_message() -> None:
    """the import / clear catch blocks must not read ``.message``
    on the caught error (never surface raw exception text)."""
    source = read_js("settings.js")
    # Whole-module check (extended to the new functions).
    # extends it to the new functions).
    for forbidden in ("err.message", "error.message", "e.message"):
        assert forbidden not in source, (
            "settings.js must not read .message in catch: " + forbidden
        )


def test_settings_js_import_clear_uses_text_content() -> None:
    """the import / clear status rendering must use
    ``textContent`` only; ``innerHTML`` is already forbidden module-wide."""
    source = read_js("settings.js")
    assert "innerHTML" not in source
    # The new status helpers must use textContent.
    for name in ("setSettingsImportStatus", "setSettingsClearStatus"):
        pos = source.find("function " + name)
        assert pos != -1
        body = source[pos:pos + 600]
        assert "textContent" in body


def test_settings_js_reset_frontend_after_local_data_replacement() -> None:
    """``resetFrontendAfterLocalDataReplacement`` must clear the
    Timeline / Statistics / Project Rules caches and per-session /
    per-activity selection state so stale ids cannot be operated on after
    the local DB is replaced by an import or a clear-all."""
    source = read_js("settings.js")
    pos = source.find("function resetFrontendAfterLocalDataReplacement")
    assert pos != -1
    body = source[pos:pos + 2500]
    for token in (
        "App.timelineLoaded = false",
        "App.statisticsLoaded = false",
        "App.rulesLoaded = false",
        "App.projectsCache = null",
        "App.currentSessions = []",
        "App.selectedSessionId = null",
        "App.selectedBatchActivityIds = {}",
    ):
        assert token in body, (
            "resetFrontendAfterLocalDataReplacement must clear: " + token
        )


def test_settings_js_import_clear_confirm_literals_present() -> None:
    """the import / clear paths must use the explicit Chinese
    confirmation literals ``导入并替换`` (import) and ``清空本地数据``
    (clear) so the user must type the exact phrase to trigger the
    destructive operation."""
    source = read_js("settings.js")
    assert "导入并替换" in source
    assert "清空本地数据" in source


def test_settings_js_import_clear_refresh_status_and_overview() -> None:
    """the import / clear success path must trigger a Settings
    status refresh (``App.loadSettingsPrivacyStatus``) and refresh the
    global overview / recent / status (``App.refreshAll``) so the main UI
    does not keep showing pre-import / pre-clear data."""
    source = read_js("settings.js")
    for name in ("importEncryptedBackup", "clearAllLocalData"):
        pos = source.find("function " + name)
        assert pos != -1
        body = source[pos:pos + 3500]
        assert "App.loadSettingsPrivacyStatus()" in body, (
            name + " success path must call App.loadSettingsPrivacyStatus()"
        )
        assert "App.refreshAll" in body, (
            name + " success path must call App.refreshAll"
        )


def test_init_js_binds_import_and_clear_buttons() -> None:
    """initButtons must bind the ``settings-backup-import-btn``
    click event to ``App.importEncryptedBackup`` and the
    ``settings-clear-local-data-btn`` click event to
    ``App.clearAllLocalData``."""
    source = read_js("init.js")
    pos = source.find("function initButtons")
    assert pos != -1
    body = source[pos:pos + 12000]
    assert "settings-backup-import-btn" in body
    assert "importEncryptedBackup" in body
    assert "settings-clear-local-data-btn" in body
    assert "clearAllLocalData" in body


def test_styles_css_has_import_and_clear_scoped_classes() -> None:
    """styles.css must define the ``.settings-backup-import-*``
    and ``.settings-danger-*`` / ``.settings-clear-*`` scoped classes
    used by the encrypted backup import and clear-all-local-data
    controls."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (
        ".settings-backup-import-section",
        ".settings-backup-import-title",
        ".settings-backup-import-hint",
        ".settings-backup-import-btn",
        ".settings-danger-clear-section",
        ".settings-danger-clear-title",
        ".settings-danger-clear-hint",
        ".settings-clear-local-data-btn",
    ):
        assert cls in source, (
            "styles.css must define class: " + cls
        )


# --- First-run privacy notice contract -----------------------


def test_index_html_defines_first_run_notice_overlay_dom_ids() -> None:
    """index.html must define the first-run notice overlay DOM
    ids. The overlay must be hidden by default (``hidden`` attribute) so
    it does not flash on already-accepted installs."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for dom_id in (
        "first-run-notice-overlay",
        "first-run-notice-dialog",
        "first-run-notice-title",
        "first-run-notice-highlights",
        "first-run-notice-text",
        "first-run-notice-accept-btn",
        "first-run-notice-close-btn",
        "first-run-notice-error",
    ):
        assert 'id="' + dom_id + '"' in source, (
            "index.html must define first-run notice DOM id: " + dom_id
        )
    # The overlay must be hidden by default.
    overlay_pos = source.find('id="first-run-notice-overlay"')
    assert overlay_pos != -1
    overlay_tag = source[overlay_pos - 200:overlay_pos + 200]
    assert "hidden" in overlay_tag, (
        "first-run-notice-overlay must be hidden by default"
    )


def test_index_html_settings_page_has_read_only_view_notice_button() -> None:
    """the Settings / Privacy page must include a read-only
    "查看隐私说明" button + status span so the user can re-open the notice
    without writing any setting or re-accepting. The button must NOT
    be a save / set-path / file-dialog write button."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-settings"')
    assert pos != -1
    end = source.find("</section>", pos)
    section = source[pos:end]
    assert 'id="settings-privacy-notice-btn"' in section, (
        "page-settings must include settings-privacy-notice-btn"
    )
    assert 'id="settings-privacy-notice-status"' in section, (
        "page-settings must include settings-privacy-notice-status"
    )
    # The button label should mention "查看隐私说明" so the user knows
    # it opens a read-only view.
    btn_pos = section.find('id="settings-privacy-notice-btn"')
    assert btn_pos != -1
    btn_tag = section[btn_pos:btn_pos + 300]
    assert "查看隐私说明" in btn_tag, (
        "settings-privacy-notice-btn must be labeled 查看隐私说明"
    )


def test_index_html_first_run_gate_has_no_skip_or_later_or_cancel() -> None:
    """the first-run notice overlay (gate mode) must NOT
    include any skip / later / cancel button id that would allow the
    user to bypass the notice without accepting. Only the accept button
    is allowed; the close button is allowed only for the read-only view
    mode (it is hidden in gate mode by ``renderFirstRunNotice``)."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    overlay_pos = source.find('id="first-run-notice-overlay"')
    assert overlay_pos != -1
    # The overlay ends at the matching </div> for the overlay container;
    # slice a generous window that covers the entire dialog markup.
    overlay_end = source.find("</div>", source.find(
        "</div>", source.find('id="first-run-notice-close-btn"')
    ) + 1)
    overlay = source[overlay_pos:overlay_end + 1]
    for forbidden in (
        "first-run-notice-skip-btn",
        "first-run-notice-later-btn",
        "first-run-notice-cancel-btn",
        "first-run-notice-dismiss-btn",
    ):
        assert forbidden not in overlay, (
            "first-run notice overlay must not contain bypass button: "
            + forbidden
        )


def test_index_html_first_run_close_button_is_hidden_by_default() -> None:
    """the close button inside the first-run notice overlay
    must be hidden by default. It is only shown in read-only view mode
    (opened from Settings) by ``renderFirstRunNotice`` flipping the
    ``hidden`` attribute. This ensures the gate mode never offers a
    close affordance even before JS runs."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    close_pos = source.find('id="first-run-notice-close-btn"')
    assert close_pos != -1
    close_tag = source[close_pos - 100:close_pos + 200]
    assert "hidden" in close_tag, (
        "first-run-notice-close-btn must be hidden by default; it is "
        "only revealed in read-only view mode by renderFirstRunNotice"
    )


def test_core_js_declares_first_run_notice_state_variables() -> None:
    """core.js must declare the five first-run notice state
    variables so the gate / accept / view-mode guards have a single
    in-memory source of truth. None of these may be persisted to
    browser storage."""
    source = read_js("core.js")
    for token in (
        "App.firstRunNoticeLoaded",
        "App.firstRunNoticeLoading",
        "App.firstRunNoticeRequired",
        "App.firstRunNoticeAcceptInProgress",
        "App.firstRunNoticeViewingFromSettings",
    ):
        assert token in source, (
            "core.js must declare first-run notice state variable: " + token
        )


def test_settings_js_defines_first_run_notice_helpers() -> None:
    """settings.js must define and expose the first-run notice
    helper functions (loadFirstRunNotice / showFirstRunNotice /
    hideFirstRunNotice / acceptFirstRunNotice /
    openPrivacyNoticeFromSettings / renderFirstRunNotice)."""
    source = read_js("settings.js")
    for name in (
        "loadFirstRunNotice",
        "showFirstRunNotice",
        "hideFirstRunNotice",
        "acceptFirstRunNotice",
        "openPrivacyNoticeFromSettings",
        "renderFirstRunNotice",
    ):
        assert "function " + name in source, (
            "settings.js must define function: " + name
        )
        assert "App." + name in source, (
            "settings.js must expose App." + name
        )


def test_settings_js_first_run_notice_uses_text_content_not_inner_html() -> None:
    """renderFirstRunNotice must render title / highlights /
    notice text via ``textContent`` and ``createElement`` only.
    ``innerHTML`` is already forbidden module-wide; this test focuses on the render function."""
    source = read_js("settings.js")
    pos = source.find("function renderFirstRunNotice")
    assert pos != -1
    body = source[pos:pos + 2000]
    assert "textContent" in body
    assert "createElement" in body
    assert "innerHTML" not in body
    # The whole module still forbids innerHTML (reaffirmed).
    assert "innerHTML" not in source


def test_settings_js_first_run_notice_catch_does_not_read_error_message() -> None:
    """the first-run notice catch blocks must not read
    ``.message`` on the caught error (never surface raw exception text)."""
    source = read_js("settings.js")
    # Whole-module check (extended to the new functions).
    # extends it to the new functions).
    for forbidden in ("err.message", "error.message", "e.message"):
        assert forbidden not in source, (
            "settings.js must not read .message in catch: " + forbidden
        )


def test_settings_js_first_run_notice_no_network_storage_clipboard() -> None:
    """the first-run notice functions must not use any network,
    storage, or browser clipboard API. (Module-wide check; reaffirmed
    for the new functions.)"""
    source = read_js("settings.js")
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "navigator.clipboard",
    ):
        assert forbidden not in source, (
            "settings.js must not use: " + forbidden
        )


def test_settings_js_first_run_notice_does_not_persist_notice_payload() -> None:
    """the notice payload (title / highlights / notice_text)
    must never be saved to ``App`` global state as a long-lived
    property. The render function reads from the local ``data``
    argument only; the load / accept / view functions do not assign
    the payload to ``App.*`` properties. (State variables like
    ``App.firstRunNoticeLoaded`` are status flags, not payload
    persistence.)"""
    source = read_js("settings.js")
    for forbidden_prop in (
        "App.firstRunNoticePayload",
        "App.firstRunNoticeData",
        "App.firstRunNoticeText",
        "App.firstRunNoticeTitle",
        "App.firstRunNoticeHighlights",
        "App.privacyNoticeText",
    ):
        assert forbidden_prop not in source, (
            "settings.js must not persist notice payload to App state: "
            + forbidden_prop
        )


def test_settings_js_load_first_run_notice_shows_gate_when_unaccepted() -> None:
    """``loadFirstRunNotice`` must set
    ``App.firstRunNoticeRequired = true`` and call ``showFirstRunNotice``
    with mode ``"gate"`` when the backend reports
    ``result.accepted === false``. This locks the blocking-gate behavior
    in source so the user cannot be silently bypassed."""
    source = read_js("settings.js")
    pos = source.find("function loadFirstRunNotice")
    assert pos != -1
    body = source[pos:pos + 2500]
    assert "result.accepted === false" in body
    assert 'App.firstRunNoticeRequired = true' in body
    assert 'showFirstRunNotice' in body
    assert '"gate"' in body or "'gate'" in body


def test_settings_js_accept_first_run_notice_clears_required_and_hides_gate() -> None:
    """``acceptFirstRunNotice`` must clear
    ``App.firstRunNoticeRequired`` and call ``hideFirstRunNotice`` on
    success. It must also call ``App.refreshAll`` so the sidebar
    reflects the now-running collector."""
    source = read_js("settings.js")
    pos = source.find("function acceptFirstRunNotice")
    assert pos != -1
    body = source[pos:pos + 2500]
    assert "App.firstRunNoticeRequired = false" in body
    assert "hideFirstRunNotice" in body
    assert "App.refreshAll" in body


def test_settings_js_open_privacy_notice_uses_view_mode_only() -> None:
    """``openPrivacyNoticeFromSettings`` must call
    ``showFirstRunNotice`` with mode ``"view"`` (read-only). It must
    never call ``acceptFirstRunNotice`` or write any setting."""
    source = read_js("settings.js")
    pos = source.find("function openPrivacyNoticeFromSettings")
    assert pos != -1
    # Slice to the next sibling function so the body covers the whole
    # openPrivacyNoticeFromSettings implementation, including the strict
    # fail-closed error branch which precedes the showFirstRunNotice call.
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 3000]
    assert "showFirstRunNotice" in body
    assert '"view"' in body or "'view'" in body
    # The view-mode function must not call accept or any write bridge.
    assert "acceptFirstRunNotice" not in body
    assert 'App.callBridge("accept_first_run_notice")' not in body
    assert 'App.callBridge("set_setting_value")' not in body
    assert 'App.callBridge("set_clipboard_capture_enabled")' not in body


def test_settings_js_hide_first_run_notice_does_not_write_setting_or_start_collector() -> None:
    """``hideFirstRunNotice`` must only hide the overlay and
    clear the viewing flag. It must NOT call any bridge method, must
    NOT call ``set_setting_value``, must NOT call
    ``accept_first_run_notice``, and must NOT start the collector."""
    source = read_js("settings.js")
    pos = source.find("function hideFirstRunNotice")
    assert pos != -1
    body = source[pos:pos + 800]
    # The only operations allowed in hideFirstRunNotice are setting
    # ``overlay.hidden`` and ``App.firstRunNoticeViewingFromSettings``.
    # No bridge calls of any kind.
    assert "App.callBridge" not in body
    assert "acceptFirstRunNotice" not in body
    assert "App.firstRunNoticeViewingFromSettings = false" in body


def test_settings_js_render_first_run_notice_hides_close_in_gate_mode() -> None:
    """``renderFirstRunNotice`` must hide the close button in
    gate mode (``mode !== "view"``) so the only way to dismiss the gate
    is to accept. The accept button is shown in gate mode and hidden in
    view mode."""
    source = read_js("settings.js")
    pos = source.find("function renderFirstRunNotice")
    assert pos != -1
    body = source[pos:pos + 2500]
    # In "view" mode: accept hidden, close shown.
    assert 'acceptBtn' in body and 'closeBtn' in body
    assert '"view"' in body or "'view'" in body
    # The else branch (gate mode): accept shown, close hidden.
    assert 'acceptBtn.hidden = false' in body or 'acceptBtn.hidden = false;' in body
    assert 'closeBtn.hidden = true' in body or 'closeBtn.hidden = true;' in body
    # The view branch: accept hidden, close shown.
    assert 'acceptBtn.hidden = true' in body or 'acceptBtn.hidden = true;' in body
    assert 'closeBtn.hidden = false' in body or 'closeBtn.hidden = false;' in body


def test_settings_js_close_button_handler_guards_on_viewing_from_settings() -> None:
    """the close-button click handler (bound in init.js) must
    check ``App.firstRunNoticeViewingFromSettings`` before calling
    ``hideFirstRunNotice``. This is the JS mode guard that prevents the
    close button from ever dismissing the gate even if a future code
    path re-enables it."""
    source = read_js("init.js")
    pos = source.find("first-run-notice-close-btn")
    assert pos != -1
    body = source[pos:pos + 1000]
    assert "firstRunNoticeViewingFromSettings" in body
    assert "hideFirstRunNotice" in body


def test_init_js_binds_first_run_notice_buttons() -> None:
    """initButtons must bind the ``first-run-notice-accept-btn``
    click event to ``App.acceptFirstRunNotice``, the
    ``first-run-notice-close-btn`` click event to a guarded
    ``App.hideFirstRunNotice`` wrapper, and the
    ``settings-privacy-notice-btn`` click event to
    ``App.openPrivacyNoticeFromSettings``."""
    source = read_js("init.js")
    pos = source.find("function initButtons")
    assert pos != -1
    body = source[pos:pos + 14000]
    assert "first-run-notice-accept-btn" in body
    assert "acceptFirstRunNotice" in body
    assert "first-run-notice-close-btn" in body
    assert "hideFirstRunNotice" in body
    assert "settings-privacy-notice-btn" in body
    assert "openPrivacyNoticeFromSettings" in body


def test_init_js_calls_load_first_run_notice_in_init() -> None:
    """``init()`` must call ``App.loadFirstRunNotice()`` so the
    gate is shown on startup when the user has not yet accepted. The
    load must happen before the main UI refresh call so the gate is
    visible before any backend status refresh completes.

    The ``refreshAll()`` /
    ``startAutoRefresh()`` / ``startLocalTicker()`` were replaced by ``refreshCurrentPageData()`` + ``startHeartbeat()``. This test verifies the contract: loadFirstRunNotice must be called, and
    by ``refreshCurrentPageData()`` + ``startHeartbeat()``. This test now
    verifies the new contract: loadFirstRunNotice must be called, and
    ``refreshCurrentPageData()`` + ``startHeartbeat()`` must both be
    invoked after the notice is confirmed."""
    source = read_js("init.js")
    # Match ``function init()`` exactly so we do not collide with
    # ``function initNav`` or ``function initButtons``.
    pos = source.find("function init()")
    assert pos != -1, "init.js must define function init()"
    # Slice to the next sibling function so we capture the whole init()
    # body.
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 2500]
    assert "App.loadFirstRunNotice()" in body
    load_pos = body.find("App.loadFirstRunNotice()")
    # ``refreshCurrentPageData()`` and
    # ``startHeartbeat()`` must both be called inside the .then()
    # callback after loadFirstRunNotice resolves.
    refresh_pos = body.find("refreshCurrentPageData()")
    heartbeat_pos = body.find("startHeartbeat()")
    assert refresh_pos != -1, (
        "init() must call refreshCurrentPageData() after notice confirmation"
    )
    assert heartbeat_pos != -1, (
        "init() must call startHeartbeat() after notice confirmation"
    )
    assert load_pos < refresh_pos, (
        "init() must call loadFirstRunNotice before refreshCurrentPageData"
    )
    assert load_pos < heartbeat_pos, (
        "init() must call loadFirstRunNotice before startHeartbeat"
    )


def test_styles_css_has_first_run_notice_scoped_classes() -> None:
    """styles.css must define the ``.first-run-notice-*`` and
    ``.settings-privacy-notice-*`` scoped classes used by the first-run
    notice overlay and the Settings read-only view entry."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (
        ".first-run-notice-overlay",
        ".first-run-notice-dialog",
        ".first-run-notice-title",
        ".first-run-notice-highlights",
        ".first-run-notice-text",
        ".first-run-notice-error",
        ".first-run-notice-actions",
        ".first-run-notice-accept-btn",
        ".first-run-notice-close-btn",
        ".settings-privacy-notice-row",
        ".settings-privacy-notice-status",
        ".settings-privacy-notice-btn",
    ):
        assert cls in source, (
            "styles.css must define class: " + cls
        )


def test_first_run_notice_resources_no_external_fonts_or_cdn() -> None:
    """the first-run notice resources must not introduce any
    external font, CDN link, or network resource. The existing
    parametrized global-boundary tests already cover this for every
    frontend file; this test reaffirms the invariant for the new
    first-run notice markup / styles specifically."""
    for filename in ("index.html", "styles.css", "js/settings.js", "js/core.js", "js/init.js"):
        source = (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")
        lowered = source.lower()
        for forbidden in (
            "https://",
            "http://",
            "cdn.jsdelivr",
            "fonts.googleapis",
            "unpkg.com",
            "@import",
        ):
            assert forbidden not in lowered, (
                filename + " must not reference external resource: " + forbidden
            )


# --- Settings controls not dependent on settingsLoaded --------


def test_settings_js_backup_controls_not_dependent_on_settingsLoaded() -> None:
    """``setSettingsBackupControlsDisabled`` must compute the
    disabled state based ONLY on the ``disabled`` parameter, NOT on
    ``App.settingsLoaded``. This ensures a failed first status load does
    not permanently lock the user out of backup / import / clear controls.
    The backup passphrase / export / manifest / import inputs must remain
    editable even when the first ``get_settings_privacy_status`` read
    failed so the user can still perform backup operations."""
    source = read_js("settings.js")
    pos = source.find("function setSettingsBackupControlsDisabled")
    assert pos != -1
    # Slice to the next sibling function so the body covers the whole
    # function implementation.
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 1500]
    # Strip // line comments to avoid false positives from comments that
    # explain WHY settingsLoaded is not used.
    cleaned_lines = []
    for line in body.split("\n"):
        idx = line.find("//")
        if idx != -1:
            line = line[:idx]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    # The backup-disabled computation must NOT reference settingsLoaded.
    assert "settingsLoaded" not in cleaned, (
        "setSettingsBackupControlsDisabled must not reference "
        "App.settingsLoaded; backup controls depend only on the disabled "
        "parameter (operation in progress)"
    )
    # The function should compute backupDisabled from the disabled param.
    assert "var backupDisabled = !!disabled;" in body


def test_settings_js_danger_controls_not_dependent_on_settingsLoaded() -> None:
    """``setSettingsDangerControlsDisabled`` must compute the
    disabled state based ONLY on the ``disabled`` parameter, NOT on
    ``App.settingsLoaded``. The clear-confirm input must remain editable
    even when the first status read failed; the backend re-validates the
    confirmation literal, so allowing input before status loads is safe."""
    source = read_js("settings.js")
    pos = source.find("function setSettingsDangerControlsDisabled")
    assert pos != -1
    # Slice to the next sibling function.
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 1200]
    # Strip // line comments to avoid false positives from comments that
    # explain WHY settingsLoaded is not used.
    cleaned_lines = []
    for line in body.split("\n"):
        idx = line.find("//")
        if idx != -1:
            line = line[:idx]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    # The danger-disabled computation must NOT reference settingsLoaded.
    assert "settingsLoaded" not in cleaned, (
        "setSettingsDangerControlsDisabled must not reference "
        "App.settingsLoaded; danger controls depend only on the disabled "
        "parameter (operation in progress)"
    )
    # The function should compute dangerDisabled from the disabled param.
    assert "var dangerDisabled = !!disabled;" in body


def test_settings_js_clipboard_toggle_still_uses_settingsLoaded() -> None:
    """the clipboard toggle control logic must STILL reference
    ``settingsLoaded`` (this was intentionally kept). The clipboard toggle
    needs the current state to render, so it stays disabled until the
    first successful status load. This is the ONLY Settings control that
    still depends on settingsLoaded after the fix."""
    source = read_js("settings.js")
    pos = source.find("function setSettingsControlsDisabled")
    assert pos != -1
    # Slice to the next sibling function.
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 1000]
    # The clipboard toggle line must reference settingsLoaded.
    assert "!App.settingsLoaded" in body, (
        "setSettingsControlsDisabled must reference App.settingsLoaded "
        "for the clipboard toggle"
    )


# --- First-run notice JS fallback ----------------------------


def test_settings_js_has_no_first_run_notice_fallback_text() -> None:
    """The frontend must NOT maintain a JS-side privacy notice fallback
    body. The privacy notice text is the sole responsibility of the
    backend (``PRIVACY_NOTICE_TEXT`` in ``constants.py``). On bridge
    failure the frontend must show a blocking error overlay with NO
    notice body, NO highlights, NO title, and a disabled/hidden accept
    button (strict fail-closed)."""
    source = read_js("settings.js")
    assert "FIRST_RUN_NOTICE_FALLBACK_TEXT" not in source, (
        "settings.js must NOT define FIRST_RUN_NOTICE_FALLBACK_TEXT; "
        "the privacy notice body must come from the backend only"
    )
    assert "buildFirstRunNoticeFallback" not in source, (
        "settings.js must NOT define buildFirstRunNoticeFallback; "
        "no JS-side fallback notice body is allowed"
    )


# --- init.js awaits loadFirstRunNotice before refresh ---------


def test_init_js_awaits_load_first_run_notice_before_refresh() -> None:
    """``init()`` must await ``App.loadFirstRunNotice()`` before
    starting any main UI refresh. The refresh calls must be inside a
    ``.then(...)`` callback (or after an ``await``) on the
    loadFirstRunNotice promise, NOT called synchronously before it. This
    eliminates the frontend race where refresh could fire before the
    gate overlay was up.

    The ``refreshAll()`` /
    ``startAutoRefresh()`` / ``startLocalTicker()`` calls were replaced
    by ``refreshCurrentPageData()`` + ``startHeartbeat()``. This test
    verifies the new contract: both calls must appear after
    loadFirstRunNotice in source order, inside a ``.then(...)``
    callback on the loadFirstRunNotice promise."""
    source = read_js("init.js")
    # Match ``function init()`` exactly so we do not collide with
    # ``function initNav`` or ``function initButtons``.
    pos = source.find("function init()")
    assert pos != -1, "init.js must define function init()"
    # Slice to the next sibling function so we capture the whole init()
    # body.
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 2500]
    # loadFirstRunNotice must be called.
    assert "App.loadFirstRunNotice()" in body, (
        "init() must call App.loadFirstRunNotice()"
    )
    load_pos = body.find("App.loadFirstRunNotice()")
    # the two heartbeat-starting calls must appear
    # after loadFirstRunNotice in source order.
    for call in ("refreshCurrentPageData()", "startHeartbeat()"):
        call_pos = body.find(call)
        assert call_pos != -1, "init() must call " + call
        assert load_pos < call_pos, (
            "init() must call loadFirstRunNotice before " + call
        )
    # The refresh calls must be inside a .then(...) callback on the
    # loadFirstRunNotice promise, not at the top level of init. Verify
    # the .then( appears between loadFirstRunNotice and the first
    # refreshCurrentPageData() call.
    refresh_pos = body.find("refreshCurrentPageData()")
    between = body[load_pos:refresh_pos]
    assert ".then(function" in between, (
        "init() must call refreshCurrentPageData/startHeartbeat "
        "inside a .then(...) callback on the loadFirstRunNotice promise, "
        "not at the top level of init"
    )


# --- init.js gates init() on pywebview bridge ready ----------
#
# On cold start, pywebview injects ``window.pywebview.api`` AFTER the
# frontend scripts load. The old wiring called ``init()`` directly on
# DOMContentLoaded, so ``App.loadFirstRunNotice()`` -> ``App.callBridge()``
# ran before the bridge existed, ``callBridge`` rejected with
# "bridge unavailable", and ``loadFirstRunNotice``'s catch branch rendered
# a false "隐私说明加载失败" blocking overlay. The bootstrap must now wait
# for the ``pywebviewready`` event (or detect the bridge already injected)
# before calling ``init()``.


def test_init_js_gates_bootstrap_on_pywebviewready_event() -> None:
    """init.js must wait for the pywebview bridge to be ready
    before calling ``init()``. The bootstrap wiring must reference the
    ``pywebviewready`` event so that ``App.loadFirstRunNotice()`` is not
    called while ``window.pywebview.api`` is still undefined. Without this
    gate, ``App.callBridge`` rejects with "bridge unavailable" on cold
    start and ``loadFirstRunNotice``'s catch branch renders a false
    "隐私说明加载失败" blocking overlay even though the backend notice
    is fine."""
    source = read_js("init.js")
    assert "pywebviewready" in source, (
        "init.js must reference the pywebviewready event (or equivalent "
        "bridge-ready gate) before calling init()"
    )
    # The event listener must be attached on window so the bridge-ready
    # callback actually fires.
    assert 'addEventListener("pywebviewready"' in source or \
           "addEventListener('pywebviewready'" in source, (
        "init.js must attach a pywebviewready listener on window"
    )


def test_init_js_does_not_call_init_directly_on_domcontentloaded() -> None:
    """the DOMContentLoaded wiring must NOT pass ``init``
    directly as the listener. It must route through a bridge-ready gate
    (``onDomReady`` / ``bootstrap``) so ``init()`` only runs after
    ``window.pywebview.api`` is available. The direct
    ``addEventListener("DOMContentLoaded", init)`` pattern is forbidden
    because it would call ``App.loadFirstRunNotice()`` before the bridge
    is injected, producing a false "隐私说明加载失败" overlay."""
    source = read_js("init.js")
    # The forbidden pattern: passing ``init`` directly as the
    # DOMContentLoaded listener.
    assert 'addEventListener("DOMContentLoaded", init)' not in source, (
        "init.js must not pass init directly to DOMContentLoaded; it must "
        "go through a bridge-ready gate (onDomReady / bootstrap)"
    )
    assert "addEventListener('DOMContentLoaded', init)" not in source
    # The bootstrap must check window.pywebview.api before calling init.
    assert "pywebview.api" in source, (
        "init.js must check window.pywebview.api before calling init()"
    )


def test_init_js_bootstrap_runs_init_only_once() -> None:
    """the bootstrap wiring must guarantee ``init()`` runs only
    once regardless of whether DOMContentLoaded / pywebviewready fire
    before or after each other (or are already satisfied at script load).
    A re-entrant guard flag (e.g. ``initStarted``) must prevent double
    initialization."""
    source = read_js("init.js")
    # A guard flag must be declared.
    assert re.search(
        r"var\s+init(?:Started|Done|Invoked|Initialized|Ran)\s*=", source
    ), (
        "init.js must declare a re-entrant guard flag (e.g. initStarted) "
        "so init() only runs once"
    )
    # The guard must be checked before calling init(). Accept either the
    # early-return form (``if (initStarted) return;``) or the negated
    # guarded-call form (``if (!initStarted) { ... init(); }``).
    assert re.search(
        r"if\s*\(\s*!?\s*init(?:Started|Done|Invoked|Initialized|Ran)\s*\)",
        source,
    ), (
        "init.js bootstrap must check the guard flag before calling init() "
        "so init() never runs twice"
    )


def test_init_js_bootstrap_handles_bridge_already_ready() -> None:
    """when the bridge is already injected at bootstrap time
    (``window.pywebview && window.pywebview.api`` exists), the bootstrap
    must call ``init()`` immediately without waiting for the
    ``pywebviewready`` event (which will never fire again). This covers
    the case where pywebview finished injecting before the frontend
    script ran."""
    source = read_js("init.js")
    # A bridge-ready helper must exist and check both window.pywebview
    # and window.pywebview.api.
    assert re.search(r"function\s+isBridgeReady\s*\(", source), (
        "init.js must define an isBridgeReady() helper that checks "
        "window.pywebview && window.pywebview.api"
    )
    # The onDomReady handler must branch on isBridgeReady(): call
    # bootstrap() directly when ready, otherwise attach the
    # pywebviewready listener.
    pos = source.find("function onDomReady")
    assert pos != -1, "init.js must define function onDomReady"
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 800]
    assert "isBridgeReady()" in body, (
        "onDomReady must call isBridgeReady() to detect an already-injected "
        "bridge"
    )
    assert "bootstrap()" in body, (
        "onDomReady must call bootstrap() when the bridge is already ready"
    )
    assert "pywebviewready" in body, (
        "onDomReady must attach the pywebviewready listener when the bridge "
        "is not yet ready"
    )


def test_init_js_does_not_use_storage_or_network_apis() -> None:
    """the init.js bootstrap wiring must not introduce any
    browser storage (localStorage / sessionStorage / cookie) or network
    (fetch / XMLHttpRequest / WebSocket / EventSource / navigator.clipboard)
    API. The pywebview bridge is the only communication channel."""
    source = read_js("init.js")
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "navigator.clipboard",
    ):
        assert forbidden not in source, (
            "init.js must not use: " + forbidden
        )


# --- notice load failure does not start main UI refresh --------
#
# loadFirstRunNotice() now resolves to a boolean: ``true`` when the notice
# state was successfully confirmed, ``false`` on backend ``ok:false`` or
# bridge rejection. init() must only start refreshAll / startAutoRefresh /
# startLocalTicker when the boolean is true. On failure the blocking error
# overlay is already shown by loadFirstRunNotice; the collector and main UI
# auto-refresh must NOT start (fail-closed). Additionally, the catch branch
# of loadFirstRunNotice must NOT set ``firstRunNoticeLoaded = true`` so a
# transient bridge rejection does not permanently lock the frontend state.


def test_init_js_does_not_start_refresh_on_notice_load_failure() -> None:
    """init() must not call ``refreshCurrentPageData`` /
    ``startHeartbeat`` when loadFirstRunNotice resolves false (notice load
    failed). The refresh calls must be guarded by a notice-confirmed check
    so a failed notice load leaves the main UI auto-refresh off
    (fail-closed). The refresh contract is ``refreshCurrentPageData()`` plus
    ``startHeartbeat()``, guarded by the notice state."""
    source = read_js("init.js")
    pos = source.find("function init()")
    assert pos != -1, "init.js must define function init()"
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 2500]
    # The .then callback must receive a notice-confirmed boolean and guard
    # the refresh calls on it so a failed notice load does not start refresh.
    assert "noticeConfirmed" in body, (
        "init() .then callback must receive a noticeConfirmed boolean "
        "from loadFirstRunNotice"
    )
    assert "if (!noticeConfirmed) return;" in body or \
           "if (!noticeConfirmed) return" in body, (
        "init() must guard refresh calls on noticeConfirmed"
    )
    # The old catch branch that unconditionally started refresh must not
    # exist. A .catch on the loadFirstRunNotice chain that contains
    # refreshCurrentPageData / startHeartbeat is forbidden.
    catch_pos = body.find(".catch(function")
    if catch_pos != -1:
        catch_body = body[catch_pos:catch_pos + 600]
        for call in ("refreshCurrentPageData()", "startHeartbeat()"):
            assert call not in catch_body, (
                "init() catch branch must not call " + call + " on notice "
                "load failure (fail-closed)"
            )


def test_settings_js_load_first_run_notice_catch_does_not_lock_state() -> None:
    """the catch branch of loadFirstRunNotice must NOT set
    ``App.firstRunNoticeLoaded = true``. A bridge rejection may be
    transient (bridge not yet injected, temporary unavailability), so
    permanently marking the notice as loaded would prevent any retry and
    lock the user out. The catch must still show the blocking error
    overlay (fail-closed UI) but leave the loaded flag false so a retry
    or app restart can re-attempt the load. The backend ``ok:false``
    path (real backend failure) still sets ``firstRunNoticeLoaded = true``
    for strict fail-closed since the backend is broken and retrying will
    not help."""
    source = read_js("settings.js")
    pos = source.find("function loadFirstRunNotice")
    assert pos != -1
    # Slice to the next sibling function so we cover the whole
    # loadFirstRunNotice implementation including the catch block.
    end = source.find("\n    function ", pos + 1)
    body = source[pos:end if end != -1 else pos + 3000]
    # Locate the catch block within loadFirstRunNotice.
    catch_pos = body.find(".catch(function")
    assert catch_pos != -1, "loadFirstRunNotice must have a catch block"
    # Slice the catch block body (generous window).
    catch_body = body[catch_pos:catch_pos + 800]
    assert "firstRunNoticeLoaded = true" not in catch_body, (
        "loadFirstRunNotice catch must not set firstRunNoticeLoaded = true; "
        "bridge rejection may be transient and must allow retry"
    )
    # The catch must still show the blocking error (fail-closed UI).
    assert "showFirstRunNoticeBlockingError" in catch_body, (
        "loadFirstRunNotice catch must still show the blocking error overlay"
    )
