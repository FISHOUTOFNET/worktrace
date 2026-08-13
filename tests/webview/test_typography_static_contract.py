"""Static contracts for the shipping Simplified-Chinese typography system."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

ROOT = Path(__file__).resolve().parents[2]
UI_ROOT = ROOT / "worktrace" / "webview_ui"
BASE_CSS = UI_ROOT / "styles.css"
FINAL_CSS = UI_ROOT / "ui_components.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_shipping_typography_uses_one_cjk_capable_ui_family() -> None:
    final_css = _read(FINAL_CSS)
    assert '--font-sans: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;' in final_css
    assert "font-synthesis: none" in final_css
    assert "@font-face" not in _read(BASE_CSS) + "\n" + final_css


def test_mixed_script_emphasis_uses_real_bold_face() -> None:
    final_css = _read(FINAL_CSS)
    expected_selectors = (
        ".page-header h1",
        ".nav-item.active",
        ".topbar-context",
        "th",
        '.tabs button[aria-selected="true"]',
        ".tabs button.is-active",
        ".current-label",
        ".overview-project-hours",
        ".recent-project",
        ".timeline-item-project",
        '.quick-ranges button[aria-pressed="true"]',
        ".rules-project-title",
        '.settings-categories button[aria-current="true"]',
    )
    weight_block = re.search(
        r"(?P<selectors>(?:[^{}]|\n)+)\{\s*font-weight:\s*700;\s*\}",
        final_css,
    )
    assert weight_block, "expected final mixed-script emphasis block"
    selectors = weight_block.group("selectors")
    for selector in expected_selectors:
        assert selector in selectors


def test_numeric_alignment_remains_tabular_without_a_separate_font_family() -> None:
    base_css = _read(BASE_CSS)
    final_css = _read(FINAL_CSS)
    assert "font-variant-numeric: tabular-nums" in base_css
    assert not re.search(r"\.numeric[^{}]*\{[^{}]*font-family", final_css, re.DOTALL)
    assert not re.search(r"\.number[^{}]*\{[^{}]*font-family", final_css, re.DOTALL)


def test_controls_keep_inheriting_the_shared_ui_font() -> None:
    base_css = _read(BASE_CSS)
    assert "button, input, select, textarea { color: inherit; font: inherit; }" in base_css
