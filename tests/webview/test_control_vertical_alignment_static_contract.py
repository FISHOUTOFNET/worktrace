"""Static contracts for cross-page single-line control vertical alignment."""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

WEBVIEW_UI_DIR = Path(__file__).resolve().parents[2] / "worktrace" / "webview_ui"
FINAL_CSS = (WEBVIEW_UI_DIR / "ui_components.css").read_text(encoding="utf-8")


def _block_after(marker: str, start: int = 0) -> str:
    selector_start = FINAL_CSS.index(marker, start)
    body_start = FINAL_CSS.index("{", selector_start) + 1
    body_end = FINAL_CSS.index("}", body_start)
    return FINAL_CSS[body_start:body_end]


def test_compact_toolbars_share_fixed_single_line_control_height() -> None:
    marker = ":where(\n    .timeline-toolbar,\n    .statistics-toolbar,\n    .rules-toolbar\n) :is("
    selector_start = FINAL_CSS.index(marker)
    selector_end = FINAL_CSS.index("{", selector_start)
    selector = FINAL_CSS[selector_start:selector_end]
    block = FINAL_CSS[selector_end + 1:FINAL_CSS.index("}", selector_end)]

    assert "button:not(.project-autocomplete-option)" in selector
    assert "height: var(--control-height-sm);" in block
    assert "min-height: var(--control-height-sm);" in block


def test_compact_toolbar_inputs_and_selects_remove_native_vertical_padding() -> None:
    marker = ":where(\n    .timeline-toolbar,\n    .statistics-toolbar,\n    .rules-toolbar\n) :is("
    first = FINAL_CSS.index(marker)
    second = FINAL_CSS.index(marker, FINAL_CSS.index("}", first) + 1)
    block = _block_after(marker, second)
    assert "padding-block: 0;" in block


def test_toolbar_labels_statistics_separator_and_native_date_edit_are_centered() -> None:
    label_marker = ") > label:not(.sr-only),\n.statistics-date-inputs > span[aria-hidden=\"true\"]"
    label_block = _block_after(label_marker)
    assert "min-height: var(--control-height-sm);" in label_block
    assert "display: inline-flex;" in label_block
    assert "align-items: center;" in label_block

    date_block = _block_after(") input[type=\"date\"]::-webkit-datetime-edit")
    assert "padding-block: 0;" in date_block


def test_regular_inline_input_button_pairs_keep_normal_control_height() -> None:
    marker = ":where(\n    .folder-picker-control,\n    .danger-inline\n) :is("
    block = _block_after(marker)
    assert "height: var(--control-height);" in block
    assert "min-height: var(--control-height);" in block

    assert ".input-with-unit input {\n    padding-block: 0;\n}" in FINAL_CSS
