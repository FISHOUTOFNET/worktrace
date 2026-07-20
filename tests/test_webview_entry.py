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

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]

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

    source = (REPO_ROOT / "worktrace" / "main.py").read_text(encoding="utf-8")
    assert "WorkTraceApp" not in source


def test_main_ignores_all_args_and_starts_webview():
    """``main`` must ignore any args and always start the WebView UI."""
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
    import worktrace.webview_main as webview_main

    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "missing")
    monkeypatch.setattr(
        "worktrace.config.resolve_paths",
        lambda: type("P", (), {"log_path": "nul"})(),
    )
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)

    result = webview_main.main()

    assert result != 0
    captured = capsys.readouterr()
    assert "WebView2" in captured.err
    assert "Microsoft" in captured.err
    assert "tkinter" not in captured.err.lower()
    assert "fallback" not in captured.err.lower()
    assert "继续使用默认" not in captured.err


def test_webview_main_returns_nonzero_when_pywebview_missing(monkeypatch, capsys):
    import worktrace.webview_main as webview_main

    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "installed")
    monkeypatch.setattr(
        "worktrace.config.resolve_paths",
        lambda: type("P", (), {"log_path": "nul"})(),
    )
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)
    monkeypatch.setitem(sys.modules, "webview", None)

    result = webview_main.main()

    assert result != 0
    captured = capsys.readouterr()
    assert "pywebview" in captured.err
    assert "未安装" in captured.err


def test_webview_main_does_not_swallow_nonzero_exit_from_pre_flight(monkeypatch):
    import worktrace.main as main_mod
    import worktrace.webview_main as webview_main

    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "missing")
    monkeypatch.setattr(
        "worktrace.config.resolve_paths",
        lambda: type("P", (), {"log_path": "nul"})(),
    )
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)

    result_from_main = main_mod.main([])
    result_from_webview = webview_main.main()
    assert result_from_main != 0
    assert result_from_main == result_from_webview


def test_resource_path_resolves_index_html_in_source_run():
    import worktrace.webview_main as mod

    with patch.dict(sys.modules, {}, clear=False):
        path = mod.resource_path("index.html")
    assert path.name == "index.html"
    assert path.is_file(), f"expected index.html to exist at {path}"


def test_resource_path_resolves_index_html_in_frozen_run(monkeypatch, tmp_path):
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
    assert str(fake_meipass) in str(path)
    assert "webview_ui" in path.parts


def test_bridge_layer_only_imports_allowed_facades():
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
    from tests.support.application import build_test_bridge
    from worktrace.services import settings_service

    settings_service.clear_settings_cache()
    bridge = build_test_bridge()
    for method_name in ("get_status", "toggle_pause", "get_overview"):
        method = getattr(bridge, method_name)
        result = method()
        assert isinstance(result, dict), f"{method_name} must return a dict"
        json.dumps(result)
        assert "ok" in result
        if result.get("ok") is False:
            assert "error" in result
            assert "traceback" not in str(result).lower()


def _stub_webview_main_environment(monkeypatch, tmp_path):
    """Build the entry point from explicit runtime and application capabilities."""
    import worktrace.webview_main as webview_main

    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "installed")
    monkeypatch.setattr(
        "worktrace.config.resolve_paths",
        lambda: type("P", (), {"log_path": str(tmp_path / "nul")})(),
    )
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)

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

    shutdown_calls = {"count": 0}

    class _FakeRuntime:
        def initialize(self):
            return True

        def shutdown(self):
            shutdown_calls["count"] += 1

    fake_runtime = _FakeRuntime()
    monkeypatch.setattr(webview_main, "AppRuntime", lambda _paths: fake_runtime)

    gate_calls = {"count": 0}

    class _FakeAppControl:
        def start_collection_after_privacy_gate(self):
            gate_calls["count"] += 1
            return {"ok": True}

    app_control = _FakeAppControl()
    fake_services = type("Services", (), {"app_control": app_control})()
    monkeypatch.setattr(
        webview_main,
        "build_application_services",
        lambda runtime: fake_services if runtime is fake_runtime else None,
    )

    class _FakeBridge:
        shipping_api = object()

        def __init__(self, services):
            assert services is fake_services

        def set_window(self, window):
            assert window is fake_window

    monkeypatch.setattr(webview_main, "WebViewBridge", _FakeBridge)

    return {
        "gate_calls": gate_calls,
        "start_calls": start_calls,
        "shutdown_calls": shutdown_calls,
        "fake_runtime": fake_runtime,
        "app_control": app_control,
    }


def test_webview_main_calls_unified_privacy_gate_on_startup(monkeypatch, tmp_path):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    assert mocks["gate_calls"]["count"] == 1
    assert mocks["start_calls"]["count"] == 1


def test_webview_main_starts_webview_even_when_gate_fails_closed(monkeypatch, tmp_path):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    mocks["app_control"].start_collection_after_privacy_gate = lambda: {
        "ok": False,
        "error": "请先确认隐私说明",
    }
    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    assert mocks["start_calls"]["count"] == 1


def test_webview_main_runtime_shutdown_called_even_when_gate_fails(monkeypatch, tmp_path):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)

    def _raise_gate() -> dict:
        raise RuntimeError("gate failed")

    mocks["app_control"].start_collection_after_privacy_gate = _raise_gate
    import worktrace.webview_main as webview_main

    webview_main.main()
    assert mocks["shutdown_calls"]["count"] == 1


def test_webview_main_gate_raise_does_not_block_webview(monkeypatch, tmp_path):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)

    def _raise_gate() -> dict:
        raise RuntimeError("gate crashed")

    mocks["app_control"].start_collection_after_privacy_gate = _raise_gate
    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    assert mocks["start_calls"]["count"] == 1
