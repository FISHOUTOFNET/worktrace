from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
JS_DIR = ROOT / "worktrace" / "webview_ui" / "js"
TIMELINE = JS_DIR / "timeline.js"
HTML = ROOT / "worktrace" / "webview_ui" / "index_fd_work_v5.html"
SPEC = ROOT / "WorkTrace.spec"
STATIC_TEST = ROOT / "tests" / "webview" / "test_timeline_static_contract.py"
OWNERSHIP_TEST = ROOT / "tests" / "webview" / "test_timeline_module_ownership.py"


def cut(source: str, start_marker: str, end_marker: str) -> tuple[str, str]:
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[:start] + source[end:], source[start:end]


def replace_calls(source: str, mapping: dict[str, str]) -> str:
    for name, replacement in mapping.items():
        source = re.sub(rf"(?<!App\.)\b{re.escape(name)}\(", replacement + "(", source)
    return source


def wrap_module(title: str, blocks: list[str], footer: str = "") -> str:
    body = "".join(blocks).rstrip() + "\n"
    return (
        f"// WorkTrace WebView frontend — {title}.\n"
        "(function () {\n"
        "    \"use strict\";\n"
        "    var App = window.WorkTraceApp = window.WorkTraceApp || {};\n\n"
        + body
        + ("\n" + footer.rstrip() + "\n" if footer else "")
        + "})();\n"
    )


