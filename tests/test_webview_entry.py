"""default WebView entry behavior tests.

These tests cover the default entry contracts:

- ``worktrace.main.main([])`` defaults to WebView, not the Tkinter
  ``WorkTraceApp``;
- ``main`` ignores any command-line args (there is no argparse layer;
  WebView is the only UI);
- when the WebView2 Runtime is missing on Windows, ``webview_main.main``
  returns a non-zero exit code, prints a clear Chinese install prompt, and
  does not start any Tkinter UI;
- when pywebview is missing, ``webview_main.main`` returns a non-zero exit
  code with a clear install prompt;
- the static resource path helper resolves ``index.html`` in both source-run
  and PyInstaller-frozen layouts;
- the bridge only imports ``worktrace.api`` (covered in detail by
  ``test_ui_backend_boundary.py``);
- Overview bridge methods return JSON-serializable data and never leak
  tracebacks (covered in detail by ``test_webview_bridge.py``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_main_defaults_to_webview_without_instantiating_tkinter():
    """``main([])`` must delegate to ``webview_main.main()`` and must not
    reference the Tkinter ``WorkTraceApp``."""
    import worktrace.main as main_mod

    called = {"count": 0}

    def fake_webview_main():
        called["count"] += 1
        return 0

    with patch("worktrace.webview_main.main", fake_webview_main):
        result = main_mod.main([])
    assert result == 0
    assert called["count"] == 1

    # main.py must not import WorkTraceApp at module load time.
    source = (REPO_ROOT / "worktrace" / "main.py").read_text(encoding="utf-8")
    assert "WorkTraceApp" not in source


def test_main_ignores_all_args_and_starts_webview():
    """``main`` must ignore any args and always start the WebView UI.
    There is no argparse layer; args are silently discarded."""
    import worktrace.main as main_mod

    calls = []

    def fake_webview_main():
        calls.append("webview")
        return 0

    with patch("worktrace.webview_main.main", fake_webview_main):
        main_mod.main([])
        main_mod.main(["--unknown"])
        main_mod.main(["--other-flag"])

    assert calls == ["webview", "webview", "webview"]


def test_webview_main_returns_nonzero_when_runtime_missing(monkeypatch, capsys):
    """When the WebView2 Runtime is missing on Windows, ``webview_main.main``
    must:
    - print a clear Chinese install prompt to stderr;
    - return a non-zero exit code;
    - not start any Tkinter UI.
    """
    import worktrace.webview_main as webview_main

    # Patch the reference bound in webview_main (it imports the function
    # directly via ``from .webview_ui.runtime_check import detect_webview2_runtime``),
    # otherwise patching the source module has no effect on the call site.
    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "missing")

    # Stub config/setup_logging so main() can reach the pre-flight check
    # without touching the filesystem.
    monkeypatch.setattr("worktrace.config.resolve_paths", lambda: type("P", (), {"log_path": "nul"})())
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)

    result = webview_main.main()

    assert result != 0
    captured = capsys.readouterr()
    assert "WebView2" in captured.err
    assert "Microsoft" in captured.err
    # The prompt must not mention Tkinter or any fallback wording.
    assert "tkinter" not in captured.err.lower()
    assert "fallback" not in captured.err.lower()
    assert "继续使用默认" not in captured.err


def test_webview_main_returns_nonzero_when_pywebview_missing(monkeypatch, capsys):
    """When pywebview is not installed, ``webview_main.main`` must return a
    non-zero exit code with a clear install prompt and must not fall back to
    any Tkinter UI (the ``worktrace.ui`` package is deleted,
    so there is nothing to fall back to)."""
    import worktrace.webview_main as webview_main

    # Patch the reference bound in webview_main so the pre-flight check passes
    # and execution reaches the pywebview availability check.
    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "installed")
    monkeypatch.setattr("worktrace.config.resolve_paths", lambda: type("P", (), {"log_path": "nul"})())
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)
    # Simulate pywebview not being installed.
    monkeypatch.setitem(sys.modules, "webview", None)

    result = webview_main.main()

    assert result != 0
    captured = capsys.readouterr()
    assert "pywebview" in captured.err
    assert "未安装" in captured.err


def test_webview_main_does_not_swallow_nonzero_exit_from_pre_flight(monkeypatch):
    """If the pre-flight check returns a non-zero code, ``main`` must
    propagate it; the caller (``worktrace.main.main``) must not catch it
    and start a Tkinter UI."""
    import worktrace.main as main_mod
    import worktrace.webview_main as webview_main

    # Patch the reference bound in webview_main so the pre-flight check
    # deterministically reports a missing runtime.
    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "missing")
    monkeypatch.setattr("worktrace.config.resolve_paths", lambda: type("P", (), {"log_path": "nul"})())
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)

    # main_mod.main should return the same non-zero code webview_main returns.
    result_from_main = main_mod.main([])
    result_from_webview = webview_main.main()
    assert result_from_main != 0
    assert result_from_main == result_from_webview


def test_resource_path_resolves_index_html_in_source_run():
    """``resource_path`` must resolve ``index.html`` to an existing file in
    the source-run layout (no ``_MEIPASS`` set)."""
    import worktrace.webview_main as mod

    # Ensure _MEIPASS is not set so the source-run branch is exercised.
    with patch.dict(sys.modules, {}, clear=False):
        path = mod.resource_path("index.html")
    assert path.name == "index.html"
    assert path.is_file(), f"expected index.html to exist at {path}"


def test_resource_path_resolves_index_html_in_frozen_run(monkeypatch, tmp_path):
    """When ``sys._MEIPASS`` is set (PyInstaller frozen layout),
    ``resource_path`` must resolve the bundled resource under
    ``worktrace/webview_ui/``."""
    import worktrace.webview_main as mod

    fake_meipass = tmp_path / "fake_meipass"
    (fake_meipass / "worktrace" / "webview_ui").mkdir(parents=True, exist_ok=True)
    fake_index = fake_meipass / "worktrace" / "webview_ui" / "index.html"
    fake_index.write_text("<html>placeholder</html>", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    try:
        path = mod.resource_path("index.html")
    finally:
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert path.name == "index.html"
    # The frozen path must point inside the fake _MEIPASS tree, under
    # worktrace/webview_ui/.
    assert str(fake_meipass) in str(path)
    assert "webview_ui" in path.parts


def test_bridge_layer_only_imports_allowed_facades():
    """The bridge layer must use API facades and avoid direct lower-layer imports."""
    bridge_dir = REPO_ROOT / "worktrace" / "webview_ui"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(bridge_dir.glob("bridge*.py"))
    )
    forbidden = [
        "from ..services",
        "from worktrace.services",
        "from ..db",
        "from worktrace.db",
        "from ..collector",
        "from worktrace.collector",
        "from ..security",
        "from worktrace.security",
        "from ..runtime",
        "from worktrace.runtime",
        "from ..config",
        "from worktrace.config",
    ]
    for token in forbidden:
        assert token not in source, f"bridge layer must not import {token}"
    assert "from ..api import" in source or "from worktrace.api import" in source


def test_overview_bridge_methods_return_json_serializable_no_traceback(temp_db):
    """All Overview bridge methods must return JSON-serializable dicts and
    must never leak tracebacks on error. This is a focused assertion;
    see ``test_webview_bridge.py`` for the full per-method coverage."""
    from worktrace.services import settings_service
    from worktrace.webview_ui.bridge import WebViewBridge

    settings_service.clear_settings_cache()
    bridge = WebViewBridge()
    for method_name in ("get_status", "toggle_pause", "get_overview", "get_recent_activities"):
        method = getattr(bridge, method_name)
        result = method()
        assert isinstance(result, dict), f"{method_name} must return a dict"
        # Must be JSON-serializable.
        json.dumps(result)
        assert "ok" in result
        # On error, the bridge must return a generic error, not a traceback.
        if result.get("ok") is False:
            assert "error" in result
            assert "traceback" not in str(result).lower()


# --- First-run startup gate --------------------------------
#
# These tests verify the first-run privacy notice gate added to
# ``webview_main.main()``. The gate checks
# ``settings_api.first_run_notice_accepted()`` after
# ``runtime.initialize()`` / ``app_api.set_runtime(runtime)`` and before
# the WebView window is created. If accepted, the collector is
# auto-started; if not accepted (or the read raises), the collector is
# NOT started and the frontend overlay is responsible for showing the
# notice. ``runtime.shutdown()`` must still be called in the finally
# block regardless of the gate outcome.


def _stub_webview_main_environment(monkeypatch, tmp_path):
    """Stub the webview_main.main() environment so it reaches the first-run
    gate without touching the filesystem or starting a real GUI.

    Returns a dict of mocks the test can assert against.
    """
    import worktrace.webview_main as webview_main

    # Pre-flight checks must pass.
    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "installed")
    monkeypatch.setattr("worktrace.config.resolve_paths", lambda: type("P", (), {"log_path": str(tmp_path / "nul")})())
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)

    # Fake pywebview module: create_window returns a sentinel; start()
    # returns immediately so main() can proceed to the finally block.
    fake_window = object()
    start_calls = {"count": 0}

    class _FakeWebview:
        @staticmethod
        def create_window(*_args, **_kwargs):
            return fake_window

        @staticmethod
        def start():
            start_calls["count"] += 1

    monkeypatch.setattr(webview_main, "_check_pywebview_available", lambda: _FakeWebview)

    # Fake AppRuntime: initialize/shutdown are no-ops.
    fake_runtime = type("R", (), {"initialize": lambda self: None, "shutdown": lambda self: None})()
    monkeypatch.setattr(webview_main, "AppRuntime", lambda _paths: fake_runtime)

    # set_runtime must be a no-op; start_collector and
    # start_background_workers are the key mocks.
    start_collector_calls = {"count": 0}
    start_background_workers_calls = {"count": 0}

    def _fake_start_collector():
        start_collector_calls["count"] += 1

    def _fake_start_background_workers():
        start_background_workers_calls["count"] += 1

    monkeypatch.setattr("worktrace.api.app_api.set_runtime", lambda _runtime: None)
    monkeypatch.setattr("worktrace.api.app_api.start_collector", _fake_start_collector)
    monkeypatch.setattr(
        "worktrace.api.app_api.start_background_workers",
        _fake_start_background_workers,
    )

    return {
        "start_collector_calls": start_collector_calls,
        "start_background_workers_calls": start_background_workers_calls,
        "start_calls": start_calls,
        "fake_runtime": fake_runtime,
    }


def test_webview_main_starts_collector_when_notice_accepted(monkeypatch, tmp_path):
    """When first_run_notice_accepted() returns True, webview_main.main()
    must call app_api.start_background_workers() and
    app_api.start_collector() after set_runtime()."""
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "worktrace.api.settings_api.first_run_notice_accepted",
        lambda: True,
    )

    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    assert mocks["start_collector_calls"]["count"] == 1
    assert mocks["start_background_workers_calls"]["count"] == 1
    # The WebView main loop must still have been entered.
    assert mocks["start_calls"]["count"] == 1


def test_webview_main_does_not_start_collector_when_notice_not_accepted(monkeypatch, tmp_path):
    """When first_run_notice_accepted() returns False, webview_main.main()
    must NOT call app_api.start_collector() or
    app_api.start_background_workers(). The WebView must still start
    so the frontend overlay can show the notice."""
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "worktrace.api.settings_api.first_run_notice_accepted",
        lambda: False,
    )

    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    assert mocks["start_collector_calls"]["count"] == 0
    assert mocks["start_background_workers_calls"]["count"] == 0
    # The WebView main loop must still start so the frontend can display
    # the first-run notice overlay.
    assert mocks["start_calls"]["count"] == 1


def test_webview_main_fail_closed_when_notice_read_raises(monkeypatch, tmp_path):
    """When first_run_notice_accepted() raises, webview_main.main() must
    fail closed: NOT call start_collector() or start_background_workers(),
    but still start the WebView so the frontend can display the error."""
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)

    def _raise():
        raise RuntimeError("settings read failed")

    monkeypatch.setattr("worktrace.api.settings_api.first_run_notice_accepted", _raise)

    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    assert mocks["start_collector_calls"]["count"] == 0
    assert mocks["start_background_workers_calls"]["count"] == 0
    assert mocks["start_calls"]["count"] == 1


def test_webview_main_runtime_shutdown_called_even_when_gate_fails(monkeypatch, tmp_path):
    """runtime.shutdown() must still be called in the finally block even
    when the first-run gate read raises."""
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    shutdown_calls = {"count": 0}
    fake_runtime = mocks["fake_runtime"]
    original_shutdown = fake_runtime.shutdown

    def _counting_shutdown():
        shutdown_calls["count"] += 1
        original_shutdown()

    fake_runtime.shutdown = _counting_shutdown

    def _raise():
        raise RuntimeError("settings read failed")

    monkeypatch.setattr("worktrace.api.settings_api.first_run_notice_accepted", _raise)

    import worktrace.webview_main as webview_main

    webview_main.main()
    assert shutdown_calls["count"] == 1


def test_webview_main_collector_start_failure_does_not_block_webview(monkeypatch, tmp_path):
    """When the notice is accepted but app_api.start_collector() raises,
    webview_main.main() must log the error but still start the WebView
    (the user can retry via the sidebar toggle)."""
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "worktrace.api.settings_api.first_run_notice_accepted",
        lambda: True,
    )

    def _raise_on_start():
        raise RuntimeError("collector already running")

    monkeypatch.setattr("worktrace.api.app_api.start_collector", _raise_on_start)

    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    # The WebView must still start.
    assert mocks["start_calls"]["count"] == 1


def test_webview_main_starts_background_workers_before_collector_when_notice_accepted(monkeypatch, tmp_path):
    """When the notice is accepted, webview_main.main() must call
    ``app_api.start_background_workers()`` BEFORE ``app_api.start_collector()``
    so the folder index is warm by the time the collector starts matching
    activities (the privacy gate)."""
    _stub_webview_main_environment(monkeypatch, tmp_path)
    call_order: list[str] = []

    def _track_bg():
        call_order.append("background_workers")

    def _track_collector():
        call_order.append("collector")

    monkeypatch.setattr("worktrace.api.app_api.start_background_workers", _track_bg)
    monkeypatch.setattr("worktrace.api.app_api.start_collector", _track_collector)
    monkeypatch.setattr(
        "worktrace.api.settings_api.first_run_notice_accepted",
        lambda: True,
    )

    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    assert call_order == ["background_workers", "collector"]
