from __future__ import annotations
import os, sys
import re
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from static_helpers import func_body, read_js, read_resource  # noqa: E402


def _css_rule(source: str, selector: str) -> str:
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", source)
    assert match, f"styles.css must define {selector}"
    return match.group(1)


def test_overview_renders_authoritative_groups_and_timeline_intents():
    source = read_js("overview.js")
    show = func_body(source, "showOverview")
    assert "bundle.current_activity" in show
    assert "bundle.current_session" in show
    assert "renderProjectDistribution(bundle.project_distribution)" in show
    assert "renderRecent(bundle.recent)" in show
    intent = func_body(source, "timelineIntent")
    assert "projection_instance_key" in intent
    assert "focusTarget" in intent
    assert 'App.switchPage("timeline")' in intent


def test_derived_description_has_explicit_non_color_label():
    source = read_js("overview.js")
    assert 'description_source === "derived"' in source
    assert 'content: "自动摘要"' in read_resource("styles.css")


def test_overview_distribution_reads_the_accepted_overview_payload_directly():
    show = func_body(read_js("overview.js"), "showOverview")
    assert "bundle.project_distribution" in show
    assert "bundle.project_count" not in show
    assert "bundle.classified_duration" not in show
    assert "bundle.uncategorized_duration" not in show
    assert "bundle.overview" not in show


def test_overview_shipping_ui_uses_authoritative_module_names():
    """Regression guard: the shipping UI must use the canonical module
    names "当前活动 / 最近记录" and must not reintroduce the retired
    attention section or "最近活动" label in user-visible markup or ARIA."""
    html = read_resource("index_fd_work_v5.html")
    assert "当前活动" in html
    assert "最近记录" in html
    assert "待整理" not in html
    assert "overview-attention-list" not in html
    assert "overview-attention-more" not in html
    assert "最近活动" not in html, "shipping HTML must not use retired '最近活动' label"
    overview_js = read_js("overview.js")
    assert "暂无最近记录" in overview_js, "empty state must use '暂无最近记录'"
    assert "最近活动" not in overview_js, "overview.js must not use retired '最近活动' label"


def test_overview_view_model_does_not_reintroduce_attention_selection():
    """Overview keeps shared row facts but has no page-level attention list."""
    import inspect
    from worktrace.services import view_model_service

    source = inspect.getsource(view_model_service)
    assert "_ATTENTION_LIMIT" not in source
    assert "_select_overview_recent_rows" not in source
    assert '"attention":' not in source
    assert '"attention_remaining_count":' not in source
    assert '"needs_attention":' in source
    assert '"missing_fields":' in source


def test_overview_project_bar_is_unheaded_narrow_and_accessible():
    html = read_resource("index_fd_work_v5.html")
    css = read_resource("styles.css")
    source = read_js("overview.js")
    render = func_body(source, "renderProjectDistribution")

    assert 'id="overview-project-bar"' in html
    assert 'role="list"' in html
    assert 'aria-label="今日项目和未归类时间分布"' in html
    assert "项目分布</h" not in html
    assert "height: 30px" in css
    assert "--overview-bar-min-segment: 88px" in css
    assert "--overview-bar-min-segment: 64px" in css
    bar_rule = _css_rule(css, ".overview-project-bar")
    segment_rule = _css_rule(css, ".overview-project-segment")
    assert "display: flex" in bar_rule
    assert "flex-basis: var(--overview-bar-min-segment)" in segment_rule
    assert "flex-shrink: 1" in segment_rule
    assert "gridTemplateColumns" not in render
    assert "minmax(var(--overview-bar-min-segment)" not in render
    assert "Number(segment.duration_seconds)" in render
    assert "Number.isFinite(rawSeconds)" in render
    assert "Math.max(0, rawSeconds)" in render
    assert "var grow = Math.max(1, Math.round(seconds))" in render
    assert 'style="flex-grow: ' in render
    assert "ResizeObserver" not in source
    assert "addEventListener" not in render


