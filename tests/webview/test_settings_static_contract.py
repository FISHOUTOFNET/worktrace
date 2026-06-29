"""Phase 6A — Settings / Privacy WebView static-contract tests.

These tests read the bundled frontend resources (``index.html`` /
``js/*.js`` / ``styles.css`` / ``WorkTrace.spec``) directly without starting
the GUI. They lock the Settings / Privacy page contracts for Phase 6A
(read-only status foundation): the page must be migrated (no placeholder),
the required DOM ids must exist, ``settings.js`` must be loaded in the
correct order, and the JS must only call the read-only bridge method
``get_settings_privacy_status`` (no save / export / import / clear-all /
clipboard-toggle write paths).
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


def test_index_html_settings_nav_entry_6a() -> None:
    """Phase 6A: the sidebar nav must still contain the 设置与隐私 entry."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    assert 'data-page="settings"' in source
    assert "设置与隐私" in source


def test_index_html_settings_page_section_is_migrated_6a() -> None:
    """Phase 6A: the page-settings section must not contain the old
    migration placeholder copy."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    pos = source.find('id="page-settings"')
    assert pos != -1, "page-settings section must exist"
    section = source[pos:pos + 1200]
    assert "WebView 迁移中" not in section
    # The migrated page must announce its read-only nature so the user
    # understands no write action is offered here yet.
    assert "设置与隐私" in section
    assert "只读" in section or "暂不开放" in section


def test_index_html_settings_required_dom_ids_6a() -> None:
    """Phase 6A: the page-settings section must define the required DOM ids."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    for dom_id in (
        "settings-refresh-btn",
        "settings-error",
        "settings-loading",
        "settings-status",
        "settings-storage-card",
        "settings-privacy-card",
        "settings-backup-card",
        "settings-danger-card",
    ):
        assert 'id="' + dom_id + '"' in source, (
            "index.html must define DOM id: " + dom_id
        )


# --- JS load order + packaging ------------------------------------------


