from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "worktrace" / "webview_ui" / "js"

EDITOR_PRIVATE_GLOBALS = (
    "App.editingSession",
    "App.timelineCompositionActive",
    "App.timelineDurationDraftTouched",
    "App.timelineDurationDraftInvalid",
    "App.timelineAutosaveTimer",
    "App.timelineAutosaveQueued",
    "App.editSaving",
    "App.timelineSavePromise",
    "App.timelineLastSaveFailed",
    "App.submittedDraft",
)


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
    assert "App.renderTimelineTotal = renderTimelineTotal" in presentation
    assert "App.resetTimelineTransientUi = resetTimelineTransientUi" in transient
    assert "App.timelineEditorState = Object.freeze" in editor
    assert "App.resetTimelineFDWorkState" in fd_work
    assert "timelineRequestState.nextMutationOwner" not in presentation
    assert "timelineRequestState.nextMutationOwner" not in transient
    assert "timelineRequestState.nextMutationOwner" not in editor


def test_editor_private_state_has_no_app_global_fact_source():
    core = read("core.js")
    combined = "\n".join(path.read_text(encoding="utf-8") for path in JS.glob("*.js"))
    for global_name in EDITOR_PRIVATE_GLOBALS:
        assert global_name not in core
        assert global_name not in combined


def test_timeline_editor_exposes_intent_and_lifecycle_capabilities():
    editor = read("timeline_editor_state.js")
    assert "App.timelineEditorState = Object.freeze" in editor
    for capability in (
        "populate",
        "clear",
        "currentSession",
        "isDirty",
        "isComposing",
        "captureSaveIntent",
        "scheduleAutosave",
        "cancelAutosave",
        "hasQueuedAutosave",
        "consumeQueuedAutosave",
        "rebase",
        "resetGeneration",
        "preview",
    ):
        assert capability + ":" in editor
    assert "saveTimelineSessionEdit" not in editor


def test_timeline_coordinator_submits_editor_intent_without_parsing_editor_dom():
    coordinator = read("timeline.js")
    assert "captureSaveIntent()" in coordinator
    for dom_id in ("edit-project-select", "edit-note-text", "edit-duration-input"):
        assert f'document.getElementById("{dom_id}")' not in coordinator
    assert "App.bridge.saveTimelineSessionEdit" in coordinator
    assert "App.timelineEditMutation = Object.freeze" in coordinator


def test_fd_work_uses_editor_and_mutation_capabilities_only():
    fd_work = read("timeline_fd_work.js")
    assert "App.timelineEditorState" in fd_work
    assert "App.timelineEditMutation" in fd_work
    for dom_id in ("edit-project-select", "edit-note-text", "edit-duration-input"):
        assert dom_id not in fd_work
    for global_name in EDITOR_PRIVATE_GLOBALS:
        assert global_name not in fd_work


def test_save_bridge_and_editor_globals_have_single_owners():
    bridge_owners = []
    for path in JS.glob("*.js"):
        if "App.bridge.saveTimelineSessionEdit" in path.read_text(encoding="utf-8"):
            bridge_owners.append(path.name)
    assert bridge_owners == ["timeline.js"]


def test_generation_and_transient_resets_respect_editor_owner():
    coordinator = read("timeline.js")
    transient = read("timeline_transient_ui.js")
    reset = coordinator.split("function resetTimelineGeneration()", 1)[1].split(
        "App.timeline = Object.freeze", 1
    )[0]
    assert "App.timelineEditorState.resetGeneration()" in reset
    for global_name in EDITOR_PRIVATE_GLOBALS:
        assert global_name not in reset
        assert global_name not in transient
