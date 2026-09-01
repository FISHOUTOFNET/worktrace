from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from worktrace import webview_main
from worktrace.integrations.fd_work.deferred_interaction import (
    DeferredFDWorkInteractionCoordinator,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract]


class _EventHook:
    def __init__(self) -> None:
        self.callbacks = []

    def __iadd__(self, callback):
        self.callbacks.append(callback)
        return self


class _Window:
    def __init__(self, release: threading.Event) -> None:
        self.events = SimpleNamespace(closing=_EventHook(), loaded=_EventHook())
        self._release = release

    def destroy(self) -> None:
        self._release.set()


class _Runtime:
    instances: list["_Runtime"] = []
    order: list[str] = []

    def __init__(self, paths, **_kwargs) -> None:
        self.paths = paths
        self.initialize_calls = 0
        self.shutdown_calls = 0
        self.collector_supervisor = SimpleNamespace(
            set_privacy_authorized=lambda _authorized: None,
            prepare_after_privacy=lambda **_kwargs: None,
        )
        type(self).instances.append(self)

    def initialize(self) -> bool:
        type(self).order.append("runtime.initialize")
        self.initialize_calls += 1
        return True

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _AppControl:
    def __init__(self, *, authorized: bool) -> None:
        self.authorized = authorized
        self.prepare_calls = 0
        self.start_calls: list[bool] = []
        self.started = threading.Event()

    def prepare_before_webview_start(self):
        self.prepare_calls += 1
        return {
            "ok": self.authorized,
            "authorized": self.authorized,
            "prepared": self.authorized,
        }

    def start_if_authorized(self, *, pre_start: bool = False):
        _Runtime.order.append("runtime.start")
        self.start_calls.append(pre_start)
        if self.authorized:
            self.started.set()
            return {"ok": True, "authorized": True, "degraded": False}
        return {"ok": False, "authorized": False, "error": "privacy_gate_required"}

    def is_collection_active(self) -> bool:
        return self.started.is_set()


class _FDWork:
    def __init__(self) -> None:
        self.shutdown_calls = 0
        self.prepare_window_calls = 0

    def bind_status_callback(self, callback) -> None:
        self.status_callback = callback

    def bind_picker_result_callback(self, callback) -> None:
        self.picker_callback = callback

    def prepare_window_before_start(self, show_login_if_required=False):
        self.prepare_window_calls += 1
        return {"ok": True}

    def get_settings_status(self):
        return {"enabled": True, "ready": False}

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _Settings:
    def __init__(
        self,
        *,
        eligible: bool,
        recovery_blocked: bool = False,
        maintenance_restored: bool = True,
    ) -> None:
        self.eligible = eligible
        self.recovery_blocked = recovery_blocked
        self.maintenance_restored = maintenance_restored

    def get_first_run_notice_for_webview(self):
        return {"ok": True, "notice": {"accepted": self.eligible}}

    def get_settings_privacy_status(self):
        return {
            "ok": True,
            "status": {
                "recovery_blocked": self.recovery_blocked,
                "maintenance_restored": self.maintenance_restored,
            },
        }


class _InstanceCoordinator:
    def __init__(self) -> None:
        self.handler = None
        self.started = False

    def prepare_activation_event(self) -> None: pass

    def start_activation_listener(self) -> None:
        self.started = True

    def bind_activation_handler(self, callback) -> None:
        self.handler = callback

    def signal_existing_instance(self) -> bool:
        return True

    def stop_activation_listener(self) -> None: pass


class _UpdateShutdown:
    def __init__(self) -> None:
        self.handler = None

    def prepare(self) -> None: pass

    def start_listener(self) -> None: pass

    def bind_shutdown_handler(self, callback) -> None:
        self.handler = callback

    def stop_listener(self) -> None: pass

    def close(self) -> None: pass


class _Tray:
    instances: list["_Tray"] = []
    started = threading.Event()

    def __init__(self, *, icon_path, on_open, on_exit, on_session_end) -> None:
        self.on_open = on_open
        self.on_exit = on_exit
        self.on_session_end = on_session_end
        self.start_calls = 0
        self.stop_calls = 0
        self.active_values: list[bool] = []
        type(self).instances.append(self)

    def start(self) -> bool:
        self.start_calls += 1
        type(self).started.set()
        return True

    def stop(self) -> None:
        self.stop_calls += 1

    def set_collection_active(self, active: bool) -> None:
        self.active_values.append(active)

    def show_background_notice(self) -> None: pass


