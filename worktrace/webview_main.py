"""WebView UI entry point (default and only shipping UI)."""
from __future__ import annotations

import logging
import json
import sys
import threading
from pathlib import Path
from typing import Any, Mapping

from . import config
from .collector.single_instance import get_application_instance_coordinator
from .desktop.shell import DesktopShellController
from .desktop.windows_tray import WindowsTrayHost
from .integrations.fd_work.window_controller import FDWorkWindowController
from .runtime.app_runtime import AppRuntime
from .runtime.application_services import build_application_services
from .webview_ui.bridge import WebViewBridge
from .webview_ui.runtime_check import (
    detect_webview2_runtime,
    missing_runtime_message,
)


def setup_logging(log_path) -> None:
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


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


def _check_pywebview_available() -> Any:
    try:
        import webview
        return webview
    except ImportError as exc:
        raise RuntimeError(
            "pywebview 未安装，无法启动 WebView UI。"
            "请运行 pip install pywebview>=5.0 后重试。"
        ) from exc


def _show_blocking_startup_message(message: str) -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "WorkTrace",
            0x00000010,
        )
    except Exception:
        logging.warning("startup message box failed", exc_info=True)


def _report_runtime_missing(*, background: bool = False) -> int:
    msg = missing_runtime_message()
    print(msg, file=sys.stderr)
    if background:
        _show_blocking_startup_message(msg)
    logging.error("webview startup aborted: WebView2 Runtime missing")
    return 2


def _report_already_running(instance_coordinator) -> int:
    activated = instance_coordinator.signal_existing_instance()
    logging.info(
        "webview startup skipped: existing instance activation=%s",
        activated,
    )
    return 0


def _report_startup_failure(message: str, *, background: bool) -> int:
    print(message, file=sys.stderr)
    if background:
        _show_blocking_startup_message(message)
    return 2


def _background_start_allowed(services, startup_result: dict[str, Any]) -> bool:
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
        return startup_result.get("ok") is True
    except Exception:
        logging.exception("background startup eligibility check failed")
        return False


def _bind_shell_events(window, shell: DesktopShellController) -> None:
    events = getattr(window, "events", None)
    if events is None:
        return
    events.closing += shell.handle_window_closing
    events.loaded += shell.handle_window_loaded


def _defer_fd_work_callback(callback) -> None:
    timer = threading.Timer(0.05, callback)
    timer.daemon = True
    timer.start()


_RENDERER_UNAVAILABLE_MESSAGE = (
    "WorkTrace 无法使用 Microsoft Edge WebView2 renderer。"
    "请安装或修复 WebView2 Runtime 后重新打开应用。"
)


