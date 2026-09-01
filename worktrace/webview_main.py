"""WebView UI entry point (default and only shipping UI)."""
from __future__ import annotations

import logging
import sys
import threading
import time
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from . import PRODUCT_DISPLAY_NAME, PRODUCT_NAME, config
from .collector.single_instance import get_application_instance_coordinator
from .desktop.collection_icon_projection import CollectionIconProjectionHost
from .desktop.deferred_ui import DeferredUIGate, InitialUIRequest
from .desktop.install_bootstrap import consume_fd_work_install_intent
from .desktop.update_shutdown import get_application_update_shutdown_coordinator
from .desktop.windows_tray import WindowsTrayHost
from .integrations.fd_work.deferred_interaction import (
    DeferredFDWorkInteractionCoordinator,
)
from .platforms.window_activation import grant_foreground_permission
from .platforms.windows_startup import (
    WindowsLaunchAtLoginRepair,
    WindowsStartupRegistration,
)
from .runtime.app_runtime import AppRuntime
from .runtime.application_services import build_application_services
from .webview_ui.runtime_check import (
    detect_webview2_runtime,
    missing_runtime_message,
)


def setup_logging(log_path) -> None:
    from .logging_config import configure_file_logging

    configure_file_logging(log_path)


def resource_path(relative: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "worktrace" / "webview_ui" / relative
    return Path(__file__).resolve().parent / "webview_ui" / relative


def desktop_resource_path(relative: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "worktrace" / "assets" / relative
    return Path(__file__).resolve().parent / "assets" / relative


def _versioned_resource_url(path: Path) -> str:
    canonical_text = (
        path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    )
    revision = sha256(canonical_text.encode("utf-8")).hexdigest()[:16]
    return f"{path}?v={revision}"


def _check_pywebview_available() -> Any:
    try:
        import webview
        return webview
    except ImportError as exc:
        raise RuntimeError(
            "pywebview 未安装，无法启动 WebView UI。"
            "请运行 pip install pywebview==6.2.1 后重试。"
        ) from exc


def _pywebview_runtime_version() -> str:
    try:
        return str(package_version("pywebview"))
    except PackageNotFoundError:
        return "unknown"


def _brand_runtime_message(message: str) -> str:
    return str(message).replace("WorkTrace", PRODUCT_NAME)


def _show_blocking_startup_message(message: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            _brand_runtime_message(message),
            PRODUCT_DISPLAY_NAME,
            0x00000010,
        )
    except Exception:
        logging.warning("startup message box failed", exc_info=True)


def _should_show_blocking_startup_message(*, background: bool) -> bool:
    return background or bool(getattr(sys, "frozen", False))


def _report_runtime_missing(*, background: bool = False) -> int:
    msg = _brand_runtime_message(missing_runtime_message())
    print(msg, file=sys.stderr)
    if _should_show_blocking_startup_message(background=background):
        _show_blocking_startup_message(msg)
    logging.error("webview startup aborted: WebView2 Runtime missing")
    return 2


def _report_already_running(instance_coordinator) -> int:
    permission_granted = grant_foreground_permission(
        fallback_title=PRODUCT_DISPLAY_NAME,
    )
    activated = instance_coordinator.signal_existing_instance()
    logging.info(
        "webview startup skipped: existing instance activation=%s "
        "foreground_permission=%s",
        activated,
        permission_granted,
    )
    return 0


def _report_startup_failure(message: str, *, background: bool) -> int:
    branded_message = _brand_runtime_message(message)
    print(branded_message, file=sys.stderr)
    if _should_show_blocking_startup_message(background=background):
        _show_blocking_startup_message(branded_message)
    return 2


def _background_start_allowed(services, prestart_result: dict[str, Any]) -> bool:
    try:
        notice_result = services.settings.get_first_run_notice_for_webview()
        notice = notice_result.get("notice") if notice_result.get("ok") else None
        if not isinstance(notice, dict) or notice.get("accepted") is not True:
            return False
        status_result = services.settings.get_settings_privacy_status()
        status = status_result.get("status") if status_result.get("ok") else None
        if not isinstance(status, dict):
            return False
        if status.get("recovery_blocked") is True:
            return False
        if status.get("maintenance_restored") is False:
            return False
        authorized = prestart_result.get(
            "authorized",
            prestart_result.get("ok"),
        )
        return authorized is True
    except Exception:
        logging.exception("background startup eligibility check failed")
        return False


def _bind_shell_events(
    window,
    shell,
    *,
    startup_started_at: float | None = None,
) -> None:
    events = getattr(window, "events", None)
    if events is None:
        return
    events.closing += shell.handle_window_closing
    if startup_started_at is None:
        events.loaded += shell.handle_window_loaded
        return

    def handle_window_loaded() -> None:
        logging.info(
            "startup stage=main_window_loaded elapsed_ms=%s",
            int((time.monotonic() - startup_started_at) * 1000),
        )
        shell.handle_window_loaded()

    events.loaded += handle_window_loaded


_RENDERER_UNAVAILABLE_MESSAGE = (
    f"{PRODUCT_NAME} 无法使用 Microsoft Edge WebView2 renderer。"
    "请安装或修复 WebView2 Runtime 后重新打开应用。"
)


def _load_ui_components() -> SimpleNamespace:
    """Import renderer-owned composition only when a UI is actually requested."""

    from .desktop.shell import DesktopShellController
    from .desktop.windows_icons import WindowsWindowIconHost
    from .desktop.windows_webview_power import WindowsWebView2PowerController
    from .integrations.fd_work.helper_bridge import FDWorkHelperBridge
    from .integrations.fd_work.interaction_coordinator import (
        FDWorkInteractionCoordinator,
    )
    from .integrations.fd_work.main_window_sink import FDWorkMainWindowSink
    from .integrations.fd_work.page_adapter import FDWorkPageAdapter
    from .integrations.fd_work.window_controller import FDWorkWindowController
    from .webview_ui.bridge import WebViewBridge

    return SimpleNamespace(
        DesktopShellController=DesktopShellController,
        WindowsWindowIconHost=WindowsWindowIconHost,
        WindowsWebView2PowerController=WindowsWebView2PowerController,
        FDWorkHelperBridge=FDWorkHelperBridge,
        FDWorkInteractionCoordinator=FDWorkInteractionCoordinator,
        FDWorkMainWindowSink=FDWorkMainWindowSink,
        FDWorkPageAdapter=FDWorkPageAdapter,
        FDWorkWindowController=FDWorkWindowController,
        WebViewBridge=WebViewBridge,
    )


def _prepare_webview(*, background: bool) -> Any | None:
    if detect_webview2_runtime() == "missing":
        _report_runtime_missing(background=background)
        return None
    try:
        webview = _check_pywebview_available()
    except RuntimeError as exc:
        _report_startup_failure(str(exc), background=background)
        return None
    logging.info("pywebview_runtime version=%s", _pywebview_runtime_version())
    return webview


def _prepare_post_privacy_startup(app_control) -> tuple[dict[str, Any], bool]:
    prestart_result: dict[str, Any] = {
        "ok": False,
        "authorized": False,
    }
    prepare_before_webview_start = getattr(
        app_control,
        "prepare_before_webview_start",
        None,
    )
    deferred_runtime_start = callable(prepare_before_webview_start)
    try:
        if deferred_runtime_start:
            prestart_result = dict(prepare_before_webview_start())
        else:
            # Compatibility path for injected legacy capabilities. Shipping uses
            # PostPrivacyStartupCoordinator and therefore the split preparation.
            prestart_result = dict(app_control.start_if_authorized(pre_start=True))
    except Exception:
        logging.exception("webview startup: pre-start preparation failed")
    return prestart_result, deferred_runtime_start


def _create_fd_work_interaction(webview, ui):
    fd_work_page_adapter = ui.FDWorkPageAdapter()
    fd_work_helper_bridge = ui.FDWorkHelperBridge(
        action_result_sink=fd_work_page_adapter
    )
    fd_work_controller = ui.FDWorkWindowController(
        webview,
        page_adapter=fd_work_page_adapter,
        helper_bridge=fd_work_helper_bridge,
    )
    fd_work_coordinator = ui.FDWorkInteractionCoordinator(
        window_controller=fd_work_controller,
        page_adapter=fd_work_page_adapter,
    )
    fd_work_helper_bridge.bind_coordinator(fd_work_coordinator)
    return fd_work_controller, fd_work_coordinator


def _run_webview_ui(
    *,
    webview,
    ui,
    runtime,
    services,
    paths,
    startup_started_at: float,
    background: bool,
    runtime_started_before_renderer: bool,
    deferred_runtime_start: bool,
    tray,
    exit_application,
    shell_holder: dict[str, Any],
    instance_coordinator,
    update_shutdown,
    update_shutdown_prepared: bool,
    deferred_ui: DeferredUIGate | None,
    deferred_fd_work: DeferredFDWorkInteractionCoordinator | None,
    foreground_fd_work: tuple[Any, Any] | None,
) -> int:
    fd_work_main_sink = ui.FDWorkMainWindowSink(deliver_asynchronously=True)
    fd_work_controller = None
    fd_work_coordinator = None
    shell = None
    try:
        if foreground_fd_work is None:
            fd_work_controller, fd_work_coordinator = _create_fd_work_interaction(
                webview,
                ui,
            )
        else:
            fd_work_controller, fd_work_coordinator = foreground_fd_work

        bridge = ui.WebViewBridge(services)
        index_path = resource_path("index_fd_work_v5.html")
        window = webview.create_window(
            title=PRODUCT_DISPLAY_NAME,
            url=_versioned_resource_url(index_path),
            js_api=bridge.shipping_api,
            width=1080,
            height=720,
            min_size=(840, 560),
            hidden=False,
            focus=True,
        )
        logging.info(
            "startup stage=main_window_created elapsed_ms=%s hidden=False",
            int((time.monotonic() - startup_started_at) * 1000),
        )
        bridge.set_window(window)
        fd_work_main_sink.bind_window(window)
        services.fd_work.bind_status_callback(fd_work_main_sink.status_changed)
        services.fd_work.bind_picker_result_callback(fd_work_main_sink.picker_result)

        if deferred_fd_work is not None:
            # Binding is renderer-free. Any helper-window preparation must wait
            # until webview.start has entered the GUI runtime.
            deferred_fd_work.bind(fd_work_coordinator)

        icon_path = desktop_resource_path("worktrace.ico")
        window_icons = ui.WindowsWindowIconHost(
            window_title=PRODUCT_DISPLAY_NAME,
            icon_path=icon_path,
        )
        webview_power = (
            ui.WindowsWebView2PowerController(window)
            if sys.platform.startswith("win")
            else None
        )
        shell = ui.DesktopShellController(
            window=window,
            tray=tray,
            initial_hidden=False,
            window_icons=window_icons,
            webview_power=webview_power,
        )
        attach_window_icons = getattr(tray, "attach_window_icons", None)
        if callable(attach_window_icons):
            attach_window_icons(window_icons)
        shell_holder["shell"] = shell
        fd_work_controller.bind_main_focus_callback(shell.show_window)
        _bind_shell_events(
            window,
            shell,
            startup_started_at=startup_started_at,
        )
        if deferred_ui is not None:
            deferred_ui.bind_shell(shell)
        else:
            instance_coordinator.bind_activation_handler(shell.show_window)
            if update_shutdown_prepared:
                update_shutdown.bind_shutdown_handler(exit_application)
        webview_profile_path = paths.base_dir / "webview-profile"
        webview_profile_path.mkdir(parents=True, exist_ok=True)

        def handle_webview_initialized() -> None:
            renderer = str(getattr(webview, "renderer", "") or "").lower()
            safe_renderer = (
                renderer
                if renderer in {"edgechromium", "cef", "qt", "gtk", "mshtml"}
                else "unknown"
            )
            logging.info(
                "startup stage=renderer_initialized elapsed_ms=%s renderer=%s",
                int((time.monotonic() - startup_started_at) * 1000),
                safe_renderer,
            )

            # Tray readiness and icon projection are auxiliary shell work. Run
            # them only after webview.start has entered the GUI runtime so a slow
            # Explorer/pywin32 path cannot gate creation of the first window.
            try:
                tray_available = shell.start()
            except Exception:
                logging.exception("desktop shell startup failed")
                tray_available = False
            logging.info(
                "startup stage=shell_ready elapsed_ms=%s tray=%s",
                int((time.monotonic() - startup_started_at) * 1000),
                tray_available,
            )

            if sys.platform.startswith("win") and renderer != "edgechromium":
                fd_work_controller.mark_renderer_unavailable()
                _show_blocking_startup_message(_RENDERER_UNAVAILABLE_MESSAGE)
                return
            fd_work_main_sink.mark_ready()
            fd_work_controller.on_renderer_initialized(safe_renderer)

            # Headless startup may already have completed participant preparation
            # while the deferred interaction had no renderer. Once the real
            # coordinator is bound, warm the helper only now.
            if deferred_fd_work is not None and runtime_started_before_renderer:
                try:
                    services.fd_work.prepare_session(
                        show_login_if_required=False
                    )
                except Exception:
                    logging.exception("deferred FD Work renderer preparation failed")
            fd_work_main_sink.status_changed(services.fd_work.get_settings_status())

            if runtime_started_before_renderer or not deferred_runtime_start:
                return
            runtime_start_started_at = time.monotonic()
            try:
                startup_result = dict(
                    services.app_control.start_if_authorized(pre_start=False)
                )
                logging.info(
                    "startup stage=runtime_ready elapsed_ms=%s runtime_elapsed_ms=%s ok=%s degraded=%s",
                    int((time.monotonic() - startup_started_at) * 1000),
                    int((time.monotonic() - runtime_start_started_at) * 1000),
                    bool(startup_result.get("ok")),
                    bool(startup_result.get("degraded")),
                )
                if not startup_result.get("ok"):
                    logging.error(
                        "collector startup rejected error=%s",
                        startup_result.get("error")
                        or startup_result.get("error_code")
                        or "unknown",
                    )
                    if background:
                        shell.show_window()
                elif startup_result.get("degraded"):
                    logging.warning(
                        "collector started with background worker degradation"
                    )
            except Exception:
                logging.exception(
                    "webview startup: authorized runtime startup failed; user can retry"
                )
                if background:
                    shell.show_window()

        webview.start(
            func=handle_webview_initialized,
            gui="edgechromium",
            http_server=True,
            private_mode=False,
            storage_path=str(webview_profile_path),
        )
        return 0
    finally:
        fd_work_main_sink.mark_unavailable()


def _wait_after_failed_headless_ui(deferred_ui: DeferredUIGate) -> None:
    while True:
        request = deferred_ui.wait_for_initial_request()
        if request is InitialUIRequest.EXIT:
            return


def _request_runtime_shutdown(runtime) -> None:
    request_shutdown = getattr(runtime, "request_shutdown", None)
    if not callable(request_shutdown):
        logging.warning("application runtime missing cooperative shutdown capability")
        return
    request_shutdown()


def _run_cleanup_step(name: str, callback) -> None:
    try:
        callback()
    except Exception:
        logging.exception("application cleanup failed stage=%s", name)


def main(*, background: bool = False) -> int:
    startup_started_at = time.monotonic()
    paths = config.resolve_paths()
    config.ensure_directories(paths)
    setup_logging(paths.log_path)
    logging.info("webview ui startup background=%s", background)

    webview = None
    ui = None
    if not background:
        webview = _prepare_webview(background=False)
        if webview is None:
            return 2
        ui = _load_ui_components()

    startup_registration = WindowsStartupRegistration()
    runtime = AppRuntime(
        paths,
        launch_at_login_repair=WindowsLaunchAtLoginRepair(startup_registration),
    )
    services = None
    shell_holder: dict[str, Any] = {}
    tray = None
    fd_work_controller = None
    deferred_fd_work = None
    foreground_fd_work = None
    instance_coordinator = get_application_instance_coordinator()
    update_shutdown = get_application_update_shutdown_coordinator()
    update_shutdown_prepared = False
    exit_lock = threading.Lock()
    exit_worker_running = False
    runtime_shutdown_lock = threading.Lock()
    runtime_shutdown_completed = False
    deferred_ui: DeferredUIGate | None = None

    def shutdown_runtime_once() -> None:
        nonlocal runtime_shutdown_completed
        with runtime_shutdown_lock:
            if runtime_shutdown_completed:
                return
            runtime.shutdown()
            runtime_shutdown_completed = True

    try:
        try:
            instance_coordinator.prepare_activation_event()
        except Exception:
            logging.exception("activation Event preparation failed")
            return _report_startup_failure(
                f"{PRODUCT_NAME} 实例激活通道初始化失败，请重新打开应用。",
                background=background,
            )
        try:
            update_shutdown.prepare()
            update_shutdown_prepared = True
        except Exception:
            logging.exception("update shutdown Event preparation failed")
        try:
            initialized = runtime.initialize()
        except Exception:
            logging.exception("runtime initialization failed")
            return _report_startup_failure(
                f"{PRODUCT_NAME} 初始化失败，请打开应用处理后重试。",
                background=background,
            )
        logging.info(
            "startup stage=runtime_initialized elapsed_ms=%s",
            int((time.monotonic() - startup_started_at) * 1000),
        )
        if initialized is False:
            return _report_already_running(instance_coordinator)
        try:
            instance_coordinator.start_activation_listener()
        except Exception:
            logging.exception("activation listener startup failed")
            return _report_startup_failure(
                f"{PRODUCT_NAME} 实例激活监听启动失败，请重新打开应用。",
                background=background,
            )
        if update_shutdown_prepared:
            try:
                update_shutdown.start_listener()
            except Exception:
                logging.exception("update shutdown listener startup failed")
                update_shutdown_prepared = False

        if background:
            deferred_fd_work = DeferredFDWorkInteractionCoordinator()
            services = build_application_services(
                runtime,
                fd_work_interaction_coordinator=deferred_fd_work,
                paths=paths,
                startup_registration=startup_registration,
            )
        else:
            fd_work_controller, fd_work_coordinator = _create_fd_work_interaction(
                webview,
                ui,
            )
            foreground_fd_work = (fd_work_controller, fd_work_coordinator)
            services = build_application_services(
                runtime,
                fd_work_interaction_coordinator=fd_work_coordinator,
                paths=paths,
                startup_registration=startup_registration,
            )
        if consume_fd_work_install_intent(services.fd_work):
            logging.info("FD Work enabled from installer bootstrap")
        logging.info(
            "startup stage=services_ready elapsed_ms=%s",
            int((time.monotonic() - startup_started_at) * 1000),
        )

        app_control = services.app_control
        prestart_result, deferred_runtime_start = _prepare_post_privacy_startup(
            app_control
        )
        logging.info(
            "startup stage=prestart_ready elapsed_ms=%s authorized=%s deferred_runtime=%s",
            int((time.monotonic() - startup_started_at) * 1000),
            bool(prestart_result.get("authorized", prestart_result.get("ok"))),
            deferred_runtime_start,
        )

        runtime_started_before_renderer = not deferred_runtime_start
        headless_allowed = False
        if background and _background_start_allowed(services, prestart_result):
            if deferred_runtime_start:
                runtime_start_started_at = time.monotonic()
                try:
                    runtime_start_result = dict(
                        app_control.start_if_authorized(pre_start=False)
                    )
                except Exception:
                    logging.exception("headless authorized runtime startup failed")
                    runtime_start_result = {"ok": False}
                logging.info(
                    "startup stage=headless_runtime_ready elapsed_ms=%s runtime_elapsed_ms=%s ok=%s degraded=%s",
                    int((time.monotonic() - startup_started_at) * 1000),
                    int((time.monotonic() - runtime_start_started_at) * 1000),
                    bool(runtime_start_result.get("ok")),
                    bool(runtime_start_result.get("degraded")),
                )
                runtime_started_before_renderer = runtime_start_result.get("ok") is True
                headless_allowed = runtime_started_before_renderer
            else:
                headless_allowed = prestart_result.get("ok") is True

        if headless_allowed:
            deferred_ui = DeferredUIGate()

        def open_application() -> bool:
            if deferred_ui is not None:
                return deferred_ui.request_open()
            shell = shell_holder.get("shell")
            return bool(shell and shell.show_window())

        def exit_application() -> None:
            nonlocal exit_worker_running
            with exit_lock:
                if exit_worker_running:
                    return
                exit_worker_running = True

            def perform_application_exit() -> None:
                nonlocal exit_worker_running
                logging.info("application exit requested")
                try:
                    _run_cleanup_step(
                        "runtime_request",
                        lambda: _request_runtime_shutdown(runtime),
                    )
                    if services is not None:
                        _run_cleanup_step(
                            "fd_work_exit",
                            lambda: services.fd_work.shutdown(),
                        )
                    elif fd_work_controller is not None:
                        _run_cleanup_step(
                            "fd_work_controller_exit",
                            lambda: fd_work_controller.shutdown(),
                        )

                    shell = shell_holder.get("shell")
                    if deferred_ui is not None:
                        _run_cleanup_step(
                            "deferred_ui_exit",
                            lambda: deferred_ui.request_exit(),
                        )
                        if shell is not None:
                            # request_exit owns the normal bound-shell path. Call
                            # the shell capability once more so a transient native
                            # destroy failure stays retryable instead of becoming
                            # sticky behind DeferredUIGate._exit_requested.
                            _run_cleanup_step(
                                "desktop_shell_exit",
                                lambda: shell.exit_application(),
                            )
                        elif tray is not None:
                            _run_cleanup_step("tray_exit", lambda: tray.stop())
                    elif shell is not None:
                        _run_cleanup_step(
                            "desktop_shell_exit",
                            lambda: shell.exit_application(),
                        )
                    elif tray is not None:
                        _run_cleanup_step("tray_exit", lambda: tray.stop())

                    # Explicit application exit owns full runtime terminalization.
                    # The outer finally reuses the same once-guarded capability,
                    # so GUI-loop return cannot race a second terminal shutdown.
                    _run_cleanup_step("runtime_exit", shutdown_runtime_once)
                finally:
                    with exit_lock:
                        exit_worker_running = False

            try:
                threading.Thread(
                    target=perform_application_exit,
                    name="WorkTraceApplicationExit",
                    daemon=True,
                ).start()
            except Exception:
                with exit_lock:
                    exit_worker_running = False
                logging.exception("application exit worker startup failed")

        icon_path = desktop_resource_path("worktrace.ico")
        tray = CollectionIconProjectionHost(
            tray=WindowsTrayHost(
                icon_path=icon_path,
                on_open=open_application,
                on_exit=exit_application,
                on_session_end=exit_application,
            ),
            collection_active_provider=app_control.is_collection_active,
        )

        if deferred_ui is not None:
            instance_coordinator.bind_activation_handler(deferred_ui.request_open)
            if update_shutdown_prepared:
                update_shutdown.bind_shutdown_handler(exit_application)
            tray_available = tray.start()
            if not tray_available:
                logging.error("headless tray unavailable; opening visible UI")
                deferred_ui.request_open()
            logging.info(
                "startup stage=headless_waiting elapsed_ms=%s tray=%s",
                int((time.monotonic() - startup_started_at) * 1000),
                tray_available,
            )
            while True:
                request = deferred_ui.wait_for_initial_request()
                if request is InitialUIRequest.EXIT:
                    return 0
                if request is not InitialUIRequest.OPEN:
                    continue
                webview = _prepare_webview(background=True)
                if webview is None:
                    deferred_ui.mark_initial_open_failed()
                    continue
                try:
                    ui = _load_ui_components()
                    return _run_webview_ui(
                        webview=webview,
                        ui=ui,
                        runtime=runtime,
                        services=services,
                        paths=paths,
                        startup_started_at=startup_started_at,
                        background=True,
                        runtime_started_before_renderer=True,
                        deferred_runtime_start=deferred_runtime_start,
                        tray=tray,
                        exit_application=exit_application,
                        shell_holder=shell_holder,
                        instance_coordinator=instance_coordinator,
                        update_shutdown=update_shutdown,
                        update_shutdown_prepared=update_shutdown_prepared,
                        deferred_ui=deferred_ui,
                        deferred_fd_work=deferred_fd_work,
                        foreground_fd_work=None,
                    )
                except Exception:
                    logging.exception("deferred webview bootstrap failed")
                    # A failed first composition is not retried after FD Work may
                    # have bound. Terminalize that interaction graph while the
                    # independent runtime and collector remain alive.
                    deferred_fd_work.shutdown()
                    _report_startup_failure(
                        f"{PRODUCT_NAME} 界面启动失败；后台记录仍在继续。",
                        background=True,
                    )
                    _wait_after_failed_headless_ui(deferred_ui)
                    return 2

        if webview is None:
            webview = _prepare_webview(background=background)
            if webview is None:
                return 2
            ui = _load_ui_components()
        return _run_webview_ui(
            webview=webview,
            ui=ui,
            runtime=runtime,
            services=services,
            paths=paths,
            startup_started_at=startup_started_at,
            background=background,
            runtime_started_before_renderer=runtime_started_before_renderer,
            deferred_runtime_start=deferred_runtime_start,
            tray=tray,
            exit_application=exit_application,
            shell_holder=shell_holder,
            instance_coordinator=instance_coordinator,
            update_shutdown=update_shutdown,
            update_shutdown_prepared=update_shutdown_prepared,
            deferred_ui=None,
            deferred_fd_work=deferred_fd_work,
            foreground_fd_work=foreground_fd_work,
        )
    except Exception:
        logging.exception("webview composition failed")
        return _report_startup_failure(
            f"{PRODUCT_NAME} 启动失败，请重新打开应用。",
            background=background,
        )
    finally:
        logging.info("application cleanup begin")
        _run_cleanup_step(
            "activation_listener",
            lambda: instance_coordinator.stop_activation_listener(),
        )
        _run_cleanup_step(
            "update_shutdown_listener",
            lambda: update_shutdown.stop_listener(),
        )
        if services is not None:
            _run_cleanup_step("fd_work", lambda: services.fd_work.shutdown())
        elif fd_work_controller is not None:
            _run_cleanup_step("fd_work_controller", lambda: fd_work_controller.shutdown())
        shell = shell_holder.get("shell")
        if shell is not None:
            _run_cleanup_step("desktop_shell", lambda: shell.stop())
        elif tray is not None:
            _run_cleanup_step("tray", lambda: tray.stop())
        _run_cleanup_step("runtime", shutdown_runtime_once)
        _run_cleanup_step("update_shutdown", lambda: update_shutdown.close())
        logging.info("application cleanup end")


if __name__ == "__main__":
    raise SystemExit(main())