class _WebView:
    def __init__(self, *, block: bool) -> None:
        self.block = block
        self.create_calls = []
        self.start_calls = 0
        self.start_entered = threading.Event()
        self.release = threading.Event()
        self.renderer = "edgechromium"

    def create_window(self, **kwargs):
        _Runtime.order.append("webview.create")
        self.create_calls.append(kwargs)
        return _Window(self.release)

    def start(self, *, func, **_kwargs) -> None:
        self.start_calls += 1
        func()
        self.start_entered.set()
        if self.block:
            assert self.release.wait(5.0)


class _Controller:
    instances: list["_Controller"] = []

    def __init__(self, _webview, *, page_adapter, helper_bridge) -> None:
        self.shutdown_calls = 0
        type(self).instances.append(self)

    def bind_main_focus_callback(self, callback) -> None:
        self.focus_callback = callback

    def mark_renderer_unavailable(self) -> None: pass

    def on_renderer_initialized(self, renderer) -> None: pass

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _Coordinator:
    instances: list["_Coordinator"] = []

    def __init__(self, *, window_controller, page_adapter) -> None:
        self.status_callback = lambda _status: None
        self.picker_callback = lambda _result: None
        self.shutdown_calls = 0
        type(self).instances.append(self)

    def bind_status_callback(self, callback) -> None:
        self.status_callback = callback

    def bind_picker_result_callback(self, callback) -> None:
        self.picker_callback = callback

    def get_status(self):
        return {
            "session_state": "idle",
            "page_phase": "none",
            "operation": "none",
            "interaction_owner": "none",
            "ready": False,
            "login_required": False,
            "error_code": None,
            "navigation_generation": 0,
        }

    def enable(self) -> None: pass

    def disable(self) -> None: pass

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _HelperBridge:
    def __init__(self, *, action_result_sink) -> None: pass

    def bind_coordinator(self, coordinator) -> None:
        self.coordinator = coordinator


class _Sink:
    def __init__(self, *, deliver_asynchronously) -> None: pass

    def status_changed(self, status) -> None: pass

    def picker_result(self, result) -> None: pass

    def bind_window(self, window) -> None: pass

    def mark_ready(self) -> None: pass

    def mark_unavailable(self) -> None: pass


class _Bridge:
    services_seen = []

    def __init__(self, services) -> None:
        type(self).services_seen.append(services)
        self.shipping_api = object()

    def set_window(self, window) -> None: pass


class _Shell:
    instances: list["_Shell"] = []

    def __init__(self, *, window, tray, **_kwargs) -> None:
        self.window = window
        self.tray = tray
        self.show_calls = 0
        self.exit_calls = 0
        type(self).instances.append(self)

    def start(self) -> bool:
        return self.tray.start()

    def show_window(self) -> bool:
        self.show_calls += 1
        return True

    def exit_application(self) -> bool:
        self.exit_calls += 1
        self.window.destroy()
        return True

    def handle_window_closing(self): return False

    def handle_window_loaded(self): return None

    def stop(self) -> None:
        self.tray.stop()