def test_index_html_loads_settings_js_6a() -> None:
    """Phase 6A: index.html must load ``js/settings.js`` exactly once and
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


def test_all_js_files_includes_settings_js_6a() -> None:
    """Phase 6A: ``ALL_JS_FILES`` must include ``settings.js`` between
    ``statistics.js`` and ``rules.js``."""
    assert "settings.js" in ALL_JS_FILES
    stats_idx = ALL_JS_FILES.index("statistics.js")
    settings_idx = ALL_JS_FILES.index("settings.js")
    rules_idx = ALL_JS_FILES.index("rules.js")
    assert stats_idx < settings_idx < rules_idx, (
        "settings.js must load after statistics.js and before rules.js"
    )


def test_worktrace_spec_bundles_settings_js_6a() -> None:
    """Phase 6A: ``WorkTrace.spec`` must bundle ``settings.js`` so the
    PyInstaller build ships the new module."""
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "settings.js" in spec, (
        "WorkTrace.spec must include settings.js in datas"
    )


def test_settings_js_exists_on_disk_6a() -> None:
    """Phase 6A: the ``settings.js`` module file must exist on disk."""
    assert (JS_DIR / "settings.js").is_file(), (
        "worktrace/webview_ui/js/settings.js must exist"
    )


# --- JS contract: read-only status load ----------------------------------


def test_settings_js_defines_load_settings_privacy_status_6a() -> None:
    """Phase 6A: settings.js must define ``App.loadSettingsPrivacyStatus``
    and call ``App.callBridge("get_settings_privacy_status")``."""
    source = read_js("settings.js")
    assert "App.loadSettingsPrivacyStatus" in source
    assert 'App.callBridge("get_settings_privacy_status")' in source


def test_settings_js_only_calls_allowed_bridge_method_6a() -> None:
    """Phase 6A: settings.js must not call any write-side bridge method
    (export_encrypted_backup / import_encrypted_backup /
    parse_encrypted_backup_manifest / clear_all_local_data /
    set_setting_value / set_clipboard_capture_enabled)."""
    source = read_js("settings.js")
    for forbidden in (
        "export_encrypted_backup",
        "import_encrypted_backup",
        "parse_encrypted_backup_manifest",
        "clear_all_local_data",
        "set_setting_value",
        "set_clipboard_capture_enabled",
    ):
        assert forbidden not in source, (
            "settings.js must not call bridge method: " + forbidden
        )


def test_settings_js_does_not_use_network_or_storage_apis_6a() -> None:
    """Phase 6A: settings.js must not use any network or storage API."""
    source = read_js("settings.js")
    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "localStorage",
        "sessionStorage",
        "document.cookie",
    ):
        assert forbidden not in source, (
            "settings.js must not use: " + forbidden
        )


def test_settings_js_catch_does_not_read_error_message_6a() -> None:
    """Phase 6A: settings.js catch blocks must not read ``.message`` on
    the caught error (never surface raw exception text)."""
    source = read_js("settings.js")
    # ``.message`` access would appear as either ``err.message`` or
    # ``error.message`` in classic IIFE code.
    for forbidden in ("err.message", "error.message", "e.message"):
        assert forbidden not in source, (
            "settings.js must not read .message in catch: " + forbidden
        )


def test_settings_js_uses_text_content_not_inner_html_6a() -> None:
    """Phase 6A: settings.js dynamic rendering must use ``textContent``;
    ``innerHTML`` is forbidden for dynamic content."""
    source = read_js("settings.js")
    assert "textContent" in source
    assert "innerHTML" not in source


def test_settings_js_no_clickable_write_buttons_6a() -> None:
    """Phase 6A: the Settings / Privacy page must not surface any
    clickable save / export / import / clear / clipboard-toggle write
    button. The only allowed button is the read-only refresh button."""
    source = read_js("settings.js")
    lowered = source.lower()
    for forbidden in (
        "savebtn",
        "save_btn",
        "save-button",
        "exportbtn",
        "export_btn",
        "export-button",
        "importbtn",
        "import_btn",
        "import-button",
        "clearbtn",
        "clear_btn",
        "clear-button",
        "toggleclipbtn",
        "toggle_clip_btn",
        "clipboardtogglebtn",
        "clipboard_toggle_btn",
    ):
        assert forbidden not in lowered, (
            "settings.js must not wire write button: " + forbidden
        )


def test_index_html_no_settings_write_buttons_6a() -> None:
    """Phase 6A: index.html page-settings must not include any save /
    export / import / clear / clipboard-toggle write button id."""
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
    ):
        assert forbidden not in section, (
            "index.html page-settings must not contain write button id: "
            + forbidden
        )


def test_settings_js_state_variables_declared_6a() -> None:
    """Phase 6A: core.js must declare the settings state variables used by
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


def test_settings_js_lazy_load_in_switch_page_6a() -> None:
    """Phase 6A: switchPage must lazy-load the settings status when
    navigating to the page for the first time."""
    source = read_js("init.js")
    pos = source.find("function switchPage")
    assert pos != -1
    body = source[pos:pos + 3500]
    assert '"settings"' in body or "'settings'" in body
    assert "loadSettingsPrivacyStatus" in body


def test_settings_js_refresh_button_binding_in_init_buttons_6a() -> None:
    """Phase 6A: initButtons must bind the settings-refresh-btn to
    ``App.loadSettingsPrivacyStatus`` (read-only refresh)."""
    source = read_js("init.js")
    pos = source.find("function initButtons")
    assert pos != -1
    body = source[pos:pos + 6000]
    assert "settings-refresh-btn" in body
    assert "loadSettingsPrivacyStatus" in body


# --- Stylesheet ----------------------------------------------------------


def test_styles_css_has_settings_scoped_classes_6a() -> None:
    """Phase 6A: styles.css must scope the Settings / Privacy page CSS
    under ``settings-*`` classes."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    for cls in (
        ".settings-header",
        ".settings-subtitle",
        ".settings-refresh-btn",
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
