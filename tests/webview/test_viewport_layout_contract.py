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
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert match is not None, f"missing CSS rule: {selector}"
    return match.group(1)


def test_page_scrollbar_reserves_width_without_changing_normal_page_scroll_owner():
    base = _resource("styles.css")
    final = _resource("ui_components.css")

    base_page = _rule(base, ".page")
    final_page = _rule(final, ".page")

    assert "overflow: auto" in base_page
    assert "min-height: 0" in final_page
    assert "scrollbar-gutter: stable" in final_page


def test_overview_keeps_summary_fixed_and_delegates_scroll_to_recent_list():
    final = _resource("ui_components.css")

    active = _rule(final, ".overview-page.active,\n.timeline-page.active")
    recent_section = _rule(final, ".recent-section")
    recent_list = _rule(final, "#recent-list")

    assert "display: flex" in active
    assert "flex-direction: column" in active
    assert "overflow: hidden" in active

    assert "flex: 1 1 auto" in recent_section
    assert "min-height: 0" in recent_section
    assert "height: auto" in recent_section
    assert "align-self: stretch" in recent_section
    assert "overflow: hidden" in recent_section

    assert "flex: 1 1 auto" in recent_list
    assert "min-height: 0" in recent_list
    assert "display: block" in recent_list
    assert "overflow: auto" in recent_list
    assert "scrollbar-gutter: stable" in recent_list


def test_timeline_uses_remaining_viewport_instead_of_magic_height_at_all_widths():
    base = _resource("styles.css")
    final = _resource("ui_components.css")
    index = _resource("index_fd_work_v5.html")

    workspace = _rule(final, ".timeline-workspace")
    panes = _rule(final, ".timeline-list,\n.timeline-inspector")

    assert "flex: 1 1 auto" in workspace
    assert "min-height: 0" in workspace
    assert "height: auto" in workspace
    assert "calc(" not in workspace

    assert "overflow: auto" in panes
    assert "scrollbar-gutter: stable" in panes

    # styles.css still contains the legacy geometry as the structural baseline,
    # but ui_components.css is the final consistency layer and must load later.
    assert "height: calc(100% - 86px)" in base
    assert "height: calc(100% - 82px)" in base
    assert index.index("styles.css?") < index.index("ui_components.css?")


def test_loading_feedback_does_not_resize_rendered_timeline_or_settings():
    final = _resource("ui_components.css")

    timeline_loading = _rule(final, "#timeline-loading")
    settings_loading = _rule(final, "#settings-loading")

    assert "flex: 0 0 0" in timeline_loading
    assert "height: 0" in timeline_loading
    assert "min-height: 0" in timeline_loading
    assert "overflow: visible" in timeline_loading

    assert "height: 0" in settings_loading
    assert "min-height: 0" in settings_loading
    assert "overflow: visible" in settings_loading