@pytest.fixture
def startup(monkeypatch, tmp_path):
    _Runtime.instances.clear()
    _Runtime.order.clear()
    _Tray.instances.clear()
    _Tray.started.clear()
    _Controller.instances.clear()
    _Coordinator.instances.clear()
    _Bridge.services_seen.clear()
    instance = _InstanceCoordinator()
    update = _UpdateShutdown()
    webview = _WebView(block=True)
    app_control = _AppControl(authorized=True)
    fd_work = _FDWork()
    services = SimpleNamespace(
        app_control=app_control,
        settings=_Settings(eligible=True),
        fd_work=fd_work,
    )
    build_calls = []
    detect_calls = []
    check_calls = []
    detect_event = threading.Event()

    paths = SimpleNamespace(
        log_path=tmp_path / "worktrace.log",
        base_dir=tmp_path,
        db_path=tmp_path / "worktrace.db",
    )
    monkeypatch.setattr(webview_main.config, "resolve_paths", lambda: paths)
    monkeypatch.setattr(webview_main.config, "ensure_directories", lambda _paths: None)
    monkeypatch.setattr(webview_main, "setup_logging", lambda _path: None)
    monkeypatch.setattr(webview_main, "resource_path", lambda _path: Path("index.html"))
    monkeypatch.setattr(webview_main, "desktop_resource_path", lambda _path: Path("icon.ico"))
    monkeypatch.setattr(webview_main, "_versioned_resource_url", str)
    monkeypatch.setattr(webview_main, "AppRuntime", _Runtime)
    monkeypatch.setattr(
        webview_main,
        "build_application_services",
        lambda runtime, **kwargs: build_calls.append((runtime, kwargs)) or services,
    )
    monkeypatch.setattr(webview_main, "consume_fd_work_install_intent", lambda _fd: False)
    monkeypatch.setattr(webview_main, "get_application_instance_coordinator", lambda: instance)
    monkeypatch.setattr(webview_main, "get_application_update_shutdown_coordinator", lambda: update)
    monkeypatch.setattr(webview_main, "WindowsTrayHost", _Tray)
    def detect_runtime():
        detect_calls.append("detect")
        detect_event.set()
        return "installed"

    monkeypatch.setattr(webview_main, "detect_webview2_runtime", detect_runtime)
    monkeypatch.setattr(
        webview_main,
        "_check_pywebview_available",
        lambda: check_calls.append("check") or webview,
    )
    monkeypatch.setattr(webview_main, "_pywebview_runtime_version", lambda: "test")
    monkeypatch.setattr(webview_main, "_show_blocking_startup_message", lambda _msg: None)
    components = SimpleNamespace(
        DesktopShellController=_Shell,
        WindowsWindowIconHost=lambda **_kwargs: object(),
        WindowsWebView2PowerController=lambda _window: object(),
        FDWorkPageAdapter=lambda: object(),
        FDWorkHelperBridge=_HelperBridge,
        FDWorkWindowController=_Controller,
        FDWorkInteractionCoordinator=_Coordinator,
        FDWorkMainWindowSink=_Sink,
        WebViewBridge=_Bridge,
    )
    monkeypatch.setattr(webview_main, "_load_ui_components", lambda: components)

    return SimpleNamespace(
        instance=instance,
        update=update,
        webview=webview,
        app_control=app_control,
        fd_work=fd_work,
        services=services,
        build_calls=build_calls,
        detect_calls=detect_calls,
        detect_event=detect_event,
        check_calls=check_calls,
    )


def _run_background_in_thread():
    result = []
    thread = threading.Thread(
        target=lambda: result.append(webview_main.main(background=True)),
        daemon=True,
    )
    thread.start()
    return thread, result


def test_authorized_background_starts_runtime_and_tray_before_any_webview(startup) -> None:
    thread, result = _run_background_in_thread()
    try:
        assert startup.app_control.started.wait(2.0)
        assert _Tray.started.wait(2.0)
        assert startup.detect_calls == []
        assert startup.check_calls == []
        assert startup.webview.create_calls == []
        assert _Controller.instances == []
        assert len(startup.build_calls) == 1
        assert len(_Runtime.instances) == 1
        runtime, build_kwargs = startup.build_calls[0]
        assert runtime is _Runtime.instances[0]
        assert isinstance(
            build_kwargs["fd_work_interaction_coordinator"],
            DeferredFDWorkInteractionCoordinator,
        )
    finally:
        _Tray.instances[0].on_exit()
        startup.webview.release.set()
        thread.join(5.0)
    assert result == [0]


def test_tray_and_activation_race_bootstraps_one_ui_with_original_objects(startup) -> None:
    thread, result = _run_background_in_thread()
    assert _Tray.started.wait(2.0)
    tray = _Tray.instances[0]
    barrier = threading.Barrier(3)

    def invoke(callback) -> None:
        barrier.wait()
        callback()

    callers = [
        threading.Thread(target=invoke, args=(tray.on_open,)),
        threading.Thread(target=invoke, args=(startup.instance.handler,)),
    ]
    for caller in callers:
        caller.start()
    barrier.wait()
    for caller in callers:
        caller.join()

    assert startup.webview.start_entered.wait(2.0)
    assert len(startup.webview.create_calls) == 1
    assert len(_Controller.instances) == 1
    assert len(_Coordinator.instances) == 1
    assert len(startup.build_calls) == 1
    assert len(_Runtime.instances) == 1
    assert _Bridge.services_seen == [startup.services]
    assert startup.app_control.start_calls == [False]

    startup.instance.handler()
    startup.instance.handler()
    assert len(startup.webview.create_calls) == 1
    assert _Shell.instances[0].show_calls >= 2

    tray.on_exit()
    thread.join(5.0)
    assert result == [0]


