"""Optional WebView UI entry point (Phase 0B spike).

Starts a minimal pywebview shell that talks to ``worktrace.api`` through
``worktrace.webview_ui.bridge.WebViewBridge``. The default entry point
``python -m worktrace.main`` (Tkinter UI) is unchanged.

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
from .api import app_api
from .runtime.app_runtime import AppRuntime
from .webview_ui.bridge import WebViewBridge


def setup_logging(log_path) -> None:
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def resource_path(relative: str) -> Path:
    """Resolve a webview_ui resource path.

    Works for source runs. PyInstaller packaging will be handled in Phase 0C
    via ``sys._MEIPASS``; the helper is written to prefer that base when
    present so the packaged exe can locate bundled resources.
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


def main() -> int:
    paths = config.resolve_paths()
    config.ensure_directories(paths)
    setup_logging(paths.log_path)
    logging.info("webview ui startup")

    webview = _check_pywebview_available()

    runtime = AppRuntime(paths)
    runtime.initialize()
    app_api.set_runtime(runtime)

    bridge = WebViewBridge()
    index_path = resource_path("index.html")

    try:
        webview.create_window(
            title="WorkTrace",
            url=str(index_path),
            js_api=bridge,
            width=1080,
            height=720,
            min_size=(800, 540),
        )
        webview.start()
    finally:
        runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
