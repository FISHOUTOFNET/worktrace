"""WebView UI entry point (default and only shipping UI)."""
from __future__ import annotations

import json
import logging
import sys
import threading
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any

from . import PRODUCT_DISPLAY_NAME, PRODUCT_NAME, config
from .collector.single_instance import get_application_instance_coordinator
from .desktop.install_bootstrap import consume_fd_work_install_intent
from .desktop.shell import DesktopShellController
from .desktop.update_shutdown import get_application_update_shutdown_coordinator
from .desktop.windows_icons import WindowsWindowIconHost
from .desktop.windows_tray import WindowsTrayHost
from .integrations.fd_work.helper_bridge import FDWorkHelperBridge
from .integrations.fd_work.interaction_coordinator import FDWorkInteractionCoordinator
from .integrations.fd_work.main_window_sink import FDWorkMainWindowSink
from .integrations.fd_work.page_adapter import FDWorkPageAdapter
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
    activated = instance_coordinator.signal_existing_instance()
    logging.info(
        "webview startup skipped: existing instance activation=%s",
        activated,
    )
    return 0


def _report_startup_failure(message: str, *, background: bool) -> int:
    branded_message = _brand_runtime_message(message)
    print(branded_message, file=sys.stderr)
    if _should_show_blocking_startup_message(background=background):
        _show_blocking_startup_message(branded_message)
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


def _navigation_brand_script() -> str:
    display_name = json.dumps(PRODUCT_DISPLAY_NAME, ensure_ascii=False)
    return f"""
(() => {{
    const brand = document.querySelector('.app-brand');
    if (!brand) return;
    const mark = brand.querySelector('.brand-mark');
    const label = brand.querySelector('.nav-label');
    if (label) label.textContent = {display_name};
    brand.setAttribute('aria-label', {display_name});
    const compactSidebar = window.matchMedia('(max-width: 959px)');
    const syncBrandMark = () => {{
        if (mark) mark.style.display = compactSidebar.matches ? '' : 'none';
    }};
    syncBrandMark();
    if (typeof compactSidebar.addEventListener === 'function') {{
        compactSidebar.addEventListener('change', syncBrandMark);
    }} else if (typeof compactSidebar.addListener === 'function') {{
        compactSidebar.addListener(syncBrandMark);
    }}

    // Settings shows controls and actionable exceptions, not a healthy-state
    // dashboard. Abnormal recovery remains in its dedicated recovery card.
    const healthSummary = document.getElementById('settings-health-summary');
    if (healthSummary) healthSummary.remove();

    // Avoid an absolute local-only claim: optional integrations can perform
    // user-initiated network operations while core work-trace data is local-first.
    const localStatus = document.querySelector('.topbar-local');
    if (localStatus) localStatus.textContent = '核心工作轨迹本地保存';

    const privacyAccept = document.getElementById('first-run-notice-accept-btn');
    if (privacyAccept) privacyAccept.textContent = '我已阅读并了解';

    // Privacy is an information/action entry, not an "accepted" status setting.
    const privacyButton = document.getElementById('settings-privacy-notice-btn');
    if (privacyButton) {{
        privacyButton.textContent = '查看《有迹隐私政策》';
        const row = privacyButton.closest('.setting-row');
        const copy = row ? row.querySelector('span') : null;
        if (copy) {{
            while (copy.firstChild) copy.removeChild(copy.firstChild);
            const title = document.createElement('strong');
            title.textContent = '隐私政策';
            const detail = document.createElement('small');
            detail.textContent = '了解有迹处理哪些数据、数据存储在哪里，以及如何管理这些数据。';
            copy.appendChild(title);
            copy.appendChild(detail);
        }}
    }}
}})();
""".strip()


def _apply_navigation_brand(window) -> None:
    try:
        window.evaluate_js(_navigation_brand_script())
    except Exception:
        logging.debug("navigation brand projection deferred", exc_info=True)


def _bind_shell_events(window, shell: DesktopShellController) -> None:
    events = getattr(window, "events", None)
    if events is None:
        return

    def handle_loaded() -> None:
        # The shell readiness marker must never wait on renderer-side scripting.
        # pywebview evaluate_js can synchronously wait on WebView2 when invoked
        # from the loaded event itself, so brand presentation is projected from
        # a daemon thread only after the shell has accepted the loaded state.
        shell.handle_window_loaded()
        threading.Thread(
            target=_apply_navigation_brand,
            args=(window,),
            name="trace-navigation-brand",
            daemon=True,
        ).start()

    events.closing += shell.handle_window_closing
    events.loaded += handle_loaded


