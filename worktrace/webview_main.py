"""WebView UI entry point (Phase 1: default and only shipping UI).

Starts a pywebview shell that talks to ``worktrace.api`` through
``worktrace.webview_ui.bridge.WebViewBridge``. As of Phase 1, this is the
default entry point used by ``python -m worktrace.main`` and by the packaged
``WorkTrace.exe``. There is no Tkinter fallback: a missing WebView2 Runtime
or pywebview dependency is a blocking error that exits with a non-zero code.

This module mirrors the startup shape of ``worktrace.main``: resolve paths,
initialize logging, create and initialize ``AppRuntime``, register it with
``app_api``, then run the WebView main loop. On exit, ``runtime.shutdown`` is
called so the collector thread, folder-index worker, and single-instance lock
are released.

Importing this module does not start the GUI. Call ``main()`` to start.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from . import config
from .api import app_api, settings_api
from .runtime.app_runtime import AppRuntime
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
    """Resolve a webview_ui resource path.

    Works for source runs and PyInstaller-packaged runs. When frozen,
    ``sys._MEIPASS`` is the bundle root and the resources are bundled under
    ``worktrace/webview_ui/`` (see WorkTrace.spec).
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "worktrace" / "webview_ui" / relative
    return Path(__file__).resolve().parent / "webview_ui" / relative


def _check_pywebview_available() -> Any:
    """Import pywebview lazily and return the module.

    Returns a clear error if pywebview is not installed so the caller can show
    a helpful message instead of an ImportError traceback.
    """
    try:
        import webview

        return webview
    except ImportError as exc:
        raise RuntimeError(
            "pywebview 未安装，无法启动 WebView UI。"
            "请运行 pip install pywebview>=5.0 后重试。"
        ) from exc


def _report_runtime_missing() -> int:
    """Print a clear message when WebView2 Runtime is missing and exit.

    Does not raise; returns a non-zero exit code so the caller can surface
    the message to the user. As of Phase 1 WorkTrace ships only the WebView
    UI: the user must install the WebView2 Runtime and restart WorkTrace.
    """
    msg = missing_runtime_message()
    print(msg, file=sys.stderr)
    logging.error("webview startup aborted: WebView2 Runtime missing")
    return 2


def main() -> int:
    paths = config.resolve_paths()
    config.ensure_directories(paths)
    setup_logging(paths.log_path)
    logging.info("webview ui startup")

    # Pre-flight: if we can confidently detect the runtime is missing on
    # Windows, fail fast with a clear message instead of a pywebview traceback.
    if detect_webview2_runtime() == "missing":
        return _report_runtime_missing()

    try:
        webview = _check_pywebview_available()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    runtime = AppRuntime(paths)
    runtime.initialize()
    app_api.set_runtime(runtime)

    # Phase 6E first-run startup gate: mirror the legacy Tkinter
    # ``_startup_privacy_gate`` semantics. Only auto-start the collector
    # when the user has already accepted the first-run privacy notice.
    # If the notice has not been accepted, leave the collector stopped;
    # the frontend first-run overlay will display the notice and, on
    # accept, call ``accept_first_run_notice`` through the bridge which
    # starts the collector. Fail closed on read error: do not start the
    # collector, log, but do not block WebView startup (the frontend
    # will call ``get_first_run_notice`` and surface the error).
    try:
        notice_accepted = settings_api.first_run_notice_accepted()
    except Exception:
        logging.exception(
            "webview startup: first_run_notice_accepted read failed; "
            "not starting collector (fail closed)"
        )
        notice_accepted = False
    if notice_accepted:
        try:
            app_api.start_collector()
        except Exception:
            logging.exception(
                "webview startup: collector start failed after first-run "
                "notice already accepted; user can retry via sidebar toggle"
            )

    bridge = WebViewBridge()
    index_path = resource_path("index.html")

    try:
        # Phase 4B: capture the window so the bridge can open a native save
        # dialog for the CSV export. ``create_window`` returns the Window
        # object before ``start()`` runs the main loop; the dialog is only
        # invoked later from a JS callback (after the WebView is live), so
        # injecting the reference here is safe and does not start the GUI.
        window = webview.create_window(
            title="WorkTrace",
            url=str(index_path),
            js_api=bridge,
            width=1080,
            height=720,
            min_size=(800, 540),
        )
        bridge.set_window(window)
        webview.start()
    except Exception:
        # pywebview raises when the WebView2 backend cannot initialize even
        # though the registry check passed (e.g. corrupt install). Surface a
        # clear message without a traceback.
        logging.exception("webview start failed")
        print(missing_runtime_message(), file=sys.stderr)
        return 2
    finally:
        runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
