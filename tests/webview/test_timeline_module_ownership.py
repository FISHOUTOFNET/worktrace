from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "worktrace" / "webview_ui" / "js"


def read(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


def test_timeline_coordinator_does_not_reown_extracted_concerns():
    coordinator = read("timeline.js")
    assert "function exactRowClock" not in coordinator
    assert "function renderSessionDetails" not in coordinator
    assert "function openTimelineDrawer" not in coordinator
    assert "function closeTimelineAdvancedMenu" not in coordinator
    assert "function findCachedProject" not in coordinator
    assert "var fdWorkFillTransactionSequence" not in coordinator


def test_timeline_owner_modules_are_narrow_and_explicit():
    presentation = read("timeline_presentation.js")
    transient = read("timeline_transient_ui.js")
    editor = read("timeline_editor_state.js")
    fd_work = read("timeline_fd_work.js")
    assert "App.timelinePresentation = Object.freeze" in presentation
    assert "App.resetTimelineTransientUi = resetTimelineTransientUi" in transient
    assert "App.timelineEditorState = Object.freeze" in editor
    assert "App.resetTimelineFDWorkState" in fd_work
    assert "timelineRequestState.nextMutationOwner" not in presentation
    assert "timelineRequestState.nextMutationOwner" not in transient
    assert "timelineRequestState.nextMutationOwner" not in editor
