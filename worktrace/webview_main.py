"""WebView UI entry point (default and only shipping UI)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from . import config
from .collector.single_instance import (
    get_application_instance_coordinator,
    signal_existing_instance,
)
from .desktop.shell import DesktopShellController
from .desktop.windows_tray import WindowsTrayHost
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


def _report_already_running() -> int:
    activated = signal_existing_instance()
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
    try:
        initialized = runtime.initialize()
    except Exception:
        logging.exception("runtime initialization failed")
        return _report_startup_failure(
            "WorkTrace 初始化失败，请打开应用处理后重试。",
            background=background,
        )
    if initialized is False:
        return _report_already_running()
    shell: DesktopShellController | None = None
    instance_coordinator = get_application_instance_coordinator()

    try:
        services = build_application_services(runtime)
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
            shell_holder: dict[str, DesktopShellController] = {}
            tray = WindowsTrayHost(
                icon_path=desktop_resource_path("worktrace.ico"),
                on_open=lambda: shell_holder["shell"].show_window(),
                on_exit=lambda: shell_holder["shell"].exit_application(),
            )
            shell = DesktopShellController(
                window=window,
                tray=tray,
                initial_hidden=initial_hidden,
            )
            shell_holder["shell"] = shell
            _bind_shell_events(window, shell)
            shell.start()
            instance_coordinator.start_activation_listener(shell.show_window)
            webview.start()
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
        if shell is not None:
            shell.stop()
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
