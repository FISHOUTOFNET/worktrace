"""packaging, default WebView entry, and WebView2 runtime detection tests.

WebView is the default and only shipping UI. These tests
cover:

- WorkTrace.spec bundles webview_ui static resources + retains schema.sql,
  open_files_helper, customtkinter, win32timezone;
- pyinstaller_entry.py forwards to worktrace.main.main (which now defaults
  to WebView);
- ``python -m worktrace.main`` defaults to the WebView entry point and does
  not instantiate the Tkinter ``WorkTraceApp``;
- importing worktrace.main does not start the GUI;
- WebView2 runtime_check is importable, never raises, and does not block
  non-Windows;
- the missing-runtime message does not mention Tkinter, fallback, or any
  ``继续使用默认`` wording;
- boundary: runtime_check stays inside webview_ui and does not import backend.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.webview.static_helpers import ALL_JS_FILES

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "WorkTrace.spec"
INDEX_HTML_PATH = REPO_ROOT / "worktrace" / "webview_ui" / "index.html"
ENTRY_PATH = REPO_ROOT / "scripts" / "pyinstaller_entry.py"
MAIN_PATH = REPO_ROOT / "worktrace" / "main.py"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file: {path}"
    return path.read_text(encoding="utf-8")


# --- packaging resource tests -------------------------------------------


def test_spec_bundles_webview_ui_static_resources():
    """the spec must bundle index.html, styles.css, and every
    ``js/`` module listed in ``static_helpers.ALL_JS_FILES`` (the single
    source of truth). frontend JS must no longer be
    referenced since the file was removed."""
    spec = _read(SPEC_PATH)
    for name in ("index.html", "styles.css"):
        assert name in spec, f"WorkTrace.spec must bundle webview_ui/{name}"
    # every JS module in ALL_JS_FILES must be bundled.
    for name in ALL_JS_FILES:
        assert name in spec, f"WorkTrace.spec must bundle webview_ui/js/{name}"
    # The removed frontend JS must no longer be referenced.
    assert "app.js" not in spec, (
        "WorkTrace.spec must not reference the removed monolithic frontend bundle"
    )


def test_index_html_loads_all_js_in_order():
    """index.html must load every file in ``ALL_JS_FILES`` and in
    the exact same order. This guards against a new JS module being added
    to ``ALL_JS_FILES`` without being wired into ``index.html`` (or vice
    versa)."""
    html = _read(INDEX_HTML_PATH)
    # Collect every <script src="js/..."> tag in document order.
    import re

    scripts = re.findall(r'<script\s+src="js/([^"]+)"\s*>\s*</script>', html)
    assert scripts, "expected at least one <script src=js/...> tag in index.html"
    assert scripts == ALL_JS_FILES, (
        "index.html script order must match ALL_JS_FILES exactly; "
        f"got {scripts}"
    )


def test_all_js_files_exist_on_disk():
    """every entry in ``ALL_JS_FILES`` must resolve to an actual
    JS module on disk so the static-contract tests and PyInstaller spec
    never silently reference a missing file."""
    js_dir = REPO_ROOT / "worktrace" / "webview_ui" / "js"
    for name in ALL_JS_FILES:
        path = js_dir / name
        assert path.is_file(), f"missing JS module: {path}"


def test_spec_bundles_webview_resources_under_webview_ui_dir():
    spec = _read(SPEC_PATH)
    assert "webview_ui" in spec


def test_spec_collects_pywebview():
    spec = _read(SPEC_PATH)
    assert "collect_all('webview')" in spec or 'collect_all("webview")' in spec


def test_spec_retains_schema_sql():
    spec = _read(SPEC_PATH)
    assert "schema.sql" in spec


def test_spec_retains_open_files_helper():
    spec = _read(SPEC_PATH)
    assert "open_files_helper.py" in spec


def test_spec_does_not_bundle_customtkinter():
    """customtkinter must NOT be bundled: the worktrace.ui package was
    removed and no production code imports customtkinter."""
    spec = _read(SPEC_PATH)
    assert "customtkinter" not in spec


def test_spec_retains_win32timezone():
    spec = _read(SPEC_PATH)
    assert "win32timezone" in spec


def test_entry_script_forwards_to_worktrace_main():
    """The entry script must fall through to worktrace.main.main for the
    default invocation. WebView is the default and only UI."""
    source = _read(ENTRY_PATH)
    assert "--open-files-helper" in source
    assert "from worktrace.main import main" in source


# --- startup tests ------------------------------------------------------


def test_main_module_does_not_import_worktrace_app():
    """main.py must not import or instantiate the Tkinter WorkTraceApp.

    The default path is the WebView UI. The
    ``worktrace.ui`` package has been deleted entirely, so the default entry point
    must not depend on it (and no such module exists to import).
    """
    source = _read(MAIN_PATH)
    assert "WorkTraceApp" not in source, (
        "worktrace.main must not import or reference WorkTraceApp; "
        "WebView is the default UI as of WebView UI."
    )
    assert "from .ui.app" not in source
    assert "from worktrace.ui.app" not in source


def test_main_defaults_to_webview_without_flag():
    """``main([])`` must delegate to ``webview_main.main()``.

    This is the core invariant: the default entry point starts the
    WebView UI. There is no Tkinter path in ``main``.
    """
    import worktrace.main as main_mod

    called = {"count": 0}

    def fake_webview_main():
        called["count"] += 1
        return 0

    with patch("worktrace.webview_main.main", fake_webview_main):
        result = main_mod.main([])
    assert result == 0
    assert called["count"] == 1


def test_main_ignores_extra_args():
    """``main`` must ignore any command-line args and always delegate to
    ``webview_main.main()``. WebView is the only UI; there is no argparse
    layer and no flag parsing."""
    import worktrace.main as main_mod

    called = {"count": 0}

    def fake_webview_main():
        called["count"] += 1
        return 0

    with patch("worktrace.webview_main.main", fake_webview_main):
        result = main_mod.main(["--unknown-arg"])
    assert result == 0
    assert called["count"] == 1


def test_main_does_not_instantiate_worktrace_app_on_default_path():
    """The default ``main([])`` path must not instantiate WorkTraceApp.

    Even if webview_main raises, the main module must not catch the error and
    instantiate the Tkinter UI as a fallback. We assert that WorkTraceApp is
    never imported by main.py (covered by
    ``test_main_module_does_not_import_worktrace_app``) and that main()
    returns whatever webview_main returns, including non-zero codes.
    """
    import worktrace.main as main_mod

    def fake_webview_main_returning_nonzero():
        return 2

    with patch("worktrace.webview_main.main", fake_webview_main_returning_nonzero):
        result = main_mod.main([])
    assert result == 2


def test_main_propagates_webview_failure_without_tkinter_fallback(monkeypatch):
    """If webview_main.main raises, main() must propagate the exception
    instead of catching it and starting a Tkinter UI."""
    import worktrace.main as main_mod

    def boom():
        raise RuntimeError("webview failed to start")

    monkeypatch.setattr("worktrace.webview_main.main", boom)
    with pytest.raises(RuntimeError, match="webview failed to start"):
        main_mod.main([])


def test_import_main_does_not_start_gui():
    code = """
