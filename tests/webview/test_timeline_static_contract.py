from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def _source(name: str) -> str:
    return (ROOT / "worktrace" / "webview_ui" / "js" / name).read_text(encoding="utf-8")


def _resource(name: str) -> str:
    return (ROOT / "worktrace" / "webview_ui" / name).read_text(encoding="utf-8")


def test_timeline_consumes_canonical_entries_and_authoritative_mutation_result():
    source = _source("timeline.js")
    assert "data.entries" in source
    assert "selection_hint" in source
    assert "snapshot_revision" in source
    assert "outcome_type" in source
    assert "data.sessions" not in source
    assert "session_id" not in source


def test_details_and_mutation_have_single_owner_models():
    source = _source("timeline.js") + _source("core.js")
    assert "detailsOwner" in source
    assert "detailsRequestToken" not in source
    assert "selectedSessionId" not in source
    assert "selectedSessionLiveKey" not in source


def test_unknown_and_refresh_failure_messages_are_explicit():
    source = _source("timeline.js")
    assert "操作结果尚未确认，可重试同一操作或刷新核对" in source
    assert "操作已保存，但刷新失败" in source


def test_timeline_empty_state_uses_shared_visual_language():
    source = _source("timeline.js")
    assert 'class="empty-state timeline-empty"' in source
    assert "当日暂无时间记录" in source
    assert "选择其他日期，或开始记录新的工作活动。" in source


def test_timeline_header_filter_editor_and_advanced_menu_contract():
    html = _resource("index.html")
    timeline_page = html[html.index('id="page-timeline"') : html.index('id="page-statistics"')]

    header = timeline_page[: timeline_page.index("</header>") + len("</header>")]
    assert 'class="page-total"' in header
    assert 'id="timeline-total-label"' in header
    assert 'id="timeline-total"' in header
    assert "今日总时长" in header
    assert "toolbar-total" not in timeline_page

    toolbar = timeline_page[
        timeline_page.index('class="toolbar timeline-toolbar"') :
        timeline_page.index('id="timeline-error"')
    ]
    assert '<label for="timeline-project-filter">项目</label>' in toolbar
    assert '<option value="">全部项目</option>' in toolbar
    assert "项目：全部" not in toolbar

    textarea = re.search(r'<textarea id="edit-note-text"[^>]*>', timeline_page)
    assert textarea is not None
    assert 'rows="2"' in textarea.group(0)
    assert 'maxlength="200"' in textarea.group(0)
    assert "0 / 200" in timeline_page
    assert 'id="timeline-readonly-notice"' in timeline_page
    assert "进行中时段不可编辑，结束后可修改项目、描述和时长。" in timeline_page

    action_menu = timeline_page[
        timeline_page.index('id="timeline-session-actions"') :
        timeline_page.index("</div>", timeline_page.index('id="timeline-session-actions"'))
    ]
    expected = [
        ('id="timeline-copy-session"', "复制时间段"),
        ('id="timeline-split-session"', "拆分时间段"),
        ('id="timeline-merge-previous"', "合并到前一时间段"),
        ('id="timeline-merge-next"', "合并到后一时间段"),
    ]
    positions = []
    for element_id, label in expected:
        position = action_menu.index(element_id)
        assert label in action_menu[position:]
        positions.append(position)
    assert positions == sorted(positions)
    assert re.search(
        r'id="timeline-advanced-toggle"[^>]*class="[^"]*inline-icon-button',
        timeline_page,
    )
    assert re.search(
        r'id="timeline-hide-session"[^>]*class="[^"]*inline-icon-button',
        timeline_page,
    )
    for control_id in ("timeline-prev-btn", "timeline-next-btn", "timeline-today-btn"):
        control = re.search(r'id="' + control_id + r'"[^>]*>', timeline_page)
        assert control is not None
        assert "inline-icon-button" not in control.group(0)


