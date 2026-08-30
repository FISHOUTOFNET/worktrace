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


def test_compact_timeline_and_rules_keep_labels_with_controls() -> None:
    final = _resource("ui_components.css")

    timeline = _rule(final, ".timeline-toolbar")
    timeline_label = _rule(
        final,
        '.timeline-toolbar > label[for="timeline-project-filter"]',
    )
    timeline_filter = _rule(
        final,
        ".timeline-toolbar > .project-autocomplete-shell.project-autocomplete-filter",
    )
    rules = _rule(final, ".rules-toolbar")
    rules_label = _rule(final, '.rules-toolbar > label[for="rules-sort-select"]')
    rules_select = _rule(final, ".rules-toolbar > #rules-sort-select")
    rules_search = _rule(final, ".rules-toolbar > #rules-search-input")

    assert "display: grid" in timeline
    assert "grid-template-columns: auto minmax(0, 1fr)" in timeline
    assert "grid-row: 2" in timeline_label and "grid-column: 1" in timeline_label
    assert "grid-row: 2" in timeline_filter and "grid-column: 2" in timeline_filter

    assert "display: grid" in rules
    assert "grid-template-columns: auto minmax(0, 1fr)" in rules
    assert "grid-row: 2" in rules_label and "grid-column: 1" in rules_label
    assert "grid-row: 2" in rules_select and "grid-column: 2" in rules_select
    assert "grid-column: 1 / -1" in rules_search
    assert "min-width: 0" in rules_search


def test_compact_settings_keep_simple_rows_inline_and_stack_only_complex_danger_row() -> None:
    final = _resource("ui_components.css")

    setting_row = _rule(final, ".settings-content .setting-row")
    storage = _rule(final, "#settings-storage-card")
    data_path = _rule(final, ".settings-local-data-path")
    danger_row = _rule(final, ".settings-content .danger-zone .setting-row")
    buttons = _rule(final, ".settings-content .button-row")

    assert "grid-template-columns: minmax(0, 1fr) auto" in setting_row
    assert "grid-template-columns: auto minmax(0, 1fr)" in storage
    assert "min-width: 0" in data_path
    assert "text-overflow: ellipsis" in data_path
    assert "white-space: nowrap" in data_path
    assert "grid-template-columns: 1fr" in danger_row
    assert "flex-wrap: wrap" in buttons


def test_visible_autocomplete_filter_owns_compact_shrink_and_menu_width() -> None:
    autocomplete = _resource("project_autocomplete.css")

    filter_shell = _rule(
        autocomplete,
        ".project-autocomplete-shell.project-autocomplete-filter",
    )
    compact_filter = _rule(
        autocomplete,
        ".toolbar .project-autocomplete-shell.project-autocomplete-filter",
    )
    compact_menu = _rule(
        autocomplete,
        ".toolbar .project-autocomplete-filter .project-autocomplete-menu",
    )

    assert "min-width: 0" in filter_shell
    assert "max-width: 100%" in filter_shell
    assert "min-width: 0" in compact_filter
    assert "max-width: 100%" in compact_filter
    assert "width: 100%" in compact_menu
    assert "min-width: 100%" in compact_menu
    assert "max-width: 100%" in compact_menu
