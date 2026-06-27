"""Shared helpers for the WebView static-contract test suite.

These tests read the bundled frontend resources (``index.html`` / ``app.js`` /
``styles.css``) directly without starting the GUI. The constants and helpers
here are intentionally lightweight so every themed test module under
``tests/webview/`` can import the same paths without re-declaring them.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEBVIEW_UI_DIR = REPO_ROOT / "worktrace" / "webview_ui"
HISTORY_PATH = REPO_ROOT / "docs" / "history" / "webview-phases.md"
RELEASE_VALIDATION_PATH = REPO_ROOT / "docs" / "release-validation.md"
README_PATH = REPO_ROOT / "README.md"

FRONTEND_RESOURCE_FILES = ["index.html", "app.js", "styles.css"]
NO_STORAGE_FILES = ["index.html", "app.js"]


def read_resource(filename: str) -> str:
    """Return the UTF-8 text of a bundled ``webview_ui`` resource."""
    return (WEBVIEW_UI_DIR / filename).read_text(encoding="utf-8")


def func_body(source: str, name: str) -> str:
    """Return the body of ``function <name>`` in app.js (best-effort)."""
    start = source.find("function " + name)
    assert start != -1, "app.js must define " + name
    end = source.find("\n    function ", start + 1)
    return source[start:end] if end != -1 else source[start:]
