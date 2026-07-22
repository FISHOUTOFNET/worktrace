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
    html = read_resource("index.html")
    styles = read_resource("styles.css")
    init = read_js("init.js")
    assert 'aria-current="page"' in html
    assert 'setAttribute("aria-current", "page")' in init
    assert 'removeAttribute("aria-current")' in init
    assert "@media (max-width: 959px)" in styles
    assert "grid-template-columns: 60px" in styles
    assert ".app-nav" in styles and ".nav-label" in styles


def test_focus_drawer_dialog_and_toast_are_shared_accessible_primitives() -> None:
    html = read_resource("index.html")
    styles = read_resource("styles.css")
    components = read_js("ui_components.js")
    assert ":focus-visible" in styles
    assert 'role="dialog"' in html and 'aria-modal="true"' in html
    assert "trapFocus" in components and "restoreFocus" in components
    assert 'event.key === "Escape"' in components
    assert "dialogState.step === 1" in components and "dialogState.step = 2" in components
    assert 'role="status" aria-live="polite"' in html


def test_timeline_keeps_liveclock_attributes_and_uses_autosave_owner() -> None:
    source = read_js("timeline.js")
    assert "App.liveClockDataAttributes" in source
    assert "App.timelineRequestState.nextMutationOwner" in source
    assert "scheduleTimelineAutosave(650)" in read_js("init.js")
    assert "timelineAutosaveQueued" in source
    assert "markMutationUnknown" in source
    assert "refreshAfterConfirmedMutation" in source
    assert "window.confirm" not in source


def test_timeline_list_and_compact_inspector_have_keyboard_semantics() -> None:
    html = read_resource("index.html")
    source = read_js("timeline.js")
    styles = read_resource("styles.css")
    assert 'role="listbox"' in html
    assert 'role="option"' in source and 'aria-selected="' in source
    assert 'event.key !== "ArrowDown"' in source and 'event.key !== "ArrowUp"' in source
    assert ".timeline-inspector.drawer-open" in styles
    assert "App.trapFocus" in source and "closeTimelineDrawer" in source


def test_direct_deletions_use_shared_dialog_and_wait_for_backend_refresh() -> None:
    timeline = read_js("timeline.js")
    rules = read_js("rules_keyword_actions.js") + read_js("rules_create_panel.js")
    assert 'confirmTimelineDeletion("hideActivity"' in timeline
    assert "App.openDeleteDialog" in timeline
    assert "twoStep: true" in timeline
    assert "refreshAfterConfirmedMutation" in timeline
    assert "App.openDeleteDialog" in rules
    assert "window.confirm" not in read_all_js()


def test_frontend_resources_are_local_and_do_not_create_second_runtime_store() -> None:
    html = read_resource("index.html")
    source = read_all_js()
    assert not re.search(r'<(?:script|link)[^>]+https?://', html, re.I)
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "indexedDB"):
        assert forbidden not in source
    assert source.count("setInterval(") == 1