def main(*, background: bool = False) -> int:
    paths = config.resolve_paths()
    config.ensure_directories(paths)
    setup_logging(paths.log_path)
    logging.info("webview ui startup")

    if detect_webview2_runtime() == "missing":
        return _report_runtime_missing(background=background)
    try:
        webview = _check_pywebview_available()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        if background:
            _show_blocking_startup_message(str(exc))
        return 2

    runtime = AppRuntime(paths)
    shell: DesktopShellController | None = None
    fd_work_controller: FDWorkWindowController | None = None
    services = None
    instance_coordinator = get_application_instance_coordinator()

    try:
        try:
            instance_coordinator.prepare_activation_event()
        except Exception:
            logging.exception("activation Event preparation failed")
            return _report_startup_failure(
                "WorkTrace 实例激活通道初始化失败，请重新打开应用。",
                background=background,
            )
        try:
            initialized = runtime.initialize()
        except Exception:
            logging.exception("runtime initialization failed")
            return _report_startup_failure(
                "WorkTrace 初始化失败，请打开应用处理后重试。",
                background=background,
            )
        if initialized is False:
            return _report_already_running(instance_coordinator)
        try:
            instance_coordinator.start_activation_listener()
        except Exception:
            logging.exception("activation listener startup failed")
            return _report_startup_failure(
                "WorkTrace 实例激活监听启动失败，请重新打开应用。",
                background=background,
            )

        main_window_holder: dict[str, Any] = {}

        def report_fd_work_status(status: Mapping[str, Any]) -> None:
            window = main_window_holder.get("window")
            if window is None:
                return
            payload = json.dumps(dict(status), ensure_ascii=True)
            try:
                window.evaluate_js(
                    "window.WorkTraceApp&&"
                    f"window.WorkTraceApp.receiveFDWorkStatus({payload})"
                )
            except Exception:
                logging.debug("FD Work status delivery skipped")

        fd_work_controller = FDWorkWindowController(
            webview,
            schedule=_defer_fd_work_callback,
        )
        services = build_application_services(
            runtime,
            fd_work_window_controller=fd_work_controller,
        )
        services.fd_work.bind_status_callback(report_fd_work_status)
        app_control = services.app_control
        startup_result: dict[str, Any] = {"ok": False}
        try:
            startup_result = app_control.start_collection_after_privacy_gate()
            if not startup_result.get("ok"):
                logging.error(
                    "collector startup rejected error=%s",
                    startup_result.get("error", "unknown"),
                )
            elif startup_result.get("degraded"):
                logging.warning("collector started with background worker degradation")
        except Exception:
            logging.exception(
                "webview startup: authorized startup failed; user can retry"
            )

        bridge = WebViewBridge(services)
        index_path = resource_path("index.html")
        initial_hidden = background and _background_start_allowed(
            services,
            startup_result,
        )
        try:
            window = webview.create_window(
                title="WorkTrace",
                url=str(index_path),
                js_api=bridge.shipping_api,
                width=1080,
                height=720,
                min_size=(800, 540),
                hidden=initial_hidden,
                focus=not initial_hidden,
            )
            bridge.set_window(window)
            main_window_holder["window"] = window
            shell_holder: dict[str, DesktopShellController] = {}

            def exit_application() -> None:
                services.fd_work.shutdown()
                shell_holder["shell"].exit_application()

            tray = WindowsTrayHost(
                icon_path=desktop_resource_path("worktrace.ico"),
                on_open=lambda: shell_holder["shell"].show_window(),
                on_exit=exit_application,
            )
            shell = DesktopShellController(
                window=window,
                tray=tray,
                initial_hidden=initial_hidden,
            )
            shell_holder["shell"] = shell
            _bind_shell_events(window, shell)
            instance_coordinator.bind_activation_handler(shell.show_window)
            shell.start()
            webview_profile_path = paths.base_dir / "webview-profile"
            webview_profile_path.mkdir(parents=True, exist_ok=True)

            def handle_webview_initialized() -> None:
                renderer = str(getattr(webview, "renderer", "") or "").lower()
                safe_renderer = (
                    renderer
                    if renderer in {"edgechromium", "cef", "qt", "gtk", "mshtml"}
                    else "unknown"
                )
                logging.info("webview renderer initialized renderer=%s", safe_renderer)
                if sys.platform.startswith("win") and renderer != "edgechromium":
                    fd_work_controller.mark_renderer_unavailable()
                    _show_blocking_startup_message(_RENDERER_UNAVAILABLE_MESSAGE)
                    return
                if services.fd_work.get_settings_status().get("enabled") is True:
                    threading.Thread(
                        target=lambda: services.fd_work.prepare_session(
                            show_login_if_required=True
                        ),
                        name="fd-work-session-prepare",
                        daemon=True,
                    ).start()

            webview.start(
                func=handle_webview_initialized,
                gui="edgechromium",
                private_mode=False,
                storage_path=str(webview_profile_path),
            )
        except Exception:
            logging.exception("webview start failed")
            return _report_startup_failure(
                missing_runtime_message(),
                background=background,
            )
        return 0
    except Exception:
        logging.exception("webview composition failed")
        return _report_startup_failure(
            "WorkTrace 启动失败，请重新打开应用。",
            background=background,
        )
    finally:
        instance_coordinator.stop_activation_listener()
        if services is not None:
            services.fd_work.shutdown()
        elif fd_work_controller is not None:
            fd_work_controller.shutdown()
        if shell is not None:
            shell.stop()
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
