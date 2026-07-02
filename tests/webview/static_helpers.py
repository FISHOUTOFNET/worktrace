"""Shared helpers for the WebView static-contract test suite.

These tests read the bundled frontend resources (``index.html`` /
``js/*.js`` / ``styles.css``) directly without starting the GUI. The
constants and helpers here are intentionally lightweight so every themed
test module under ``tests/webview/`` can import the same paths without
re-declaring them.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEBVIEW_UI_DIR = REPO_ROOT / "worktrace" / "webview_ui"
JS_DIR = WEBVIEW_UI_DIR / "js"
HISTORY_PATH = REPO_ROOT / "docs" / "history" / "webview-phases.md"
RELEASE_VALIDATION_PATH = REPO_ROOT / "docs" / "release-validation.md"
README_PATH = REPO_ROOT / "README.md"

# JS modules in the exact load order used by index.html. read_all_js()
# concatenates them in this order so func_body() and substring checks
# see the same logical source the browser would execute.
#
# Project Rules logic is split across:
#   rules.js (core load / refresh / wiring)
#   rules_render.js (render helpers)
#   rules_rule_actions.js (rule toggle)
#   rules_keyword_actions.js (keyword create / edit / delete)
#   rules_folder_actions.js (folder create / edit / delete)
#   rules_project_actions.js (project lifecycle)
# ALL_JS_FILES is the single source of truth for both the static-contract
# tests and the packaging tests; do not hard-code the JS list elsewhere.
ALL_JS_FILES = [
    "core.js",
    "overview.js",
    "timeline.js",
    "timeline_correction.js",
    "statistics.js",
    "settings.js",
    "rules.js",
    "rules_render.js",
    "rules_rule_actions.js",
    "rules_keyword_actions.js",
    "rules_folder_actions.js",
    "rules_project_actions.js",
    "init.js",
]

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

# Bridge mixin files. ``bridge.py`` is a thin composition class that
# inherits from the mixins below; the method bodies live in those mixin
# files. The combined-source and per-method helpers let static source-level
# tests scan every bridge file without hard-coding which mixin holds each
# method.
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
    so function-body and substring contracts see the same logical source
    the browser would execute.
    """
    return "\n".join(read_js(name) for name in ALL_JS_FILES)


def read_rules_module_js() -> str:
    """Return the concatenated source of all Project Rules JS modules.

    Project Rules logic spans six IIFE modules loaded in order:
      rules.js                (core load / refresh / wiring)
      rules_render.js         (render helpers)
      rules_rule_actions.js  (rule toggle)
      rules_keyword_actions.js (keyword create / edit / delete)
      rules_folder_actions.js (folder create / edit / delete)
      rules_project_actions.js (project lifecycle: create / edit /
                                toggle / archive)
    Tests that need to check substring contracts or ``func_body`` across
    the full Project Rules surface should use this helper instead of
    ``read_js("rules.js")``.
    """
    names = [
        "rules.js",
        "rules_render.js",
        "rules_rule_actions.js",
        "rules_keyword_actions.js",
        "rules_folder_actions.js",
        "rules_project_actions.js",
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
    """Return the body slice of ``def <method_name>`` from whichever bridge
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