def test_timeline_transient_reset_preserves_selection_and_autosave_owners():
    source = _source("timeline.js")
    close_menu = source[
        source.index("function closeTimelineAdvancedMenu") :
        source.index("App.closeTimelineAdvancedMenu")
    ]
    reset = source[
        source.index("function resetTimelineTransientUi") :
        source.index("App.resetTimelineTransientUi")
    ]
    assert 'menu.hidden = true' in close_menu
    assert 'setAttribute("aria-expanded", "false")' in close_menu
    assert "closeTimelineAdvancedMenu" in reset
    assert "closeTimelineDrawer" in reset
    assert "clearEditPanel" not in reset
    assert "selectedProjectionInstanceKey" not in reset
    assert "timelineAutosaveTimer" not in reset
    assert "timelineAutosaveQueued" not in reset
    assert "submittedDraft" not in reset


def test_timeline_list_sort_duration_and_badge_contract():
    source = _source("timeline.js")
    core = _source("core.js")
    overview = _source("overview.js")

    assert "filteredTimelineSessions(allSessions)" in source
    assert ".slice().sort(timelineSessionOrder)" in source
    assert "left.is_in_progress ? -1 : 1" not in source
    assert "projection_instance_key" in source[source.index("function timelineSessionOrder") :]
    assert 'data-duration-format="compact-hours"' in source
    assert "App.formatCompactHours(seconds)" in source
    assert "进行中</span>" not in source
    assert "function formatCompactHours" not in overview
    assert "App.formatCompactHours" in overview
    assert "data-duration-format" in core
    assert "aria-label" in core
    assert "title" in core


def test_timeline_styles_keep_fixed_time_columns_and_two_line_editor():
    css = _resource("styles.css")
    item = re.search(r"\.timeline-item\s*\{([^}]*)\}", css)
    start = re.search(r"\.timeline-item-time\s*\{([^}]*)\}", css)
    side = re.search(r"\.timeline-item-side\s*\{([^}]*)\}", css)
    duration = re.search(r"\.timeline-item-duration\s*\{([^}]*)\}", css)
    editor = re.search(
        r"\.timeline-edit-panel\s+#edit-note-text\s*\{([^}]*)\}",
        css,
    )
    assert all(match is not None for match in (item, start, side, duration, editor))
    assert "52px minmax(0, 1fr) 72px" in item.group(1)
    assert "align-items: center" in item.group(1)
    assert "align-self: center" in start.group(1)
    assert "font-size: 13px" in start.group(1)
    assert "font-variant-numeric: tabular-nums" in start.group(1)
    assert "align-self: center" in side.group(1)
    assert "justify-self: end" in side.group(1)
    assert "font-size: 13px" in duration.group(1)
    assert "font-variant-numeric: tabular-nums" in duration.group(1)
    assert "height: 50px" in editor.group(1)
    assert "max-height: 50px" in editor.group(1)
    assert "resize: none" in editor.group(1)
    assert ".toolbar-total" not in css
    assert ".badge.live::before" not in css
    inline = re.search(r"\.inline-icon-button\s*\{([^}]*)\}", css)
    inline_hover = re.search(
        r"\.inline-icon-button:hover:not\(:disabled\)\s*\{([^}]*)\}",
        css,
    )
    expanded = re.search(
        r"\.inline-icon-button\[aria-expanded=\"true\"\]\s*\{([^}]*)\}",
        css,
    )
    danger_hover = re.search(
        r"\.inline-icon-button\.danger-icon-button:hover:not\(:disabled\)\s*\{([^}]*)\}",
        css,
    )
    assert inline is not None and "border" in inline.group(1) and "transparent" in inline.group(1)
    assert inline_hover is not None and "background" in inline_hover.group(1)
    assert "border" not in inline_hover.group(1) or "transparent" in inline_hover.group(1)
    assert expanded is not None
    assert "var(--color-accent)" in expanded.group(1)
    assert danger_hover is not None
    assert "border-color: transparent" in danger_hover.group(1)
    assert "var(--color-danger-soft)" in danger_hover.group(1)
