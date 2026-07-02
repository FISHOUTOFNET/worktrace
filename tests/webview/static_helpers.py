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
    parsed from ``index.html`` so function-body and substring contracts
    see the same logical source the browser would execute.
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
