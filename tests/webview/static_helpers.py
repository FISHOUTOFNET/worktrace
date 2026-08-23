"""Shared helpers for the WebView static-contract test suite.

These tests read the bundled frontend resources directly without starting the
GUI. The JS load list is parsed from the shipping index so contract tests always
reflect the real resource set and load order.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEBVIEW_UI_DIR = REPO_ROOT / "worktrace" / "webview_ui"
JS_DIR = WEBVIEW_UI_DIR / "js"
HISTORY_PATH = REPO_ROOT / "docs" / "history" / "webview-phases.md"
RELEASE_VALIDATION_PATH = REPO_ROOT / "docs" / "release-validation.md"
README_PATH = REPO_ROOT / "README.md"

_SCRIPT_SRC_RE = re.compile(
    r'<script\s+src="js/([^"]+\.js)(?:\?v=[0-9a-f]+)?"\s*>\s*</script>'
)


def _parse_js_load_order_from_index() -> list[str]:
    index_path = WEBVIEW_UI_DIR / "index_fd_work_v5.html"
    source = index_path.read_text(encoding="utf-8")
    return _SCRIPT_SRC_RE.findall(source)


ALL_JS_FILES: list[str] = _parse_js_load_order_from_index()

FRONTEND_RESOURCE_FILES = (
    ["index_fd_work_v5.html", "styles.css", "ui_components.css"]
    + ["js/" + name for name in ALL_JS_FILES]
)
NO_STORAGE_FILES = (
    ["index_fd_work_v5.html"]
    + ["js/" + name for name in ALL_JS_FILES]
)

BRIDGE_FILES = [
    "bridge.py",
    "bridge_common.py",
    "bridge_dialogs.py",
    "bridge_fd_work.py",
    "bridge_overview.py",
    "bridge_projects.py",
    "bridge_settings.py",
    "bridge_statistics.py",
    "bridge_timeline.py",
    "bridge_rules.py",
]


def read_resource(filename: str) -> str:
    return (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")


def read_js(filename: str) -> str:
    return (JS_DIR / filename).read_text(encoding="utf-8")


def read_all_js() -> str:
    return "\n".join(read_js(name) for name in ALL_JS_FILES)


def read_rules_module_js() -> str:
    """Return Project Rules sources in shipping ownership order."""
    names = [
        "rules.js",
        "rules_render.js",
        "rules_create_panel_v5.js",
        "rules_rule_actions.js",
        "rules_delete_actions.js",
    ]
    parts: list[str] = []
    for name in names:
        path = JS_DIR / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def func_body(source: str, name: str) -> str:
    start = source.find("function " + name)
    assert start != -1, "js must define " + name
    end_func = source.find("\n    function ", start + 1)
    end_iife = source.find("\n})();", start + 1)
    candidates = [e for e in (end_func, end_iife) if e != -1]
    end = min(candidates) if candidates else -1
    return source[start:end] if end != -1 else source[start:]


def html_section_by_id(source: str, section_id: str) -> str:
    marker = 'id="' + section_id + '"'
    pos = source.find(marker)
    assert pos != -1, "html must define section id: " + section_id
    end = source.find("</section>", pos)
    assert end != -1, "html section must close after id: " + section_id
    return source[pos:end]


def html_element_by_id(source: str, element_id: str) -> str:
    marker = 'id="' + element_id + '"'
    pos = source.find(marker)
    assert pos != -1, "html must define element id: " + element_id
    tag_start = source.rfind("<", 0, pos)
    assert tag_start != -1, "element must have a well-formed opening tag: " + element_id
    tag_match = re.match(r"<(\w+)", source[tag_start:])
    assert tag_match, "element must have a valid tag name: " + element_id
    tag_name = tag_match.group(1)
    open_tag_end = source.find(">", pos)
    assert open_tag_end != -1, "element opening tag must close: " + element_id
    if source[open_tag_end - 1] == "/":
        return source[tag_start:open_tag_end + 1]
    close_tag = "</" + tag_name + ">"
    search_pos = open_tag_end + 1
    depth = 1
    while depth > 0:
        next_open = source.find("<" + tag_name, search_pos)
        next_close = source.find(close_tag, search_pos)
        if next_close == -1:
            raise AssertionError(
                "element " + repr(element_id)
                + " (<" + tag_name + ">) has no matching closing tag"
            )
        if next_open != -1 and next_open < next_close:
            depth += 1
            search_pos = next_open + len("<" + tag_name)
        else:
            depth -= 1
            search_pos = next_close + len(close_tag)
    return source[tag_start:search_pos]


def html_opening_tag_by_id(source: str, element_id: str) -> str:
    marker = 'id="' + element_id + '"'
    pos = source.find(marker)
    assert pos != -1, "html must define element id: " + element_id
    tag_start = source.rfind("<", 0, pos)
    assert tag_start != -1, "element must have a well-formed opening tag: " + element_id
    tag_end = source.find(">", pos)
    assert tag_end != -1, "element opening tag must close: " + element_id
    return source[tag_start:tag_end + 1]


def js_catch_block(func_source: str) -> str:
    catch_pos = func_source.find(".catch(function")
    if catch_pos == -1:
        return ""
    brace_start = func_source.find("{", catch_pos)
    assert brace_start != -1, "catch callback must open with {"
    depth = 1
    pos = brace_start + 1
    while depth > 0:
        next_open = func_source.find("{", pos)
        next_close = func_source.find("}", pos)
        if next_close == -1:
            raise AssertionError("catch block has no matching closing brace")
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 1
        else:
            depth -= 1
            pos = next_close + 1
    paren_close = func_source.find(")", pos)
    end = paren_close + 1 if paren_close != -1 else pos
    return func_source[catch_pos:end]


def python_method_body(source: str, method_name: str) -> str:
    marker = "def " + method_name
    start = source.find(marker)
    assert start != -1, "python source must define method: " + method_name
    next_def = source.find("\n    def ", start + 1)
    next_class = source.find("\nclass ", start + 1)
    next_top_def = source.find("\ndef ", start + 1)
    candidates = [e for e in (next_def, next_class, next_top_def) if e != -1]
    end = min(candidates) if candidates else -1
    return source[start:end] if end != -1 else source[start:]


def read_bridge_sources_combined() -> str:
    parts: list[str] = []
    for name in BRIDGE_FILES:
        path = WEBVIEW_UI_DIR / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def read_bridge_method_body(method_name: str, *, max_chars: int = 4000) -> str:
    for name in BRIDGE_FILES:
        path = WEBVIEW_UI_DIR / name
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        pos = source.find("def " + method_name)
        if pos == -1:
            continue
        next_def = source.find("\n    def ", pos + 1)
        end = next_def if next_def != -1 else pos + max_chars
        return source[pos:end]
    raise AssertionError(
        "method " + repr(method_name) + " not found in any bridge file: "
        + ", ".join(BRIDGE_FILES)
    )
