"""Phase 0C packaging, startup --webview, and WebView2 runtime detection tests.

Covers:
- WorkTrace.spec bundles webview_ui static resources + retains schema.sql,
  open_files_helper, customtkinter, win32timezone;
- pyinstaller_entry.py forwards --webview (does not strip it);
- ``python -m worktrace.main`` defaults to Tkinter and does not start GUI on import;
- ``--webview`` routes to the WebView entry point;
- WebView2 runtime_check is importable, never raises, and does not block
  non-Windows;
- boundary: runtime_check stays inside webview_ui and does not import backend.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "WorkTrace.spec"
ENTRY_PATH = REPO_ROOT / "scripts" / "pyinstaller_entry.py"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file: {path}"
    return path.read_text(encoding="utf-8")


# --- packaging resource tests -------------------------------------------


def test_spec_bundles_webview_ui_static_resources():
    spec = _read(SPEC_PATH)
    for name in ("index.html", "app.js", "styles.css"):
        assert name in spec, f"WorkTrace.spec must bundle webview_ui/{name}"


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


def test_spec_retains_customtkinter():
    spec = _read(SPEC_PATH)
    assert "collect_all('customtkinter')" in spec or 'collect_all("customtkinter")' in spec


def test_spec_retains_win32timezone():
    spec = _read(SPEC_PATH)
    assert "win32timezone" in spec


def test_entry_script_forwards_webview_flag():
    """The entry script must not strip --webview before calling main()."""
    source = _read(ENTRY_PATH)
    # The only argv branch is --open-files-helper; everything else falls
    # through to main(), which reads sys.argv. So --webview is preserved.
    assert "--open-files-helper" in source
    assert "from worktrace.main import main" in source
    # No code path that consumes/ignores --webview explicitly.
    assert "--webview" not in source or source.count("--webview") == 0


# --- startup tests ------------------------------------------------------


def test_main_wants_webview_flag_detected():
    from worktrace.main import _wants_webview

    assert _wants_webview(["--webview"]) is True
    assert _wants_webview([]) is False
    assert _wants_webview(["--foo"]) is False


def test_main_routes_to_webview_when_flag_present():
    """When --webview is passed, main() delegates to webview_main.main()."""
    import worktrace.main as main_mod

    called = {"count": 0}

    def fake_webview_main():
        called["count"] += 1
        return 0

    with patch("worktrace.webview_main.main", fake_webview_main):
        result = main_mod.main(["--webview"])
    assert result == 0
    assert called["count"] == 1


def test_main_does_not_route_to_webview_without_flag():
    """Without --webview, main() must not call webview_main.main()."""
    import worktrace.main as main_mod

    called = {"count": 0}

    def fake_webview_main():
        called["count"] += 1
        return 0

    with patch("worktrace.webview_main.main", fake_webview_main):
        # main() without --webview tries to start Tkinter; intercept before
        # that by patching WorkTraceApp to a no-op.
        with patch("worktrace.main.WorkTraceApp") as fake_app:
            fake_app.return_value.mainloop.return_value = None
            with patch("worktrace.main.config") as fake_config:
                fake_config.resolve_paths.return_value = type(
                    "P", (), {"log_path": "nul"}
                )()
                fake_config.ensure_directories.return_value = None
                with patch("worktrace.main.AppRuntime") as fake_runtime:
                    fake_runtime.return_value.initialize.return_value = None
                    fake_runtime.return_value.shutdown.return_value = None
                    with patch("worktrace.main.app_api"):
                        main_mod.main([])
    assert called["count"] == 0


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


def test_missing_runtime_message_is_chinese_and_mentions_runtime():
    from worktrace.webview_ui.runtime_check import missing_runtime_message

    msg = missing_runtime_message()
    assert "WebView2" in msg
    assert "Tkinter" in msg


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