def test_project_distribution_render_owns_text_safety_and_segment_semantics():
    source = read_js("overview.js")
    core = read_js("core.js")
    render = func_body(source, "renderProjectDistribution")

    assert 'function formatCompactHours(seconds)' in core
    assert '.toFixed(1) + " h"' in core
    assert "App.formatCompactHours(seconds)" in render
    assert "function formatCompactHours" not in source
    assert "App.escapeHtml(label)" in render
    assert "App.escapeHtml(hours)" in render
    assert 'title="' in render
    assert 'aria-label="' in render
    assert "rank-" in render
    assert "is-uncategorized" in render
    assert "is-other" in render
    assert "bar.hidden = true" in render
    assert "bar.hidden = false" in render
    assert 'bar.innerHTML = ""' in render


def test_overview_time_axis_and_recent_columns_are_stable_and_local():
    css = read_resource("styles.css")
    source = read_js("overview.js")
    render = func_body(source, "renderRecent")

    overview_rule = _css_rule(css, ".overview-page")
    active_rule = _css_rule(css, ".overview-page.active")
    total_rule = _css_rule(css, ".overview-page .page-total")
    current_rule = _css_rule(css, ".current-activity")
    primary_time_rule = _css_rule(
        css,
        ".overview-page .page-total strong,\n.overview-page .current-duration",
    )
    recent_section_rule = _css_rule(css, ".recent-section")
    recent_list_rule = _css_rule(css, ".recent-section .data-list")
    recent_rule = _css_rule(css, ".recent-row")
    start_rule = _css_rule(css, ".recent-start-time")
    duration_rule = _css_rule(css, ".recent-duration")

    assert "--overview-time-right-inset: 20px" in overview_rule
    assert "--overview-record-time-size: 14px" in overview_rule
    assert "overflow: hidden" in overview_rule
    assert "display: flex" in active_rule
    assert "flex-direction: column" in active_rule
    assert "padding-right: var(--overview-time-right-inset)" in total_rule
    assert "var(--overview-time-right-inset)" in current_rule
    assert "min-width: 8ch" in primary_time_rule
    assert "font-size: var(--font-size-2xl)" in primary_time_rule
    assert "font-variant-numeric: tabular-nums" in primary_time_rule
    assert ".current-duration { font-size: var(--font-size-xl)" not in css

    assert "flex: 1 1 auto" in recent_section_rule
    assert "min-height: 0" in recent_section_rule
    assert "overflow: hidden" in recent_section_rule
    assert "overflow-y: auto" in recent_list_rule
    assert "scrollbar-gutter: stable" in recent_list_rule
    assert "padding-right: var(--overview-time-right-inset)" in recent_list_rule

    assert "grid-template-columns: 52px minmax(0, 1fr) var(--record-duration-width)" in recent_rule
    assert "column-gap: 10px" in recent_rule
    assert "grid-column: 1" in start_rule
    assert "font-size: var(--overview-record-time-size)" in start_rule
    assert "grid-column: 3" in duration_rule
    assert "font-size: var(--overview-record-time-size)" in duration_rule
    assert "font-variant-numeric: tabular-nums" in duration_rule

    assert 'class="recent-start-time numeric"' in render
    assert 'class="recent-main"><span class="recent-title-line">' in render
    assert "recent-status" not in render
    assert "badge-live" not in render
    assert "进行中" not in render
    assert ".recent-status" not in css
    assert ".badge-live" not in css
    assert "+ durationMarkup(item, \"overview-recent\") + '</button>'" in render


def test_current_activity_card_uses_structured_dto_not_display_string():
    """Regression guard: the Overview current-activity card must read the
    structured DTO fields (resource_name, app_name, project_name) and must
    not parse the combined `display` string or use current_session as the
    card content source. The unstructured Timeline path may still use
    `current.display` as transport, so the guard isolates the structured
    block via a comment marker."""
    core_js = read_js("core.js")
    marker = "// Structured Overview card"
    idx = core_js.find(marker)
    assert idx != -1, "core.js must delimit the structured Overview card path"
    structured_block = core_js[idx:]
    assert "current.resource_name" in structured_block
    assert "current-context" in structured_block or "currentContextLine" in structured_block
    assert 'split("｜")' not in structured_block, (
        "structured Overview card must not parse the combined display string"
    )
    assert "current_session.project_name" not in structured_block, (
        "structured Overview card must not read current_session for card content"
    )