_RENDERER_UNAVAILABLE_MESSAGE = (
    f"{PRODUCT_NAME} 无法使用 Microsoft Edge WebView2 renderer。"
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
        return _report_startup_failure(str(exc), background=background)
    logging.info("pywebview_runtime version=%s", _pywebview_runtime_version())

    runtime = AppRuntime(paths)
    shell: DesktopShellController | None = None
    fd_work_controller: FDWorkWindowController | None = None
    services = None
    instance_coordinator = get_application_instance_coordinator()
    update_shutdown = get_application_update_shutdown_coordinator()
    update_shutdown_prepared = False

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

        fd_work_main_sink = FDWorkMainWindowSink(deliver_asynchronously=True)
        fd_work_page_adapter = FDWorkPageAdapter()
        fd_work_helper_bridge = FDWorkHelperBridge(
            action_result_sink=fd_work_page_adapter
        )
        fd_work_controller = FDWorkWindowController(
            webview,
            page_adapter=fd_work_page_adapter,
            helper_bridge=fd_work_helper_bridge,
        )
        fd_work_coordinator = FDWorkInteractionCoordinator(
            window_controller=fd_work_controller,
            page_adapter=fd_work_page_adapter,
        )
        fd_work_helper_bridge.bind_coordinator(fd_work_coordinator)
        services = build_application_services(
            runtime,
            fd_work_interaction_coordinator=fd_work_coordinator,
            paths=paths,
        )
        services.fd_work.bind_status_callback(fd_work_main_sink.status_changed)
        services.fd_work.bind_picker_result_callback(fd_work_main_sink.picker_result)
        if consume_fd_work_install_intent(services.fd_work):
            logging.info("FD Work enabled from installer bootstrap")
        app_control = services.app_control
        startup_result: dict[str, Any] = {"ok": False}
        try:
            startup_result = app_control.start_if_authorized(pre_start=True)
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
        index_path = resource_path("index_fd_work_v5.html")
        initial_hidden = background and _background_start_allowed(
            services,
            startup_result,
        )
        try:
            window = webview.create_window(
                title=PRODUCT_DISPLAY_NAME,
                url=_versioned_resource_url(index_path),
                js_api=bridge.shipping_api,
                width=1080,
                height=720,
                min_size=(800, 540),
                hidden=initial_hidden,
                focus=not initial_hidden,
            )
            bridge.set_window(window)
            fd_work_main_sink.bind_window(window)
            shell_holder: dict[str, DesktopShellController] = {}
            exit_lock = threading.Lock()
            exit_requested = False

            def exit_application() -> None:
                nonlocal exit_requested
                with exit_lock:
                    if exit_requested:
                        return
                    exit_requested = True
                logging.info("application exit requested")
                try:
                    services.fd_work.shutdown()
                finally:
                    shell_holder["shell"].exit_application()

            icon_path = desktop_resource_path("worktrace.ico")
            tray = WindowsTrayHost(
                icon_path=icon_path,
                on_open=lambda: shell_holder["shell"].show_window(),
                on_exit=exit_application,
                on_session_end=exit_application,
            )
            window_icons = WindowsWindowIconHost(
                window_title=PRODUCT_DISPLAY_NAME,
                icon_path=icon_path,
            )
            shell = DesktopShellController(
                window=window,
                tray=tray,
                initial_hidden=initial_hidden,
                window_icons=window_icons,
                collection_active_provider=lambda: app_control.is_collection_active(),
            )
            shell_holder["shell"] = shell
            fd_work_controller.bind_main_focus_callback(shell.show_window)
            _bind_shell_events(window, shell)
            instance_coordinator.bind_activation_handler(shell.show_window)
            if update_shutdown_prepared:
                update_shutdown.bind_shutdown_handler(exit_application)
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
                fd_work_main_sink.mark_ready()
                fd_work_controller.on_renderer_initialized(safe_renderer)
                fd_work_main_sink.status_changed(services.fd_work.get_settings_status())

            webview.start(
                func=handle_webview_initialized,
                gui="edgechromium",
                http_server=True,
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
            f"{PRODUCT_NAME} 启动失败，请重新打开应用。",
            background=background,
        )
    finally:
        instance_coordinator.stop_activation_listener()
        update_shutdown.stop_listener()
        if "fd_work_main_sink" in locals():
            fd_work_main_sink.mark_unavailable()
        if services is not None:
            services.fd_work.shutdown()
        elif fd_work_controller is not None:
            fd_work_controller.shutdown()
        if shell is not None:
            shell.stop()
        runtime.shutdown()
        update_shutdown.close()


if __name__ == "__main__":
    raise SystemExit(main())
