from __future__ import annotations

from pathlib import Path
import re

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "worktrace" / "webview_ui"


def _resource(name: str) -> str:
    return (UI_ROOT / name).read_text(encoding="utf-8")


def _rule(source: str, selector: str) -> str:
    match = re.search(
        r"(?m)^[ \t]*" + re.escape(selector) + r"\s*\{([^}]*)\}",
        source,
    )
    assert match is not None, f"missing CSS rule: {selector}"
    return match.group(1)


def test_settings_section_owns_full_width_footer_divider() -> None:
    metadata = _resource("application_metadata.css")

    section = _rule(metadata, ".settings-section:not([hidden])")
    footer = _rule(metadata, ".settings-application-footer")

    assert "border-bottom: 1px solid var(--color-border)" in section
    assert "margin: 0" in footer
    assert "border-top: 0" in footer
    assert "margin: 18px 8px 0" not in footer


def test_local_data_path_shrinks_in_supported_desktop_layout() -> None:
    metadata = _resource("application_metadata.css")
    index = _resource("index_fd_work_v5.html")

    storage = _rule(metadata, "#settings-storage-card")
    data_path = _rule(metadata, ".settings-local-data-path")

    assert "grid-template-columns: auto minmax(0, 1fr)" in storage
    assert "min-width: 0" in data_path
    assert "max-width: 100%" in data_path
    assert "justify-self: end" in data_path
    assert "overflow: hidden" in data_path
    assert "text-overflow: ellipsis" in data_path
    assert "white-space: nowrap" in data_path
    assert "text-align: right" in data_path
    assert index.index("styles.css?") < index.index("application_metadata.css?")
    assert index.index("ui_components.css?") < index.index("application_metadata.css?")


def test_advanced_settings_no_longer_use_compensating_negative_spacing() -> None:
    metadata = _resource("application_metadata.css")

    toggle_row = _rule(
        metadata,
        '#settings-section-advanced > label.setting-row[for="settings-fd-work-toggle"]',
    )
    reconnect = _rule(metadata, "#settings-fd-work-reconnect:not([hidden])")

    assert "padding-bottom: 9px" in toggle_row
    assert "margin: 0 0 9px auto" in reconnect
    assert "margin: -" not in reconnect