import json
import sys

import worktrace.main

print(json.dumps({"started": False}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    # If import started the GUI, this subprocess would hang / fail.
    assert result.returncode == 0


def test_import_webview_main_does_not_start_gui():
    code = """
import json
import sys

import worktrace.webview_main

print(json.dumps({"started": False, "has_main": hasattr(worktrace.webview_main, "main")}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    loaded = json.loads(result.stdout)
    assert loaded["has_main"] is True


# --- WebView2 runtime detection tests -----------------------------------


def test_runtime_check_module_importable():
    from worktrace.webview_ui import runtime_check

    assert hasattr(runtime_check, "detect_webview2_runtime")
    assert hasattr(runtime_check, "is_webview2_available")
    assert hasattr(runtime_check, "missing_runtime_message")


def test_detect_webview2_runtime_returns_known_status():
    from worktrace.webview_ui.runtime_check import detect_webview2_runtime

    status = detect_webview2_runtime()
    assert status in ("installed", "missing", "unknown")


def test_detect_webview2_runtime_non_windows_returns_unknown():
    """On non-Windows the check must not block; returns unknown."""
    from worktrace.webview_ui.runtime_check import detect_webview2_runtime

    fake_platform = "linux"
    with patch("worktrace.webview_ui.runtime_check.sys") as fake_sys:
        fake_sys.platform = fake_platform
        status = detect_webview2_runtime()
    assert status == "unknown"


def test_detect_webview2_runtime_never_raises_on_windows():
    """Even if winreg raises, the function must return unknown, not raise."""
    from worktrace.webview_ui.runtime_check import detect_webview2_runtime

    with patch("worktrace.webview_ui.runtime_check.sys") as fake_sys:
        fake_sys.platform = "win32"
        # Force the winreg import inside the function to raise.
        with patch.dict("sys.modules", {"winreg": None}):
            status = detect_webview2_runtime()
    assert status == "unknown"


def test_is_webview2_available_treats_unknown_as_available():
    from worktrace.webview_ui.runtime_check import is_webview2_available

    with patch(
        "worktrace.webview_ui.runtime_check.detect_webview2_runtime",
        return_value="unknown",
    ):
        assert is_webview2_available() is True


def test_is_webview2_available_treats_missing_as_unavailable():
    from worktrace.webview_ui.runtime_check import is_webview2_available

    with patch(
        "worktrace.webview_ui.runtime_check.detect_webview2_runtime",
        return_value="missing",
    ):
        assert is_webview2_available() is False


def test_missing_runtime_message_mentions_webview2():
    from worktrace.webview_ui.runtime_check import missing_runtime_message

    msg = missing_runtime_message()
    assert "WebView2" in msg
    assert "Microsoft" in msg


def test_missing_runtime_message_has_no_tkinter_or_fallback_wording():
    """The missing-runtime message must not reference Tkinter, fallback, or
    any ``继续使用默认`` wording. The fallback path has been removed."""
    from worktrace.webview_ui.runtime_check import missing_runtime_message

    msg = missing_runtime_message()
    msg_lower = msg.lower()
    assert "tkinter" not in msg_lower
    assert "fallback" not in msg_lower
    assert "继续使用默认" not in msg


def test_runtime_check_does_not_import_backend():
    """runtime_check must not import services/db/collector/security."""
    source = (REPO_ROOT / "worktrace" / "webview_ui" / "runtime_check.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "from ..services",
        "from worktrace.services",
        "from ..db",
        "from worktrace.db",
        "from ..collector",
        "from worktrace.collector",
        "from ..security",
        "from worktrace.security",
        "import worktrace.services",
        "import worktrace.db",
        "import worktrace.collector",
        "import worktrace.security",
    ):
        assert forbidden not in source, f"runtime_check must not import {forbidden}"
