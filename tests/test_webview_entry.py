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
- the static resource path helper resolves ``index_fd_work_v5.html`` in both source-run
  and PyInstaller-frozen layouts;
- the bridge only imports ``worktrace.api`` (covered in detail by
  ``test_ui_backend_boundary.py``);
- Overview bridge methods return JSON-serializable data and never leak
  tracebacks (covered in detail by ``test_webview_bridge.py``).
"""

from __future__ import annotations

import json
import sys
import threading
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


def test_pywebview_runtime_version_is_safe_and_exact(monkeypatch):
    import worktrace.webview_main as webview_main

    monkeypatch.setattr(webview_main, "package_version", lambda _name: "6.2.1")

    assert webview_main._pywebview_runtime_version() == "6.2.1"


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


def test_resource_path_resolves_versioned_index_in_source_run():
    import worktrace.webview_main as mod

    with patch.dict(sys.modules, {}, clear=False):
        path = mod.resource_path("index_fd_work_v5.html")
    assert path.name == "index_fd_work_v5.html"
    assert path.is_file(), f"expected versioned index to exist at {path}"


def test_resource_path_resolves_versioned_index_in_frozen_run(monkeypatch, tmp_path):
    import worktrace.webview_main as mod

    fake_meipass = tmp_path / "fake_meipass"
    (fake_meipass / "worktrace" / "webview_ui").mkdir(parents=True, exist_ok=True)
    fake_index = fake_meipass / "worktrace" / "webview_ui" / "index_fd_work_v5.html"
    fake_index.write_text("<html>placeholder</html>", encoding="utf-8")

    monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)
    try:
        path = mod.resource_path("index_fd_work_v5.html")
    finally:
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert path.name == "index_fd_work_v5.html"
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
        lambda: type(
            "P",
            (),
            {
                "log_path": str(tmp_path / "nul"),
                "base_dir": tmp_path / "WorkTrace",
            },
        )(),
    )
    monkeypatch.setattr("worktrace.config.ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _log_path: None)

    evaluate_js_calls = []

    class _FakeWindow:
        def evaluate_js(self, script):
            order.append("evaluate_js")
            evaluate_js_calls.append(script)

        def destroy(self):
            order.append("window_destroy")

    fake_window = _FakeWindow()
    start_calls = {"count": 0, "kwargs": {}}
    create_window_kwargs = {}

    class _FakeWebview:
        renderer_on_start = "edgechromium"

        @staticmethod
        def create_window(*_args, **kwargs):
            order.append("create_window")
            create_window_kwargs.update(kwargs)
            return fake_window

        @staticmethod
        def start(*_args, **kwargs):
            order.append("webview_start")
            start_calls["count"] += 1
            start_calls["kwargs"] = dict(kwargs)
            callback = kwargs.get("func")
            if callable(callback):
                _FakeWebview.renderer = _FakeWebview.renderer_on_start
                callback()

    monkeypatch.setattr(webview_main, "_check_pywebview_available", lambda: _FakeWebview)

    class _FakeFDWorkController:
        def __init__(self, *_args, **_kwargs):
            self.renderer_calls = []
            self.renderer_unavailable_calls = 0
            self.shutdown_calls = 0
            self.status_callback = None
            self.close_callback = None
            self.main_focus_callback = None

        def get_status(self):
            return {
                "session_state": "idle", "page_phase": "none",
                "operation": "none", "ready": False,
                "login_required": False, "error_code": None,
                "navigation_generation": 0,
            }

        def bind_status_callback(self, callback):
            self.status_callback = callback

        def bind_close_callback(self, callback):
            self.close_callback = callback

        def bind_main_focus_callback(self, callback):
            self.main_focus_callback = callback

        def on_renderer_initialized(self, renderer):
            self.renderer_calls.append(renderer)

        def mark_renderer_unavailable(self):
            self.renderer_unavailable_calls += 1

        def shutdown(self):
            self.shutdown_calls += 1

    fake_fd_work_controller = _FakeFDWorkController()

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
        start_result = {"ok": True}

        def __init__(self):
            self.prepared = False

        def prepare_before_webview_start(self):
            result = dict(self.start_result)
            if (
                result.get("ok") is True
                and fake_services.fd_work.get_settings_status().get("enabled") is True
            ):
                fake_services.fd_work.prepare_window_before_start(True)
                self.prepared = True
            return result

        def start_collection_after_privacy_gate(self):
            gate_calls["count"] += 1
            return dict(self.start_result)

        def is_collection_active(self):
            return gate_calls["count"] > 0

        def start_if_authorized(self, *, pre_start=False):
            result = self.start_collection_after_privacy_gate()
            if (
                result.get("ok") is True
                and not self.prepared
                and fake_services.fd_work.get_settings_status().get("enabled") is True
            ):
                if pre_start:
                    fake_services.fd_work.prepare_window_before_start(True)
                else:
                    fake_services.fd_work.prepare_session(True)
            return result

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
        def __init__(self):
            self.status_callback = None
            self.picker_result_callback = None
            self.prepare_calls = []
            self.startup_prepare_calls = []

        def bind_status_callback(self, callback):
            self.status_callback = callback

        def bind_picker_result_callback(self, callback):
            self.picker_result_callback = callback

        def get_settings_status(self):
            return {
                "supported": True, "enabled": False,
                "session_state": "disabled", "operation": "none",
                "ready": False, "login_required": False, "error_code": None,
            }

        def prepare_session(self, show_login_if_required=True):
            self.prepare_calls.append(show_login_if_required)
            return {"ok": True, "status": self.get_settings_status()}

        def prepare_window_before_start(self, show_login_if_required=True):
            order.append("fd_work_prepare_window")
            self.startup_prepare_calls.append(show_login_if_required)
            if self.status_callback is not None:
                self.status_callback(self.get_settings_status())
            return {"ok": True, "status": self.get_settings_status()}

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

    ui_components = webview_main._load_ui_components()
    ui_components.FDWorkWindowController = (
        lambda *_args, **_kwargs: fake_fd_work_controller
    )
    ui_components.WebViewBridge = _FakeBridge
    monkeypatch.setattr(
        webview_main,
        "_load_ui_components",
        lambda: ui_components,
    )

    class _FakeTray:
        def __init__(self, **kwargs):
            self.on_open = kwargs["on_open"]
            self.on_exit = kwargs["on_exit"]
            self.on_session_end = kwargs["on_session_end"]
            self.started = threading.Event()

        def start(self):
            self.started.set()
            return True

        def stop(self):
            return None

        def show_background_notice(self):
            return None

        def set_collection_active(self, _active):
            return None

    fake_tray = _FakeTray(
        on_open=lambda: None,
        on_exit=lambda: None,
        on_session_end=lambda: None,
    )

    def build_tray(**kwargs):
        fake_tray.on_open = kwargs["on_open"]
        fake_tray.on_exit = kwargs["on_exit"]
        fake_tray.on_session_end = kwargs["on_session_end"]
        return fake_tray

    monkeypatch.setattr(webview_main, "WindowsTrayHost", build_tray)

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

    class _FakeUpdateShutdown:
        def prepare(self):
            order.append("prepare_update_shutdown")

        def start_listener(self):
            order.append("start_update_shutdown")

        def bind_shutdown_handler(self, callback):
            assert callable(callback)
            order.append("bind_update_shutdown")

        def stop_listener(self):
            order.append("stop_update_shutdown")

        def close(self):
            order.append("close_update_shutdown")

    monkeypatch.setattr(
        webview_main,
        "get_application_update_shutdown_coordinator",
        _FakeUpdateShutdown,
    )

    return {
        "order": order,
        "gate_calls": gate_calls,
        "start_calls": start_calls,
        "shutdown_calls": shutdown_calls,
        "fake_runtime": fake_runtime,
        "app_control": app_control,
        "settings": fake_settings,
        "fd_work": fake_services.fd_work,
        "fd_work_controller": fake_fd_work_controller,
        "create_window_kwargs": create_window_kwargs,
        "evaluate_js_calls": evaluate_js_calls,
        "instance_coordinator": instance_coordinator,
        "webview": _FakeWebview,
        "tray": fake_tray,
    }


def test_webview_main_calls_unified_privacy_gate_on_startup(monkeypatch, tmp_path):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    result = webview_main.main()
    assert result == 0
    assert mocks["order"].count("fd_work_shutdown") == 1
    assert mocks["gate_calls"]["count"] == 1
    assert mocks["start_calls"]["count"] == 1


def test_enabled_fd_work_window_is_prepared_before_start_without_extra_thread(
    monkeypatch, tmp_path
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    mocks["fd_work"].get_settings_status = lambda: {
        "supported": True, "enabled": True, "session_state": "idle",
        "operation": "none", "ready": False, "login_required": False,
        "error_code": None,
    }
    assert webview_main.main() == 0
    assert mocks["fd_work"].startup_prepare_calls == [True]
    assert mocks["fd_work"].prepare_calls == []
    assert mocks["order"].index("fd_work_prepare_window") < mocks["order"].index(
        "webview_start"
    )
    assert mocks["fd_work_controller"].renderer_calls == ["edgechromium"]
    source = (REPO_ROOT / "worktrace" / "webview_main.py").read_text(
        encoding="utf-8"
    )
    assert "fd-work-session-prepare" not in source


def test_prestart_fd_work_status_does_not_evaluate_main_window_js(
    monkeypatch, tmp_path
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    mocks["fd_work"].get_settings_status = lambda: {
        "supported": True, "enabled": True, "session_state": "probing",
        "operation": "none", "ready": False, "login_required": False,
        "error_code": None,
    }
    assert webview_main.main() == 0

    prestart_order = mocks["order"][: mocks["order"].index("webview_start")]
    assert "fd_work_prepare_window" in prestart_order
    assert "evaluate_js" not in prestart_order


def test_disabled_fd_work_does_not_prepare_auxiliary_window_before_start(
    monkeypatch, tmp_path
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    assert webview_main.main() == 0
    assert mocks["fd_work"].startup_prepare_calls == []
    assert mocks["fd_work_controller"].renderer_calls == ["edgechromium"]


def test_unaccepted_privacy_creates_only_main_window_and_never_prepares_fd_work(
    monkeypatch, tmp_path
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    mocks["app_control"].start_result = {
        "ok": False,
        "error": "请先确认隐私说明",
    }
    mocks["settings"].notice_accepted = False
    mocks["fd_work"].get_settings_status = lambda: {
        "supported": True, "enabled": True, "session_state": "deferred_by_privacy",
        "operation": "none", "ready": False, "login_required": False,
        "error_code": None,
    }

    assert webview_main.main() == 0
    assert mocks["fd_work"].startup_prepare_calls == []
    assert mocks["fd_work"].prepare_calls == []


def test_shipping_webview_forces_edgechromium_and_persistent_worktrace_profile(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    assert webview_main.main() == 0

    kwargs = mocks["start_calls"]["kwargs"]
    assert kwargs["gui"] == "edgechromium"
    assert kwargs["private_mode"] is False
    assert kwargs["storage_path"] == str(tmp_path / "WorkTrace" / "webview-profile")
    assert callable(kwargs["func"])


def test_shipping_webview_opens_the_content_versioned_index(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    assert webview_main.main() == 0

    index_path = webview_main.resource_path("index_fd_work_v5.html")
    assert mocks["create_window_kwargs"]["url"] == (
        webview_main._versioned_resource_url(index_path)
    )


def test_initialized_renderer_mismatch_fails_closed_with_webview2_message(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    messages = []
    mocks["webview"].renderer_on_start = "mshtml"
    monkeypatch.setattr(webview_main, "_show_blocking_startup_message", messages.append)

    assert webview_main.main() == 0
    assert messages == [webview_main._RENDERER_UNAVAILABLE_MESSAGE]
    assert "WebView2" in messages[0]


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


def test_background_start_creates_no_window_until_first_open(
    monkeypatch,
    tmp_path,
):
    mocks = _stub_webview_main_environment(monkeypatch, tmp_path)
    import worktrace.webview_main as webview_main

    result = []
    thread = threading.Thread(
        target=lambda: result.append(webview_main.main(background=True)),
        daemon=True,
    )
    thread.start()
    assert mocks["tray"].started.wait(2.0)
    assert mocks["create_window_kwargs"] == {}

    mocks["tray"].on_open()
    thread.join(5.0)
    assert result == [0]
    assert mocks["create_window_kwargs"]["hidden"] is False
    assert mocks["create_window_kwargs"]["focus"] is True


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
