from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise AssertionError(f"{path}: expected one replacement, found {count}: {old!r}")
    write(path, content.replace(old, new, 1))


def make_descriptor_invocation_lazy() -> None:
    path = "worktrace/webview_ui/js/timeline.js"
    mappings = {
        'hide: Object.freeze({ intent: "hide_timeline_session", invoke: App.bridge.hideTimelineSession })':
            'hide: Object.freeze({ intent: "hide_timeline_session", invoke: function () { return App.bridge.hideTimelineSession.apply(null, arguments); } })',
        'hideActivity: Object.freeze({ intent: "hide_timeline_session_activity", invoke: App.bridge.hideTimelineSessionActivity })':
            'hideActivity: Object.freeze({ intent: "hide_timeline_session_activity", invoke: function () { return App.bridge.hideTimelineSessionActivity.apply(null, arguments); } })',
        'merge: Object.freeze({ intent: "merge_timeline_session", invoke: App.bridge.mergeTimelineSession })':
            'merge: Object.freeze({ intent: "merge_timeline_session", invoke: function () { return App.bridge.mergeTimelineSession.apply(null, arguments); } })',
        'split: Object.freeze({ intent: "split_timeline_session", invoke: App.bridge.splitTimelineSession })':
            'split: Object.freeze({ intent: "split_timeline_session", invoke: function () { return App.bridge.splitTimelineSession.apply(null, arguments); } })',
        'copy: Object.freeze({ intent: "copy_timeline_session", invoke: App.bridge.copyTimelineSession })':
            'copy: Object.freeze({ intent: "copy_timeline_session", invoke: function () { return App.bridge.copyTimelineSession.apply(null, arguments); } })',
    }
    for old, new in mappings.items():
        replace_once(path, old, new)


def migrate_node_harness() -> None:
    path = "tests/webview/timeline_mutation_coordinator.test.js"
    bridge_mock = '''  const bridgeCall = (method) => (...args) => {
    const handler = context.window.WorkTraceApp.callBridge;
    if (typeof handler !== "function") return Promise.reject(new Error(`missing bridge handler: ${method}`));
    return handler(method, ...args);
  };
  context.window.WorkTraceApp.bridge = {
    getTimeline: bridgeCall("get_timeline"),
    getTimelineSessionActivitySummary: bridgeCall("get_timeline_session_activity_summary"),
    listProjectsForTimeline: bridgeCall("list_projects_for_timeline"),
    saveTimelineSessionEdit: bridgeCall("save_timeline_session_edit"),
    hideTimelineSession: bridgeCall("hide_timeline_session"),
    hideTimelineSessionActivity: bridgeCall("hide_timeline_session_activity"),
    mergeTimelineSession: bridgeCall("merge_timeline_session"),
    splitTimelineSession: bridgeCall("split_timeline_session"),
    copyTimelineSession: bridgeCall("copy_timeline_session"),
  };
'''
    replace_once(
        path,
        "  vm.createContext(context);\n",
        "  vm.createContext(context);\n" + bridge_mock,
    )

    content = read(path)
    replacements = {
        'App.runTimelineSessionOperation("copy_timeline_session")': 'App.runTimelineSessionOperation("copy")',
        'App.runTimelineSessionOperation("hide_timeline_session")': 'App.runTimelineSessionOperation("hide")',
        '["copy_timeline_session", {}, "copy:12"]': '["copy", {}, "copy:12"]',
        '["merge_timeline_session", { direction: "next" }, "merge:13"]': '["merge", { direction: "next" }, "merge:13"]',
        'for (const method of ["hide_timeline_session", "split_timeline_session"])': 'for (const method of ["hide", "split"])',
    }
    for old, new in replacements.items():
        count = content.count(old)
        if count < 1:
            raise AssertionError(f"{path}: operation key target missing: {old!r}")
        content = content.replace(old, new)
    write(path, content)


def main() -> None:
    make_descriptor_invocation_lazy()
    migrate_node_harness()


if __name__ == "__main__":
    main()