def test_update_shutdown_exits_headless_without_creating_ui(startup) -> None:
    thread, result = _run_background_in_thread()
    assert _Tray.started.wait(2.0)

    startup.update.handler()
    thread.join(5.0)

    assert result == [0]
    assert startup.webview.create_calls == []
    assert _Controller.instances == []
    assert _Runtime.instances[0].shutdown_calls == 1


@pytest.mark.parametrize(
    ("settings", "authorized"),
    [
        (_Settings(eligible=False), False),
        (_Settings(eligible=True, recovery_blocked=True), True),
        (_Settings(eligible=True, maintenance_restored=False), True),
    ],
    ids=("privacy", "recovery", "maintenance"),
)
def test_background_ineligible_for_headless_opens_visible_ui(
    startup,
    settings,
    authorized,
) -> None:
    startup.services.settings = settings
    startup.app_control.authorized = authorized
    startup.webview.block = False

    assert webview_main.main(background=True) == 0

    assert startup.detect_calls == ["detect"]
    assert len(startup.webview.create_calls) == 1
    assert startup.webview.create_calls[0]["hidden"] is False
    assert len(_Controller.instances) == 1


def test_foreground_preserves_renderer_then_runtime_start_contract(startup) -> None:
    startup.webview.block = False
    original_detect = webview_main.detect_webview2_runtime

    def detect():
        _Runtime.order.append("webview.detect")
        return original_detect()

    webview_main.detect_webview2_runtime = detect
    try:
        assert webview_main.main(background=False) == 0
    finally:
        webview_main.detect_webview2_runtime = original_detect

    assert _Runtime.order[:2] == ["webview.detect", "runtime.initialize"]
    assert startup.app_control.prepare_calls == 1
    assert startup.app_control.start_calls == [False]
    assert len(startup.webview.create_calls) == 1
    assert startup.webview.create_calls[0]["hidden"] is False
    assert _Runtime.order.index("webview.create") < _Runtime.order.index("runtime.start")


def test_missing_runtime_on_first_open_keeps_collector_alive_and_allows_retry(
    startup,
    monkeypatch,
) -> None:
    detections = iter(("missing", "installed"))
    first_open_failed = threading.Event()
    original_mark_failed = webview_main.DeferredUIGate.mark_initial_open_failed

    def mark_failed(gate) -> None:
        original_mark_failed(gate)
        first_open_failed.set()

    monkeypatch.setattr(
        webview_main.DeferredUIGate,
        "mark_initial_open_failed",
        mark_failed,
    )
    monkeypatch.setattr(
        webview_main,
        "detect_webview2_runtime",
        lambda: (
            startup.detect_calls.append("detect"),
            startup.detect_event.set(),
            next(detections),
        )[-1],
    )
    thread, result = _run_background_in_thread()
    assert _Tray.started.wait(2.0)
    tray = _Tray.instances[0]

    tray.on_open()
    assert startup.detect_event.wait(2.0)
    assert first_open_failed.wait(2.0)
    assert len(startup.detect_calls) == 1
    assert thread.is_alive()
    assert _Runtime.instances[0].shutdown_calls == 0
    assert startup.webview.create_calls == []

    tray.on_open()
    assert startup.webview.start_entered.wait(2.0)
    assert len(startup.webview.create_calls) == 1
    tray.on_exit()
    thread.join(5.0)
    assert result == [0]


def test_ui_composition_failure_keeps_headless_runtime_until_explicit_exit(
    startup,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        webview_main,
        "_load_ui_components",
        lambda: (_ for _ in ()).throw(RuntimeError("ui import failed")),
    )
    thread, result = _run_background_in_thread()
    assert _Tray.started.wait(2.0)

    _Tray.instances[0].on_open()
    assert startup.detect_event.wait(2.0)
    assert startup.detect_calls == ["detect"]
    assert thread.is_alive()
    assert _Runtime.instances[0].shutdown_calls == 0

    startup.update.handler()
    thread.join(5.0)
    assert result == [2]
