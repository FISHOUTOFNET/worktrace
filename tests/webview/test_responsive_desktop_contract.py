"""Desktop responsive-layout contracts for the shipping WebView."""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "worktrace" / "webview_ui"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(source: str, start: str, end: str) -> str:
    assert start in source
    assert end in source
    return source.split(start, 1)[1].split(end, 1)[0]


def test_shipping_window_uses_desktop_size_floor() -> None:
    source = _read(ROOT / "worktrace" / "webview_main.py")
    assert "width=1080," in source
    assert "height=720," in source
    assert "min_size=(840, 560)," in source


def test_959_breakpoint_compacts_shell_without_reflowing_pages() -> None:
    styles = _read(UI_ROOT / "styles.css")
    compact = _between(
        styles,
        "@media (max-width: 959px) {",
        "@media (max-width: 767px) {",
    )
    for required in (
        ".app-shell",
        ".app-brand",
        ".nav-item",
        ".topbar-local",
        ".page {",
    ):
        assert required in compact
    for forbidden in (
        ".timeline-workspace",
        ".timeline-inspector",
        ".statistics-toolbar",
        ".statistics-date-range",
        ".quick-ranges",
        ".settings-layout",
        ".settings-categories",
    ):
        assert forbidden not in compact


def test_page_fallbacks_stay_below_supported_window_floor() -> None:
    styles = _read(UI_ROOT / "styles.css")
    narrow = _between(
        styles,
        "@media (max-width: 767px) {",
        "@media (max-width: 479px) {",
    )
    for expected in (
        ".timeline-workspace",
        ".timeline-page .timeline-inspector",
        ".settings-layout",
        ".settings-categories",
    ):
        assert expected in narrow

    transient = _read(UI_ROOT / "js" / "timeline_transient_ui.js")
    assert '(max-width: 767px)' in transient
    assert '(max-width: 959px)' not in transient


def test_statistics_stays_single_row_with_intrinsic_right_aligned_quick_ranges() -> None:
    styles = _read(UI_ROOT / "styles.css")
    final = _read(UI_ROOT / "ui_components.css")

    assert ".statistics-toolbar { flex-wrap: nowrap; }" in styles
    assert ".toolbar-spacer { flex: 1; }" in styles
    assert ".quick-ranges { display: flex; gap: 2px; }" in styles
    assert ".quick-ranges button { flex: 1; }" not in styles

    for forbidden in (
        ".statistics-toolbar > .statistics-date-range",
        '.statistics-toolbar > label[for="statistics-project-filter"]',
        ".statistics-toolbar > #statistics-project-filter",
        ".statistics-toolbar > .quick-ranges",
    ):
        assert forbidden not in final