def main() -> None:
    source = TIMELINE.read_text(encoding="utf-8")
    if "timelinePresentation = Object.freeze" in source:
        raise SystemExit("timeline.js already appears governed")

    # Presentation owns formatting, filtering and DOM-only timeline rendering.
    source, presentation_format = cut(
        source,
        "    function exactRowClock",
        "    function renderTimelineTotal",
    )
    source, presentation_total = cut(
        source,
        "    function renderTimelineTotal",
        "    function resetEmptyTimeline",
    )
    source, presentation_rows = cut(
        source,
        "    function timelineSessionOrder",
        "    function openTimelineDrawer",
    )
    source, presentation_details = cut(
        source,
        "    function renderSessionDetails",
        "    function loadProjects",
    )
    presentation = wrap_module(
        "timeline presentation owner",
        [presentation_format, presentation_total, presentation_rows, presentation_details],
        "    App.timelinePresentation = Object.freeze({\n"
        "        exactRowClock: exactRowClock,\n"
        "        clockedSeconds: clockedSeconds\n"
        "    });",
    )

    # Transient UI owns drawer/menu/focus state. It must not own report selection
    # or editor drafts.
    source, transient_drawer = cut(
        source,
        "    function openTimelineDrawer",
        "    App.applyTimelineProjectFilter",
    )
    source, transient_menu = cut(
        source,
        "    function closeTimelineAdvancedMenu",
        "    function findCachedProject",
    )
    source, transient_reset = cut(
        source,
        "    function resetTimelineTransientUi",
        "    var TIMELINE_OPERATIONS",
    )
    transient_reset = transient_reset.replace(
        "showEditStatus(", "App.showEditStatus("
    )
    transient = wrap_module(
        "timeline transient UI owner",
        [transient_drawer, transient_menu, transient_reset],
    )

    # Editor state owns draft DOM state, validation and autosave scheduling.
    # The actual save mutation remains in timeline.js and is called through the
    # existing App.saveEdit capability.
    source, editor = cut(
        source,
        "    function findCachedProject",
        "    function blockDifferentMutationIntent",
    )
    editor_dependencies = {
        "loadProjects(": "App.loadTimelineProjects(",
        "updateFDWorkEntryButton(": "App.updateFDWorkEntryButton(",
        "updateSessionActionButtons(": "App.updateSessionActionButtons(",
        "showFDWorkStatus(": "App.showFDWorkStatus(",
        "saveEdit(": "App.saveEdit(",
        "openTimelineDrawer(": "App.openTimelineDrawer(",
    }
    for old, new in editor_dependencies.items():
        editor = editor.replace(old, new)
    editor_state = wrap_module(
        "timeline editor state owner",
        [editor],
        "    App.timelineEditorState = Object.freeze({\n"
        "        canEditField: canEditField,\n"
        "        findCachedProject: findCachedProject,\n"
        "        setReadOnlyNotice: setTimelineReadOnlyNotice,\n"
        "        cancelAutosaveTimer: cancelTimelineAutosaveTimer\n"
        "    });",
    )

    # Timeline-specific FD Work orchestration is optional plugin presentation
    # policy, not report/read/mutation coordination, so keep it outside the
    # timeline coordinator.
    source, fd_work = cut(
        source,
        "    var fdWorkFillTransactionSequence = 0;",
        "    App.refreshTimelineAfterEdit = function () {",
    )
    fd_work_dependencies = {
        "normalizeTimelineDurationInput(": "App.normalizeTimelineDurationInput(",
        "cancelTimelineAutosaveTimer(": "App.timelineEditorState.cancelAutosaveTimer(",
        "isEditDirty(": "App.isEditDirty(",
        "saveEdit(": "App.saveEdit(",
        "currentTimelineReportDate(": "App.currentTimelineReportDate(",
    }
    for old, new in fd_work_dependencies.items():
        fd_work = fd_work.replace(old, new)
    fd_work_module = wrap_module(
        "timeline FD Work interaction owner",
        [fd_work],
        "    App.resetTimelineFDWorkState = function () {\n"
        "        activeFDWorkFillTransaction = null;\n"
        "        App.fdWorkOpenPromise = null;\n"
        "        App.fdWorkStatusOverride = null;\n"
        "    };",
    )

    # Export the project-catalog load seam used by the editor owner.
    load_projects_end = (
        "    }\n\n"
        "    function confirmTimelineDeletion"
    )
    if load_projects_end not in source:
        raise AssertionError("loadProjects boundary changed")
    source = source.replace(
        load_projects_end,
        "    }\n    App.loadTimelineProjects = loadProjects;\n\n"
        "    function confirmTimelineDeletion",
        1,
    )

    # Coordinator call sites now consume explicit owner capabilities.
    source = replace_calls(source, {
        "exactRowClock": "App.timelinePresentation.exactRowClock",
        "clockedSeconds": "App.timelinePresentation.clockedSeconds",
        "formatTimelineStartTime": "App.formatTimelineStartTime",
        "formatTimelineDuration": "App.formatTimelineDuration",
        "renderTimelineTotal": "App.renderTimelineTotal",
        "timelineProjectScope": "App.timelineProjectScope",
        "timelineProjectLabel": "App.timelineProjectLabel",
        "filteredTimelineSessions": "App.filteredTimelineSessions",
        "renderTimelineProjectFilter": "App.renderTimelineProjectFilter",
        "renderSessionDetails": "App.renderSessionDetails",
        "openTimelineDrawer": "App.openTimelineDrawer",
        "closeTimelineDrawer": "App.closeTimelineDrawer",
        "closeTimelineAdvancedMenu": "App.closeTimelineAdvancedMenu",
        "dismissTimelineContextTransientUi": "App.dismissTimelineContextTransientUi",
        "resetTimelineTransientUi": "App.resetTimelineTransientUi",
        "clearEditPanel": "App.clearEditPanel",
        "populateEditPanel": "App.populateEditPanel",
        "isEditDirty": "App.isEditDirty",
        "showEditStatus": "App.showEditStatus",
        "setTimelineReadOnlyNotice": "App.timelineEditorState.setReadOnlyNotice",
        "applyEditCapabilities": "App.applyTimelineEditCapabilities",
        "normalizeTimelineDurationInput": "App.normalizeTimelineDurationInput",
        "setEditSaving": "App.setEditSaving",
        "scheduleTimelineAutosave": "App.scheduleTimelineAutosave",
        "cancelTimelineAutosaveTimer": "App.timelineEditorState.cancelAutosaveTimer",
        "canEditField": "App.timelineEditorState.canEditField",
        "findCachedProject": "App.timelineEditorState.findCachedProject",
        "updateFDWorkEntryButton": "App.updateFDWorkEntryButton",
        "showFDWorkStatus": "App.showFDWorkStatus",
    })

    old_reset = (
        "        activeFDWorkFillTransaction = null;\n"
        "        App.fdWorkOpenPromise = null;\n"
        "        App.fdWorkStatusOverride = null;\n"
    )
    if old_reset not in source:
        raise AssertionError("FD Work reset boundary changed")
    source = source.replace(
        old_reset,
        "        if (App.resetTimelineFDWorkState) App.resetTimelineFDWorkState();\n",
        1,
    )

    # The coordinator must no longer contain the moved owners.
    forbidden = [
        "function exactRowClock",
        "function renderSessionDetails",
        "function openTimelineDrawer",
        "function closeTimelineAdvancedMenu",
        "function findCachedProject",
        "var fdWorkFillTransactionSequence",
    ]
    for token in forbidden:
        if token in source:
            raise AssertionError(f"moved ownership remains in timeline.js: {token}")

    TIMELINE.write_text(source, encoding="utf-8")
    (JS_DIR / "timeline_presentation.js").write_text(presentation, encoding="utf-8")
    (JS_DIR / "timeline_transient_ui.js").write_text(transient, encoding="utf-8")
    (JS_DIR / "timeline_editor_state.js").write_text(editor_state, encoding="utf-8")
    (JS_DIR / "timeline_fd_work.js").write_text(fd_work_module, encoding="utf-8")

    # Production load order: narrow owners before the coordinator.
    html = HTML.read_text(encoding="utf-8")
    needle = (
        '    <script src="js/timeline_request_state.js?v=def4153c593ccf91"></script>\n'
        '    <script src="js/timeline.js?v=031f77237ebef914"></script>'
    )
    if needle not in html:
        # Hashes can change; match by filenames instead.
        pattern = re.compile(
            r'(    <script src="js/timeline_request_state\.js\?v=[^"]+"></script>\n)'
            r'(    <script src="js/timeline\.js\?v=[^"]+"></script>)'
        )
        match = pattern.search(html)
        if not match:
            raise AssertionError("timeline script load order not found")
        replacement = (
            match.group(1)
            + '    <script src="js/timeline_presentation.js?v=governance"></script>\n'
            + '    <script src="js/timeline_transient_ui.js?v=governance"></script>\n'
            + '    <script src="js/timeline_editor_state.js?v=governance"></script>\n'
            + '    <script src="js/timeline_fd_work.js?v=governance"></script>\n'
            + match.group(2)
        )
        html = html[:match.start()] + replacement + html[match.end():]
    else:
        html = html.replace(
            needle,
            needle.splitlines()[0] + "\n"
            + '    <script src="js/timeline_presentation.js?v=governance"></script>\n'
            + '    <script src="js/timeline_transient_ui.js?v=governance"></script>\n'
            + '    <script src="js/timeline_editor_state.js?v=governance"></script>\n'
            + '    <script src="js/timeline_fd_work.js?v=governance"></script>\n'
            + needle.splitlines()[1],
            1,
        )
    HTML.write_text(html, encoding="utf-8")

    spec = SPEC.read_text(encoding="utf-8")
    spec_line = "    (str(root / 'worktrace' / 'webview_ui' / 'js' / 'timeline.js'), 'worktrace/webview_ui/js'),\n"
    if spec_line not in spec:
        raise AssertionError("timeline.js packaging entry not found")
    additions = "".join(
        f"    (str(root / 'worktrace' / 'webview_ui' / 'js' / '{name}'), 'worktrace/webview_ui/js'),\n"
        for name in (
            "timeline_presentation.js",
            "timeline_transient_ui.js",
            "timeline_editor_state.js",
            "timeline_fd_work.js",
        )
    )
    spec = spec.replace(spec_line, additions + spec_line, 1)
    SPEC.write_text(spec, encoding="utf-8")

    # Static contract tests should treat the Timeline frontend as a module set,
    # while retaining assertions about semantic ownership.
    static_test = STATIC_TEST.read_text(encoding="utf-8")
    static_test = static_test.replace('_source("timeline.js")', '_timeline_source()')
    helper_anchor = "def _resource(name: str) -> str:\n    return (ROOT / \"worktrace\" / \"webview_ui\" / name).read_text(encoding=\"utf-8\")\n\n\n"
    if helper_anchor not in static_test:
        raise AssertionError("timeline static test helper anchor changed")
    helper = (
        helper_anchor
        + "TIMELINE_MODULES = (\n"
        + "    \"timeline_presentation.js\",\n"
        + "    \"timeline_transient_ui.js\",\n"
        + "    \"timeline_editor_state.js\",\n"
        + "    \"timeline_fd_work.js\",\n"
        + "    \"timeline.js\",\n"
        + ")\n\n\n"
        + "def _timeline_source() -> str:\n"
        + "    return \"\\n\".join(_source(name) for name in TIMELINE_MODULES)\n\n\n"
    )
    static_test = static_test.replace(helper_anchor, helper, 1)
    STATIC_TEST.write_text(static_test, encoding="utf-8")

    # Node harnesses that load timeline.js directly need the same production
    # owner order. Keep this transformation generic for WebView tests.
    bundle_expression = (
        '["timeline_presentation.js", "timeline_transient_ui.js", '
        '"timeline_editor_state.js", "timeline_fd_work.js", "timeline.js"]'
        '.map((name) => fs.readFileSync(path.join(__dirname, '
        '"../../worktrace/webview_ui/js", name), "utf8")).join("\\n")'
    )
    direct_pattern = re.compile(
        r'fs\.readFileSync\(\s*path\.join\(\s*__dirname\s*,\s*'
        r'"\.\./\.\./worktrace/webview_ui/js/timeline\.js"\s*\)\s*,\s*"utf8"\s*\)'
    )
    for test_path in (ROOT / "tests" / "webview").glob("*.test.js"):
        text = test_path.read_text(encoding="utf-8")
        updated = direct_pattern.sub(bundle_expression, text)
        if updated != text:
            test_path.write_text(updated, encoding="utf-8")

    OWNERSHIP_TEST.write_text(
        "from __future__ import annotations\n\n"
        "from pathlib import Path\n\n"
        "ROOT = Path(__file__).resolve().parents[2]\n"
        "JS = ROOT / \"worktrace\" / \"webview_ui\" / \"js\"\n\n\n"
        "def read(name: str) -> str:\n"
        "    return (JS / name).read_text(encoding=\"utf-8\")\n\n\n"
        "def test_timeline_coordinator_does_not_reown_extracted_concerns():\n"
        "    coordinator = read(\"timeline.js\")\n"
        "    assert \"function exactRowClock\" not in coordinator\n"
        "    assert \"function renderSessionDetails\" not in coordinator\n"
        "    assert \"function openTimelineDrawer\" not in coordinator\n"
        "    assert \"function closeTimelineAdvancedMenu\" not in coordinator\n"
        "    assert \"function findCachedProject\" not in coordinator\n"
        "    assert \"var fdWorkFillTransactionSequence\" not in coordinator\n\n\n"
        "def test_timeline_owner_modules_are_narrow_and_explicit():\n"
        "    presentation = read(\"timeline_presentation.js\")\n"
        "    transient = read(\"timeline_transient_ui.js\")\n"
        "    editor = read(\"timeline_editor_state.js\")\n"
        "    fd_work = read(\"timeline_fd_work.js\")\n"
        "    assert \"App.timelinePresentation = Object.freeze\" in presentation\n"
        "    assert \"App.resetTimelineTransientUi = resetTimelineTransientUi\" in transient\n"
        "    assert \"App.timelineEditorState = Object.freeze\" in editor\n"
        "    assert \"App.resetTimelineFDWorkState\" in fd_work\n"
        "    assert \"timelineRequestState.nextMutationOwner\" not in presentation\n"
        "    assert \"timelineRequestState.nextMutationOwner\" not in transient\n"
        "    assert \"timelineRequestState.nextMutationOwner\" not in editor\n",
        encoding="utf-8",
    )

    print(f"timeline.js lines: {len(source.splitlines())}")
    for name in (
        "timeline_presentation.js",
        "timeline_transient_ui.js",
        "timeline_editor_state.js",
        "timeline_fd_work.js",
    ):
        text = (JS_DIR / name).read_text(encoding="utf-8")
        print(f"{name} lines: {len(text.splitlines())}")


if __name__ == "__main__":
    main()
