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

    def fake_webview_main(*, background=False):
        assert background is False
        called["count"] += 1
        return 0

    with patch("worktrace.webview_main.main", fake_webview_main):
        result = main_mod.main([])
    assert result == 0
    assert called["count"] == 1

    source = (REPO_ROOT / "worktrace" / "main.py").read_text(encoding="utf-8")
    assert "WorkTraceApp" not in source


def test_main_parses_background_once_and_forwards_to_webview():
    """``main`` owns shipping argument parsing and forwards background intent."""
    import worktrace.main as main_mod

    calls = []

    def fake_webview_main(*, background=False):
        calls.append(background)
        return 0

    with patch("worktrace.webview_main.main", fake_webview_main):
        main_mod.main([])
        main_mod.main(["--unknown"])
        main_mod.main(["--background"])

    assert calls == [False, False, True]


def test_main_uses_process_argv_when_not_explicitly_injected(monkeypatch):
    import worktrace.main as main_mod

    calls = []

    def fake_webview_main(*, background=False):
        calls.append(background)
        return 0

    monkeypatch.setattr(sys, "argv", ["worktrace", "--background"])
    with patch("worktrace.webview_main.main", fake_webview_main):
        assert main_mod.main() == 0
    assert calls == [True]


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

    order = []
    monkeypatch.setattr(webview_main, "detect_webview2_runtime", lambda: "installed")
    monkeypatch.setattr(
        "worktrace.config.resolve_paths",
        lambda: type("P", (), {"log_path": str(tmp_path / "nul")})(),
    )
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)

    fake_window = object()
    start_calls = {"count": 0}
    create_window_kwargs = {}

    class _FakeWebview:
        @staticmethod
        def create_window(*_args, **kwargs):
            order.append("create_window")
            create_window_kwargs.update(kwargs)
            return fake_window

        @staticmethod
        def start():
            order.append("webview_start")
            start_calls["count"] += 1

    monkeypatch.setattr(webview_main, "_check_pywebview_available", lambda: _FakeWebview)

    shutdown_calls = {"count": 0}

    class _FakeRuntime:
        def initialize(self):
            order.append("runtime_initialize")
            return True

        def shutdown(self):
            order.append("runtime_shutdown")
            shutdown_calls["count"] += 1

    fake_runtime = _FakeRuntime()
    monkeypatch.setattr(webview_main, "AppRuntime", lambda _paths: fake_runtime)

    gate_calls = {"count": 0}

    class _FakeAppControl:
        def start_collection_after_privacy_gate(self):
            gate_calls["count"] += 1
            return {"ok": True}

    app_control = _FakeAppControl()
    class _FakeSettings:
        notice_accepted = True
        recovery_blocked = False

        def get_first_run_notice_for_webview(self):
            return {
                "ok": True,
                "notice": {"accepted": self.notice_accepted},
            }

        def get_settings_privacy_status(self):
            return {
                "ok": True,
                "status": {
                    "recovery_blocked": self.recovery_blocked,
                    "maintenance_restored": not self.recovery_blocked,
                },
            }

    fake_settings = _FakeSettings()
    class _FakeFDWork:
        def shutdown(self):
            order.append("fd_work_shutdown")

    fake_services = type(
        "Services",
        (),
        {
            "app_control": app_control,
            "settings": fake_settings,
            "fd_work": _FakeFDWork(),
        },
    )()
    monkeypatch.setattr(
        webview_main,
        "build_application_services",
        lambda runtime, **_kwargs: (
            order.append("build_services")
            or (fake_services if runtime is fake_runtime else None)
        ),
    )

    class _FakeBridge:
        shipping_api = object()

        def __init__(self, services):
            assert services is fake_services

        def set_window(self, window):
            assert window is fake_window

    monkeypatch.setattr(webview_main, "WebViewBridge", _FakeBridge)

    class _FakeTray:
        def start(self):
            return True

        def stop(self):
            return None

        def show_background_notice(self):
            return None

    monkeypatch.setattr(
        webview_main,
        "WindowsTrayHost",
        lambda **_kwargs: _FakeTray(),
    )

    class _FakeInstanceCoordinator:
        def __init__(self):
            self.signal_calls = 0
            self.stop_calls = 0

        def prepare_activation_event(self):
            order.append("prepare_activation")

        def start_activation_listener(self):
            order.append("start_listener")

        def bind_activation_handler(self, callback):
            assert callable(callback)
            order.append("bind_handler")

        def signal_existing_instance(self):
            self.signal_calls += 1
            order.append("signal_existing")
            return True

        def stop_activation_listener(self):
            self.stop_calls += 1
            order.append("stop_listener")

    instance_coordinator = _FakeInstanceCoordinator()
    monkeypatch.setattr(
        webview_main,
        "get_application_instance_coordinator",
        lambda: instance_coordinator,
    )

    return {
        "order": order,
        "gate_calls": gate_calls,
        "start_calls": start_calls,
        "shutdown_calls": shutdown_calls,
        "fake_runtime": fake_runtime,
        "app_control": app_control,
        "settings": fake_settings,
        "create_window_kwargs": create_window_kwargs,
        "instance_coordinator": instance_coordinator,
    }


