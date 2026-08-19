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


def test_layout_scrollbars_follow_explicit_scroll_owners_without_reserving_width():
    base = _resource("styles.css")
    final = _resource("ui_components.css")

    base_page = _rule(base, ".page")
    final_page = _rule(final, ".page")

    # styles.css remains the structural baseline, while the final consistency
    # layer closes active page overflow and assigns scrolling to inner content.
    assert "overflow: auto" in base_page
    assert "min-height: 0" in final_page
    assert "scrollbar-gutter: stable" not in final

    for selector in (
        "#recent-list",
        ".timeline-list",
        ".activity-list",
        ".table-scroll",
        ".rules-scroll-region",
        ".settings-content",
        ".drawer",
        ".dialog",
        ".first-run-notice-text",
        ".settings-categories",
        ".project-autocomplete-menu",
        "textarea",
    ):
        assert selector in final

    assert "scrollbar-width: none" in final
    assert "-ms-overflow-style: none" in final
    assert "scrollbar-gutter: auto" in final
    assert ")::-webkit-scrollbar" in final
    assert "width: 0" in final
    assert "height: 0" in final
    assert "display: none" in final


def test_active_pages_close_page_level_scrolling():
    final = _resource("ui_components.css")
    active = _rule(
        final,
        ".overview-page.active,\n"
        ".timeline-page.active,\n"
        ".statistics-page.active,\n"
        ".rules-page.active,\n"
        ".settings-page.active",
    )

    assert "display: flex" in active
    assert "flex-direction: column" in active
    assert "overflow: hidden" in active


def test_overview_keeps_summary_fixed_and_restores_symmetric_spacing():
    final = _resource("ui_components.css")

    overview = _rule(final, ".overview-page")
    current = _rule(final, ".current-activity")
    recent_section = _rule(final, ".recent-section")
    recent_heading = _rule(final, ".recent-section h2")
    recent_list = _rule(final, "#recent-list")

    assert "--overview-time-right-inset: 0px" in overview
    assert "padding-right: 18px" in current

    assert "flex: 1 1 auto" in recent_section
    assert "min-height: 0" in recent_section
    assert "height: auto" in recent_section
    assert "align-self: stretch" in recent_section
    assert "padding-inline: 18px" in recent_section
    assert "overflow: hidden" in recent_section
    assert "padding-right: 0" in recent_heading

    assert "flex: 1 1 auto" in recent_list
    assert "min-height: 0" in recent_list
    assert "display: block" in recent_list
    assert "overflow: auto" in recent_list
    assert "scrollbar-gutter: auto" in recent_list


def test_timeline_keeps_editor_fixed_and_scrolls_only_activity_list():
    final = _resource("ui_components.css")
    index = _resource("index_fd_work_v5.html")

    workspace = _rule(final, ".timeline-workspace")
    timeline_list = _rule(final, ".timeline-list")
    inspector = _rule(final, ".timeline-inspector")
    details = _rule(final, ".activity-details")
    activity_list = _rule(final, ".activity-list")

    assert "flex: 1 1 auto" in workspace
    assert "min-height: 0" in workspace
    assert "height: auto" in workspace
    assert "calc(" not in workspace

    assert "overflow: auto" in timeline_list
    assert "display: flex" in inspector
    assert "flex-direction: column" in inspector
    assert "overflow: hidden" in inspector

    assert "flex: 1 1 auto" in details
    assert "min-height: 0" in details
    assert "display: flex" in details
    assert "overflow: hidden" in details

    assert "flex: 1 1 auto" in activity_list
    assert "min-height: 0" in activity_list
    assert "overflow: auto" in activity_list

    assert ".timeline-inspector.drawer-open { display: flex; }" in final
    assert index.index("styles.css?") < index.index("ui_components.css?")


def test_statistics_keeps_controls_and_metrics_fixed_while_tables_scroll():
    final = _resource("ui_components.css")

    results = _rule(final, "#statistics-results:not([hidden])")
    result_panel = _rule(final, ".stats-result")
    table_scroll = _rule(final, ".stats-result .table-scroll")

    assert "flex: 1 1 auto" in results
    assert "min-height: 0" in results
    assert "display: flex" in results
    assert "flex-direction: column" in results

    assert "flex: 1 1 auto" in result_panel
    assert "min-height: 0" in result_panel
    assert "display: flex" in result_panel
    assert "flex-direction: column" in result_panel

    assert "flex: 1 1 auto" in table_scroll
    assert "min-height: 0" in table_scroll
    assert "overflow: auto" in table_scroll


def test_rules_keep_search_and_sort_fixed_while_list_region_scrolls():
    final = _resource("ui_components.css")
    index = _resource("index_fd_work_v5.html")

    scroll_region = _rule(final, ".rules-scroll-region")
    assert "flex: 1 1 auto" in scroll_region
    assert "min-height: 0" in scroll_region
    assert "overflow: auto" in scroll_region

    wrapper = '<div class="rules-scroll-region"><div id="rules-list" class="rules-list"></div><div id="rules-empty" class="empty-state" hidden><strong>暂无项目</strong></div></div>'
    assert wrapper in index


def test_settings_keep_title_and_categories_fixed_while_content_scrolls():
    final = _resource("ui_components.css")

    status = _rule(final, "#settings-status:not([hidden])")
    content = _rule(final, ".settings-content")

    assert "flex: 1 1 auto" in status
    assert "min-height: 0" in status
    assert "display: grid" in status

    assert "min-height: 0" in content
    assert "align-self: stretch" in content
    assert "overflow: auto" in content
    assert "grid-template-rows: auto minmax(0, 1fr)" in final


def test_timeline_conditional_actions_keep_stable_nonempty_operation_slots():
    final = _resource("ui_components.css")
    presentation = _resource("js/timeline_action_presentation.js")
    index = _resource("index_fd_work_v5.html")

    disabled_danger = _rule(final, ".danger-icon-button:disabled")
    collapsed_actions = _rule(final, ".editor-actions.advanced-actions-unavailable")
    moved_delete = _rule(
        final,
        ".editor-actions.advanced-actions-unavailable #timeline-hide-session",
    )

    assert "var(--color-text-tertiary)" in disabled_danger
    assert "background: transparent" in disabled_danger
    assert "grid-template-columns: minmax(0, 1fr) var(--control-height)" in collapsed_actions
    assert "grid-column: 2" in moved_delete

    assert 'button.hidden = false' in presentation
    assert 'button.disabled = true' in presentation
    assert 'data-activity-delete-placeholder' in presentation
    assert 'button.innerHTML = App.iconMarkup("trash")' in presentation
    assert 'advanced.hidden === true' in presentation
    assert 'attributeFilter: ["hidden", "disabled"]' in presentation
    assert 'childList: true' in presentation

    assert index.index("js/timeline.js?") < index.index("js/timeline_action_presentation.js?")
    assert index.index("js/timeline_delete_actions.js?") < index.index(
        "js/timeline_action_presentation.js?"
    )
    assert index.index("js/timeline_action_presentation.js?") < index.index(
        "js/init_fd_work_v5.js?"
    )


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
