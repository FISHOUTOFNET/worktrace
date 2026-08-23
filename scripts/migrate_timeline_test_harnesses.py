from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEBVIEW = ROOT / "tests" / "webview"

IMPORT = 'const { TIMELINE_MODULES, loadTimelineModules } = require("./timeline_test_modules");\n'
VM_IMPORT = 'const vm = require("node:vm");\n'


def read(name: str) -> str:
    return (WEBVIEW / name).read_text(encoding="utf-8")


def write(name: str, text: str) -> None:
    (WEBVIEW / name).write_text(text, encoding="utf-8")


def add_import(text: str) -> str:
    if IMPORT in text:
        return text
    if VM_IMPORT not in text:
        raise AssertionError("node vm import anchor missing")
    return text.replace(VM_IMPORT, VM_IMPORT + IMPORT, 1)


def replace_once(text: str, old: str, new: str, *, name: str) -> str:
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"{name}: expected one occurrence, found {count}: {old!r}")
    return text.replace(old, new, 1)


def migrate_fd_loop(name: str) -> None:
    text = add_import(read(name))
    text = replace_once(
        text,
        'for (const file of ["fd_work_v5.js", "timeline.js", "ui_composition.js"]) {',
        'for (const file of ["fd_work_v5.js", ...TIMELINE_MODULES, "ui_composition.js"]) {',
        name=name,
    )
    write(name, text)


def migrate() -> None:
    for name in (
        "fd_work_fill_terminal_race.test.js",
        "fd_work_terminal_ui_contract.test.js",
    ):
        migrate_fd_loop(name)

    name = "fd_work_session_entry_policy.test.js"
    text = add_import(read(name))
    text = replace_once(
        text,
        '  vm.runInContext(source("timeline.js"), context, { filename: "timeline.js" });',
        '  loadTimelineModules(context, __dirname);',
        name=name,
    )
    write(name, text)

    name = "page_transient_state.test.js"
    text = add_import(read(name))
    text = replace_once(
        text,
        '  timeline.load("timeline.js");',
        '  for (const file of TIMELINE_MODULES) timeline.load(file);',
        name=name,
    )
    write(name, text)

    name = "timeline_mutation_coordinator.test.js"
    text = add_import(read(name))
    text = replace_once(
        text,
        'for (const file of ["timeline_request_state.js", "timeline.js"]) {',
        'for (const file of ["timeline_request_state.js", ...TIMELINE_MODULES]) {',
        name=name,
    )
    write(name, text)

    name = "transient_context_lifecycle.test.js"
    text = add_import(read(name))
    text = replace_once(
        text,
        '  h.load("timeline.js");',
        '  for (const file of TIMELINE_MODULES) h.load(file);',
        name=name,
    )
    write(name, text)

    name = "ui_redesign_behavior.test.js"
    text = add_import(read(name))
    text = replace_once(
        text,
        '  for (const file of ["timeline_request_state.js", "timeline.js"]) loadJs(context, file);',
        '  for (const file of ["timeline_request_state.js", ...TIMELINE_MODULES]) loadJs(context, file);',
        name=name,
    )
    write(name, text)

    for name in (
        "timeline_project_scope.test.js",
        "timeline_refresh_ownership.test.js",
    ):
        text = add_import(read(name))
        start = text.index("  vm.runInContext(\n", text.index("vm.createContext(context);"))
        end_marker = '  );\n'
        end = text.index(end_marker, start) + len(end_marker)
        old = text[start:end]
        if "timeline_presentation.js" not in old or 'filename: "timeline.js"' not in old:
            raise AssertionError(f"{name}: combined timeline source block changed")
        text = text[:start] + "  loadTimelineModules(context, __dirname);\n" + text[end:]
        write(name, text)

    ownership = WEBVIEW / "test_timeline_module_ownership.py"
    text = ownership.read_text(encoding="utf-8")
    anchor = '    assert "App.timelinePresentation = Object.freeze" in presentation\n'
    assertion = '    assert "App.renderTimelineTotal = renderTimelineTotal" in presentation\n'
    if assertion not in text:
        if anchor not in text:
            raise AssertionError("timeline ownership assertion anchor changed")
        text = text.replace(anchor, anchor + assertion, 1)
        ownership.write_text(text, encoding="utf-8")

    print("migrated timeline Node harnesses to production owner order")


if __name__ == "__main__":
    migrate()
