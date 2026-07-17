"""Default WebView entry and explicit runtime-composition contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_main_defaults_to_webview_without_instantiating_tkinter():
    import worktrace.main as main_mod

    called = {"count": 0}

    def fake_webview_main():
        called["count"] += 1
        return 0

    with patch("worktrace.webview_main.main", fake_webview_main):
        result = main_mod.main([])
    assert result == 0
    assert called["count"] == 1
    assert "WorkTraceApp" not in (REPO_ROOT / "worktrace/main.py").read_text(
        encoding="utf-8"
    )


def test_main_ignores_all_args_and_starts_webview():
    import worktrace.main as main_mod

    calls: list[str] = []
    with patch("worktrace.webview_main.main", lambda: calls.append("webview") or 0):
        main_mod.main([])
        main_mod.main(["--unknown"])
        main_mod.main(["--other-flag"])
    assert calls == ["webview", "webview", "webview"]


def _stub_paths(monkeypatch, tmp_path):
    paths = type(
        "P",
        (),
        {
            "log_path": str(tmp_path / "test.log"),
            "db_path": str(tmp_path / "test.sqlite"),
        },
    )()
    monkeypatch.setattr("worktrace.config.resolve_paths", lambda: paths)
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    return paths


def test_webview_main_returns_nonzero_when_runtime_missing(monkeypatch, capsys, tmp_path):
    import worktrace.webview_main as webview_main

    _stub_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "missing")
    monkeypatch.setattr(webview_main, "setup_logging", lambda _path: None)

    assert webview_main.main() != 0
    captured = capsys.readouterr()
    assert "WebView2" in captured.err
    assert "Microsoft" in captured.err
    assert "tkinter" not in captured.err.lower()
    assert "fallback" not in captured.err.lower()


def test_webview_main_returns_nonzero_when_pywebview_missing(monkeypatch, capsys, tmp_path):
    import worktrace.webview_main as webview_main

    _stub_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "installed")
    monkeypatch.setattr(webview_main, "setup_logging", lambda _path: None)
    monkeypatch.setitem(sys.modules, "webview", None)

    assert webview_main.main() != 0
    captured = capsys.readouterr()
    assert "pywebview" in captured.err
    assert "未安装" in captured.err


def test_webview_main_does_not_swallow_nonzero_preflight(monkeypatch, tmp_path):
    import worktrace.main as main_mod
    import worktrace.webview_main as webview_main

    _stub_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "missing")
    monkeypatch.setattr(webview_main, "setup_logging", lambda _path: None)

    assert main_mod.main([]) == webview_main.main() != 0


def test_resource_path_resolves_index_html_in_source_run():
    import worktrace.webview_main as module

    path = module.resource_path("index.html")
    assert path.name == "index.html"
    assert path.is_file()


def test_resource_path_resolves_index_html_in_frozen_run(monkeypatch, tmp_path):
    import worktrace.webview_main as module

    fake_meipass = tmp_path / "fake_meipass"
    target = fake_meipass / "worktrace/webview_ui/index.html"
    target.parent.mkdir(parents=True)
    target.write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    try:
        path = module.resource_path("index.html")
    finally:
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert path == target


def test_bridge_layer_only_imports_allowed_facades():
    bridge_dir = REPO_ROOT / "worktrace/webview_ui"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(bridge_dir.glob("bridge*.py"))
    )
    forbidden = (
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
    )
    assert [token for token in forbidden if token in source] == []
    assert "from ..api" in source or "from worktrace.api" in source


def test_overview_bridge_methods_are_json_serializable(temp_db):
    from worktrace.webview_ui.bridge import WebViewBridge

    bridge = WebViewBridge()
    for method_name in ("get_status", "toggle_pause", "get_overview"):
        result = getattr(bridge, method_name)()
        assert isinstance(result, dict)
        json.dumps(result)
        assert "ok" in result
        if result.get("ok") is False:
            assert "traceback" not in str(result).lower()


class _FakeRuntime:
    def __init__(self, start_result=None, start_error: Exception | None = None) -> None:
        self.start_result = start_result or {"ok": True}
        self.start_error = start_error
        self.initialize_calls = 0
        self.start_calls = 0
        self.shutdown_calls = 0

    def initialize(self):
        self.initialize_calls += 1
        return True

    def start_authorized_collection(self):
        self.start_calls += 1
        if self.start_error is not None:
            raise self.start_error
        return dict(self.start_result)

    def shutdown(self):
        self.shutdown_calls += 1

    def quiesce_collection_now(self, timeout_seconds=5.0):
        return {"ok": True}

    def reset_collection_runtime_now(self, timeout_seconds=5.0):
        return {"ok": True}


def _stub_webview_main_environment(
    monkeypatch,
    tmp_path,
    *,
    start_result=None,
    start_error: Exception | None = None,
):
    import worktrace.webview_main as webview_main

    _stub_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "installed")
    monkeypatch.setattr(webview_main, "setup_logging", lambda _path: None)
    start_calls = {"count": 0}
    fake_window = object()

    class _FakeWebview:
        @staticmethod
        def create_window(*_args, **_kwargs):
            return fake_window

        @staticmethod
        def start():
            start_calls["count"] += 1

    runtime = _FakeRuntime(start_result=start_result, start_error=start_error)
    monkeypatch.setattr(webview_main, "_check_pywebview_available", lambda: _FakeWebview)
    monkeypatch.setattr(webview_main, "AppRuntime", lambda _paths: runtime)
    return runtime, start_calls


def test_webview_main_calls_injected_privacy_gate_on_startup(monkeypatch, tmp_path):
    import worktrace.webview_main as webview_main

    runtime, start_calls = _stub_webview_main_environment(monkeypatch, tmp_path)
    assert webview_main.main() == 0
    assert runtime.start_calls == 1
    assert start_calls["count"] == 1


def test_webview_main_starts_webview_when_gate_fails_closed(monkeypatch, tmp_path):
    import worktrace.webview_main as webview_main

    runtime, start_calls = _stub_webview_main_environment(
        monkeypatch,
        tmp_path,
        start_result={"ok": False, "error": "请先确认隐私说明"},
    )
    assert webview_main.main() == 0
    assert runtime.start_calls == 1
    assert start_calls["count"] == 1


def test_webview_main_shutdown_runs_when_gate_raises(monkeypatch, tmp_path):
    import worktrace.webview_main as webview_main

    runtime, start_calls = _stub_webview_main_environment(
        monkeypatch,
        tmp_path,
        start_error=RuntimeError("gate failed"),
    )
    assert webview_main.main() == 0
    assert runtime.shutdown_calls == 1
    assert start_calls["count"] == 1
