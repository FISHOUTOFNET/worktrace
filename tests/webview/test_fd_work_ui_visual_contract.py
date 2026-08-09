"""Static contracts for the compact FD Work UI integration."""
from __future__ import annotations

import os
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import read_resource  # noqa: E402


def test_fd_work_controls_reuse_the_worktrace_visual_system() -> None:
    styles = read_resource("styles.css")

    assert "var(--border, #d8dde6)" not in styles
    assert "var(--surface-muted, #f2f5f9)" not in styles
    assert ".fd-work-picker-control { padding: 0; border: 0;" in styles
    assert "#rules-panel-fd-work-help { display: none !important; }" in styles
    assert "grid-template-columns: minmax(0, 1fr) auto;" in styles
    assert "@media (max-width: 479px)" in styles


def test_timeline_fd_work_action_does_not_compete_with_icon_actions() -> None:
    styles = read_resource("styles.css")

    editor = styles[styles.index(".editor-actions {") : styles.index(".timeline-readonly-notice")]
    assert "display: grid" in editor
    assert "grid-template-columns: minmax(0, 1fr) var(--control-height) var(--control-height)" in editor
    assert "#timeline-advanced-toggle { grid-column: 2; grid-row: 1; }" in editor
    assert "#timeline-hide-session { grid-column: 3; grid-row: 1; }" in editor
    assert "-webkit-line-clamp: 2" in editor


def test_fd_work_disabled_primary_and_settings_reconnect_are_low_emphasis() -> None:
    styles = read_resource("styles.css")

    assert ".button.primary:disabled, button.primary:disabled" in styles
    assert "opacity: 1; box-shadow: none;" in styles
    assert "#settings-fd-work-reconnect:not([hidden])" in styles
    assert "border-color: transparent; background: transparent" in styles
    assert "label.setting-row:has(+ #settings-fd-work-reconnect:not([hidden]))" in styles
