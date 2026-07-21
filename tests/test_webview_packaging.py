"""Packaging, default WebView entry, and WebView2 runtime detection tests.

WebView is the default and only shipping UI. These tests cover:

- WorkTrace.spec bundles WebView resources, schema SQL, the Windows probe helper,
  and the required win32timezone hidden import;
- pyinstaller_entry.py routes the closed probe mode or forwards to
  worktrace.main.main;
- ``python -m worktrace.main`` defaults to the WebView entry point and does not
  instantiate the retired Tkinter application;
- importing worktrace.main or worktrace.webview_main does not start the GUI;
- WebView2 runtime_check is importable, never raises, and does not block
  non-Windows;
- the missing-runtime message does not mention Tkinter or fallback behavior;
- runtime_check stays inside webview_ui and does not import backend layers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.serial]

from tests.webview.static_helpers import ALL_JS_FILES

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "WorkTrace.spec"
INDEX_HTML_PATH = REPO_ROOT / "worktrace" / "webview_ui" / "index.html"
ENTRY_PATH = REPO_ROOT / "scripts" / "pyinstaller_entry.py"
MAIN_PATH = REPO_ROOT / "worktrace" / "main.py"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file: {path}"
    return path.read_text(encoding="utf-8")


def test_spec_bundles_webview_ui_static_resources():
    """The spec bundles every static module from the shared file manifest."""

    spec = _read(SPEC_PATH)
    for name in ("index.html", "styles.css"):
        assert name in spec, f"WorkTrace.spec must bundle webview_ui/{name}"
    for name in ALL_JS_FILES:
        assert name in spec, f"WorkTrace.spec must bundle webview_ui/js/{name}"
    assert "app.js" not in spec, (
        "WorkTrace.spec must not reference the removed monolithic frontend bundle"
    )


def test_index_html_loads_all_js_in_order():
    """index.html loads every current JavaScript module in manifest order."""

    html = _read(INDEX_HTML_PATH)
    import re

    scripts = re.findall(r'<script\s+src="js/([^"]+)"\s*>\s*</script>', html)
    assert scripts, "expected at least one <script src=js/...> tag in index.html"
    assert scripts == ALL_JS_FILES, (
        "index.html script order must match ALL_JS_FILES exactly; "
        f"got {scripts}"
    )


def test_all_js_files_exist_on_disk():
    js_dir = REPO_ROOT / "worktrace" / "webview_ui" / "js"
    for name in ALL_JS_FILES:
        path = js_dir / name
        assert path.is_file(), f"missing JS module: {path}"


def test_spec_bundles_webview_resources_under_webview_ui_dir():
    assert "webview_ui" in _read(SPEC_PATH)


def test_spec_collects_pywebview():
    spec = _read(SPEC_PATH)
    assert "collect_all('webview')" in spec or 'collect_all("webview")' in spec


def test_spec_retains_schema_sql():
    assert "schema.sql" in _read(SPEC_PATH)


def test_spec_retains_windows_probe_helper():
    assert "windows_probe_helper.py" in _read(SPEC_PATH)


def test_spec_does_not_bundle_customtkinter():
    assert "customtkinter" not in _read(SPEC_PATH)


def test_spec_retains_win32timezone():
    assert "win32timezone" in _read(SPEC_PATH)


def test_entry_script_routes_probe_or_forwards_to_worktrace_main():
    source = _read(ENTRY_PATH)
    assert "--windows-probe-helper" in source
    assert "_run_windows_probe_helper" in source
    assert "from worktrace.main import main" in source


def test_main_module_does_not_import_worktrace_app():
    source = _read(MAIN_PATH)
    assert "WorkTraceApp" not in source, (
        "worktrace.main must not import or reference WorkTraceApp; "
        "WebView is the only shipping UI."
    )
    assert "from .ui.app" not in source
    assert "from worktrace.ui.app" not in source


def test_main_defaults_to_webview_without_flag():
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
    import worktrace.main as main_mod

    def fake_webview_main_returning_nonzero():
        return 2

    with patch("worktrace.webview_main.main", fake_webview_main_returning_nonzero):
        result = main_mod.main([])
    assert result == 2


def test_main_propagates_webview_failure_without_tkinter_fallback(monkeypatch):
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
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


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
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    loaded = json.loads(result.stdout)
    assert loaded["has_main"] is True


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
    from worktrace.webview_ui.runtime_check import detect_webview2_runtime

    with patch("worktrace.webview_ui.runtime_check.sys") as fake_sys:
        fake_sys.platform = "linux"
        status = detect_webview2_runtime()
    assert status == "unknown"


def test_detect_webview2_runtime_never_raises_on_windows():
    from worktrace.webview_ui.runtime_check import detect_webview2_runtime

    with patch("worktrace.webview_ui.runtime_check.sys") as fake_sys:
        fake_sys.platform = "win32"
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
    from worktrace.webview_ui.runtime_check import missing_runtime_message

    msg = missing_runtime_message()
    msg_lower = msg.lower()
    assert "tkinter" not in msg_lower
    assert "fallback" not in msg_lower
    assert "继续使用默认" not in msg


def test_runtime_check_does_not_import_backend():
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