def test_webview_main_calls_unified_privacy_gate_on_startup(monkeypatch, tmp_path):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    assert mocks["order"].count("fd_work_shutdown") == 1
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


def test_webview_main_prepares_event_before_mutex_and_listens_before_composition(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    assert webview_main.main() == 0

    order = mocks["order"]
    assert order.index("prepare_activation") < order.index("runtime_initialize")
    assert order.index("runtime_initialize") < order.index("start_listener")
    assert order.index("start_listener") < order.index("build_services")
    assert order.index("create_window") < order.index("bind_handler")
    assert mocks["instance_coordinator"].stop_calls == 1


def test_second_instance_signals_prepared_event_and_cleans_up(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    mocks["fake_runtime"].initialize = lambda: (
        mocks["order"].append("runtime_initialize") or False
    )

    assert webview_main.main() == 0
    assert mocks["instance_coordinator"].signal_calls == 1
    assert mocks["instance_coordinator"].stop_calls == 1
    assert mocks["shutdown_calls"]["count"] == 1
    assert mocks["start_calls"]["count"] == 0
    assert "build_services" not in mocks["order"]


def test_activation_prepare_failure_cleans_runtime_without_initializing(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    def fail_prepare():
        mocks["order"].append("prepare_activation")
        raise RuntimeError("event unavailable")

    mocks["instance_coordinator"].prepare_activation_event = fail_prepare

    assert webview_main.main() == 2
    assert "runtime_initialize" not in mocks["order"]
    assert mocks["instance_coordinator"].stop_calls == 1
    assert mocks["shutdown_calls"]["count"] == 1


def test_background_start_hides_only_when_privacy_and_recovery_are_ready(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    assert webview_main.main(background=True) == 0
    assert mocks["create_window_kwargs"]["hidden"] is True
    assert mocks["create_window_kwargs"]["focus"] is False


def test_background_start_forces_visible_window_when_privacy_is_unaccepted(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    mocks["settings"].notice_accepted = False
    import worktrace.webview_main as webview_main

    assert webview_main.main(background=True) == 0
    assert mocks["create_window_kwargs"]["hidden"] is False
    assert mocks["create_window_kwargs"]["focus"] is True


def test_background_runtime_initialization_failure_shows_blocking_error(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    def fail_initialize():
        raise RuntimeError("database unavailable")

    messages = []
    mocks["fake_runtime"].initialize = fail_initialize
    monkeypatch.setattr(
        webview_main,
        "_show_blocking_startup_message",
        messages.append,
    )

    assert webview_main.main(background=True) == 2
    assert messages and "初始化失败" in messages[0]
    assert mocks["start_calls"]["count"] == 0


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
