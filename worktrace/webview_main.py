"""WebView UI entry point (default and only shipping UI)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from . import config
from .api.app_api import ApplicationControlService
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


def _check_pywebview_available() -> Any:
    try:
        import webview
        return webview
    except ImportError as exc:
        raise RuntimeError(
            "pywebview 未安装，无法启动 WebView UI。"
            "请运行 pip install pywebview>=5.0 后重试。"
        ) from exc


def _report_runtime_missing() -> int:
    msg = missing_runtime_message()
    print(msg, file=sys.stderr)
    logging.error("webview startup aborted: WebView2 Runtime missing")
    return 2


def _report_already_running() -> int:
    message = "WorkTrace 已在运行。"
    print(message, file=sys.stderr)
    logging.info("webview startup skipped: application instance already running")
    return 0


def main() -> int:
    paths = config.resolve_paths()
    config.ensure_directories(paths)
    setup_logging(paths.log_path)
    logging.info("webview ui startup")

    if detect_webview2_runtime() == "missing":
        return _report_runtime_missing()
    try:
        webview = _check_pywebview_available()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    runtime = AppRuntime(paths)
    if runtime.initialize() is False:
        return _report_already_running()
    services = build_application_services(runtime)
    app_control = ApplicationControlService(runtime)

    try:
        try:
            startup_result = app_control.start_collection_after_privacy_gate()
            if not startup_result.get("ok"):
                logging.error(
                    "collector startup rejected error=%s",
                    startup_result.get("error", "unknown"),
                )
            elif startup_result.get("background_worker_degraded"):
                logging.warning("collector started with background worker degradation")
        except Exception:
            logging.exception(
                "webview startup: authorized startup failed; user can retry"
            )

        bridge = WebViewBridge(services)
        index_path = resource_path("index.html")
        try:
            window = webview.create_window(
                title="WorkTrace",
                url=str(index_path),
                js_api=bridge.shipping_api,
                width=1080,
                height=720,
                min_size=(800, 540),
            )
            bridge.set_window(window)
            webview.start()
        except Exception:
            logging.exception("webview start failed")
            print(missing_runtime_message(), file=sys.stderr)
            return 2
        return 0
    finally:
        runtime.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
