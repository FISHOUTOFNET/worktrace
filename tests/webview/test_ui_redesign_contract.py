"""Cross-page contracts introduced by the responsive WorkTrace UI cutover."""
from __future__ import annotations

import os
import re
import sys
import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import read_all_js, read_js, read_resource  # noqa: E402


def test_navigation_has_accessible_current_state_and_compact_rail() -> None:
    html = read_resource("index_fd_work_v5.html")
    styles = read_resource("styles.css")
    init = read_js("init_fd_work_v5.js")
    assert 'aria-current="page"' in html
    assert 'setAttribute("aria-current", "page")' in init
    assert 'removeAttribute("aria-current")' in init
    assert "@media (max-width: 959px)" in styles
    assert "grid-template-columns: 60px" in styles
    assert ".app-nav" in styles and ".nav-label" in styles


def test_topbar_is_static_and_does_not_duplicate_page_titles() -> None:
    html = read_resource("index_fd_work_v5.html")
    init = read_js("init_fd_work_v5.js")
    topbar = html[
        html.index('<header class="app-topbar">') :
        html.index("</header>", html.index('<header class="app-topbar">'))
    ]
    assert "本地工作区" in topbar
    assert "LOCAL WORKSPACE" not in topbar
    assert "app-topbar-title" not in topbar
    assert "<strong" not in topbar
    assert "app-topbar-title" not in init
    assert 'getAttribute("data-title")' not in init
    assert html.count("<h1>") >= 5


def test_focus_drawer_dialog_and_toast_are_shared_accessible_primitives() -> None:
    html = read_resource("index_fd_work_v5.html")
    styles = read_resource("styles.css")
    components = read_js("ui_components.js")
    assert ":focus-visible" in styles
    assert 'role="dialog"' in html and 'aria-modal="true"' in html
    assert "trapFocus" in components and "restoreFocus" in components
    assert 'event.key === "Escape"' in components
    assert "dialogState.step === 1" in components and "dialogState.step = 2" in components
    assert 'role="status" aria-live="polite"' in html


def test_timeline_keeps_liveclock_attributes_and_uses_autosave_owner() -> None:
    coordinator = read_js("timeline.js")
    presentation = read_js("timeline_presentation.js")
    editor = read_js("timeline_editor_state.js")
    assert "App.liveClockDataAttributes" in coordinator
    assert "App.timelineRequestState.nextMutationOwner" in coordinator
    assert "App.timelineEditorState.bindEvents()" in coordinator
    assert 'note.addEventListener("compositionstart", handleCompositionStart)' in editor
    assert 'note.addEventListener("compositionend", handleCompositionEnd)' in editor
    assert 'note.addEventListener("input", handleNoteInput)' in editor
    assert "scheduleAutosave(650)" in editor
    assert "autosaveQueued" in editor
    assert "markMutationUnknown" in coordinator
    assert "refreshAfterConfirmedMutation" in coordinator
    assert "window.confirm" not in coordinator + presentation + editor


def test_timeline_list_and_compact_inspector_have_keyboard_semantics() -> None:
    html = read_resource("index_fd_work_v5.html")
    coordinator = read_js("timeline.js")
    transient = read_js("timeline_transient_ui.js")
    styles = read_resource("styles.css")
    assert 'role="listbox"' in html
    assert 'role="option"' in coordinator and 'aria-selected="' in coordinator
    assert 'event.key !== "ArrowDown"' in coordinator and 'event.key !== "ArrowUp"' in coordinator
    assert ".timeline-inspector.drawer-open" in styles
    assert "App.trapFocus" in transient and "closeTimelineDrawer" in transient


def test_direct_deletions_use_shared_dialog_and_wait_for_backend_refresh() -> None:
    timeline = read_js("timeline.js")
    timeline_delete = read_js("timeline_delete_actions.js")
    rules = read_js("rules_delete_actions.js") + read_js("rules_create_panel_v5.js")
    assert "App.confirmTimelineDeletion = function" in timeline_delete
    assert "App.openDeleteDialog" in timeline_delete
    assert "twoStep: true" in timeline_delete
    assert "App.runTimelineSessionOperation" in timeline_delete
    assert "refreshAfterConfirmedMutation" in timeline
    assert "App.openDeleteDialog" in rules
    assert "deleteProjectFolderRule" in rules
    assert "deleteProjectKeywordRule" in rules
    assert "window.confirm" not in read_all_js()


def test_frontend_resources_are_local_and_do_not_create_second_runtime_store() -> None:
    html = read_resource("index_fd_work_v5.html")
    source = read_all_js()
    assert not re.search(r'<(?:script|link)[^>]+https?://', html, re.I)
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "indexedDB"):
        assert forbidden not in source
    assert source.count("setInterval(") == 1


def test_compact_desktop_tokens_and_single_icon_sprite_are_shared() -> None:
    html = read_resource("index_fd_work_v5.html")
    styles = read_resource("styles.css")
    assert '--control-height: 30px' in styles
    assert '--control-height-compact: 24px' in styles
    assert '--date-control-width: 116px' in styles
    assert '--record-duration-width: 76px' in styles
    assert '--sidebar-width: 188px' in styles
    assert '--page-padding-x: 18px' in styles
    compact = re.search(r"\.compact-icon-button\s*\{([^}]*)\}", styles)
    control_group = re.search(r"\.control-group\s*\{([^}]*)\}", styles)
    date_control = re.search(r"\.date-control\s*\{([^}]*)\}", styles)
    page = re.search(r"\.page\s*\{([^}]*)\}", styles)
    brand = re.search(r"\.brand-mark\s*\{([^}]*)\}", styles)
    assert compact is not None
    assert "var(--control-height-compact)" in compact.group(1)
    assert control_group is not None and "gap: 0" in control_group.group(1)
    assert date_control is not None and "var(--date-control-width)" in date_control.group(1)
    assert page is not None and "margin-inline: auto" in page.group(1)
    assert brand is not None and "background: var(--color-accent)" in brand.group(1)
    assert "--topbar-height: 40px" in styles
    for icon in ("icon-plus", "icon-pencil", "icon-trash", "icon-download"):
        assert f'id="{icon}"' in html
    assert "https://" not in html and "http://" not in html


def test_timeline_and_statistics_share_one_project_filter_control() -> None:
    html = read_resource("index_fd_work_v5.html")
    styles = read_resource("styles.css")
    for element_id in ("timeline-project-filter", "statistics-project-filter"):
        control = re.search(rf'<select id="{element_id}" class="([^"]*)"', html)
        assert control is not None
        assert "project-filter-control" in control.group(1).split()
    shared = re.search(r"\.project-filter-control\s*\{([^}]*)\}", styles)
    assert shared is not None
    for declaration in (
        "width: var(--project-filter-width)",
        "min-width: var(--project-filter-width)",
        "max-width: var(--project-filter-width)",
    ):
        assert declaration in shared.group(1)
    assert "--project-filter-width: 160px" in styles
    assert "--project-filter-width: 132px" in styles
    assert ".project-filter-control { min-width: 0; }" in styles
    assert not re.search(r"#timeline-project-filter\s*\{", styles)
    assert not re.search(r"#statistics-project-filter\s*\{", styles)
