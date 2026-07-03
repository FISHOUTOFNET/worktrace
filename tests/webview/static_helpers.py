"""Shared helpers for the WebView static-contract test suite.

These tests read the bundled frontend resources (``index.html`` /
``js/*.js`` / ``styles.css``) directly without starting the GUI. The
constants and helpers here are intentionally lightweight so every themed
test module under ``tests/webview/`` can import the same paths without
re-declaring them.

The JS load list is parsed from ``index.html``'s ``<script src="js/...">``
tags so the tests always reflect the real resource set the browser
executes. A new JS file added under ``js/`` MUST be referenced by
``index.html`` or the orphan/missing contract tests fail.
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

# Regex matching ``<script src="js/<name>.js"></script>`` tags so the JS
# load list is parsed from the real ``index.html`` instead of being
# hand-maintained. The capture group extracts the filename without the
# ``js/`` prefix.
_SCRIPT_SRC_RE = re.compile(r'<script\s+src="js/([^"]+\.js)"\s*>\s*</script>')


def _parse_js_load_order_from_index() -> list[str]:
    """Return the JS filenames in the order ``index.html`` loads them.

    Parses every ``<script src="js/<name>.js">`` tag from
    ``worktrace/webview_ui/index.html``. The returned list is the single
    source of truth for the JS resource set and load order; tests that
    need the JS list must use this function (or the ``ALL_JS_FILES``
    constant derived from it) so an orphan / missing JS file fails the
    contract tests instead of being silently skipped.
    """
    index_path = WEBVIEW_UI_DIR / "index.html"
    source = index_path.read_text(encoding="utf-8")
    return _SCRIPT_SRC_RE.findall(source)


# Parsed once at import time so every test module sees the same list.
ALL_JS_FILES: list[str] = _parse_js_load_order_from_index()

# Frontend resource files scanned by the parametrized global-boundary
# tests (no external links / CDN / Google Fonts / localStorage /
# traceback text). JS modules are listed with their js/ prefix so
# read_resource() resolves them via WEBVIEW_UI_DIR.
FRONTEND_RESOURCE_FILES = (
    ["index.html", "styles.css"]
    + ["js/" + name for name in ALL_JS_FILES]
)
NO_STORAGE_FILES = (
    ["index.html"]
    + ["js/" + name for name in ALL_JS_FILES]
)

# Bridge mixin files: ``bridge.py`` is a thin composition class; method
# bodies live in the mixins so combined-source helpers scan every file.
BRIDGE_FILES = [
    "bridge.py",
    "bridge_common.py",
    "bridge_dialogs.py",
    "bridge_overview.py",
    "bridge_settings.py",
    "bridge_statistics.py",
    "bridge_timeline.py",
    "bridge_rules.py",
]


def read_resource(filename: str) -> str:
    """Return the UTF-8 text of a bundled ``webview_ui`` resource.

    Accepts top-level files (``index.html``, ``styles.css``) and js/
    module paths (``js/core.js``).
    """
    return (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")


def read_js(filename: str) -> str:
    """Return the UTF-8 text of a single ``js/`` module."""
    return (JS_DIR / filename).read_text(encoding="utf-8")


def read_all_js() -> str:
    """Return the concatenated UTF-8 text of every ``js/`` module in load order.

    Concatenation preserves the IIFE-per-module structure and load order
    parsed from ``index.html`` so function-body and substring contracts
    see the same logical source the browser would execute.
    """
    return "\n".join(read_js(name) for name in ALL_JS_FILES)


def read_rules_module_js() -> str:
    """Return the concatenated source of all Project Rules JS modules.

    Project Rules logic spans six IIFE modules loaded in order:
      rules.js                (core load / refresh / wiring)
      rules_render.js         (render helpers)
      rules_create_panel.js   (unified create/edit panel + advanced
                                excluded-rules panel)
      rules_rule_actions.js   (created-rule backfill helper)
      rules_keyword_actions.js (keyword rule delete)
      rules_folder_actions.js (folder rule delete)
    Tests that need to check substring contracts or ``func_body`` across
    the full Project Rules surface should use this helper instead of
    ``read_js("rules.js")``.
    """
    names = [
        "rules.js",
        "rules_render.js",
        "rules_create_panel.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
    ]
    parts: list[str] = []
    for name in names:
        path = JS_DIR / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def func_body(source: str, name: str) -> str:
    """Return the body of ``function <name>`` (best-effort).

    Searches the concatenated js source for ``function <name>`` and
    returns the text up to the next sibling function declaration or the
    enclosing IIFE close (``})();``), whichever comes first. The
    IIFE-close fallback bounds the last function in each module so
    concatenation does not leak the next module's header into the
    returned body.
    """
    start = source.find("function " + name)
    assert start != -1, "js must define " + name
    end_func = source.find("\n    function ", start + 1)
    end_iife = source.find("\n})();", start + 1)
    candidates = [e for e in (end_func, end_iife) if e != -1]
    end = min(candidates) if candidates else -1
    return source[start:end] if end != -1 else source[start:]


def html_section_by_id(source: str, section_id: str) -> str:
    """Return the ``<section id="<section_id>">`` block from HTML source.

    Bounds the slice to the real ``</section>`` close so the section-level
    contract tests never scan adjacent sections. Raises ``AssertionError``
    when the section id or its closing ``</section>`` tag is missing so a
    malformed/renamed section fails loudly instead of silently scanning
    adjacent DOM.

    Used in place of fixed ``source[pos:pos + N]`` windows so a section
    test cannot bleed into the next section even when comments shrink or
    grow.
    """
    marker = 'id="' + section_id + '"'
    pos = source.find(marker)
    assert pos != -1, "html must define section id: " + section_id
    end = source.find("</section>", pos)
    assert end != -1, "html section must close after id: " + section_id
    return source[pos:end]


def html_element_by_id(source: str, element_id: str) -> str:
    """Return the full HTML element (opening tag + content + closing tag)
    for the element with ``id="<element_id>"``.

    Locates the opening tag by searching backwards from the id marker for
    the preceding ``<``, extracts the tag name, then walks forward counting
    nested open/close tags of the same name to find the matching closing
    tag. This avoids fixed character windows that could bleed into adjacent
    DOM when comments shrink or grow.

    Raises ``AssertionError`` when the id, the opening tag, or the matching
    closing tag cannot be found.
    """
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
    # Self-closing tag (e.g. <input id="..." />)
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
    """Return just the opening HTML tag for the element with
    ``id="<element_id>"``.

    Bounds the slice from the preceding ``<`` to the closing ``>`` of the
    opening tag so attribute checks (e.g. ``hidden``) never scan adjacent
    DOM.
    """
    marker = 'id="' + element_id + '"'
    pos = source.find(marker)
    assert pos != -1, "html must define element id: " + element_id
    tag_start = source.rfind("<", 0, pos)
    assert tag_start != -1, "element must have a well-formed opening tag: " + element_id
    tag_end = source.find(">", pos)
    assert tag_end != -1, "element opening tag must close: " + element_id
    return source[tag_start:tag_end + 1]


def js_catch_block(func_source: str) -> str:
    """Return the ``.catch(function () { ... })`` block from a JS function
    body.

    Finds the first ``.catch(function`` in *func_source* and returns the text
    up to the matching ``});`` close. Uses brace counting so nested
    callbacks inside the catch do not produce a false-short slice.

    Returns an empty string when no ``.catch(function`` is found, so callers
    can ``if catch_body:`` to guard assertions.
    """
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
    # Include the trailing ``);`` that closes the .catch() call.
    paren_close = func_source.find(")", pos)
    if paren_close != -1:
        end = paren_close + 1
    else:
        end = pos
    return func_source[catch_pos:end]


def python_method_body(source: str, method_name: str) -> str:
    """Return the body of ``def <method_name>`` from Python source.

    Locates ``def <method_name>`` and returns the text up to the next
    ``\\n    def `` at the same indentation (or the next ``\\nclass `` /
    EOF). This avoids fixed character windows when a test needs to check
    a single Python method body.
    """
    marker = "def " + method_name
    start = source.find(marker)
    assert start != -1, "python source must define method: " + method_name
    # Find the end: next ``\n    def `` or ``\nclass `` or ``\ndef ``.
    next_def = source.find("\n    def ", start + 1)
    next_class = source.find("\nclass ", start + 1)
    next_top_def = source.find("\ndef ", start + 1)
    candidates = [e for e in (next_def, next_class, next_top_def) if e != -1]
    end = min(candidates) if candidates else -1
    return source[start:end] if end != -1 else source[start:]


def read_bridge_sources_combined() -> str:
    """Return the concatenated UTF-8 source of all bridge mixin files.

    Tests that need substring checks (e.g. ``assert "def foo" in src`` or
    ``assert "from ..services" not in src``) should use this helper so
    the checks scan every bridge file instead of just the slim
    composition class.
    """
    parts: list[str] = []
    for name in BRIDGE_FILES:
        path = WEBVIEW_UI_DIR / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def read_bridge_method_body(method_name: str, *, max_chars: int = 4000) -> str:
    """Return the body slice of ``def <method_name>`` from whichever mixin
    mixin file defines it.

    Returns the slice from ``def <method_name>`` up to the next
    ``\\n    def `` at indent 4 (or ``max_chars`` characters if no next
    method is found). Raises ``AssertionError`` if the method is not
    found in any bridge file.
    """
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
