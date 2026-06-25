from __future__ import annotations

import logging
import sys
from typing import Sequence

from . import config
from .api import app_api
from .runtime.app_runtime import AppRuntime
from .ui.app import WorkTraceApp


def setup_logging(log_path) -> None:
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def _wants_webview(argv: Sequence[str]) -> bool:
    return "--webview" in argv


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if _wants_webview(args):
        # Delegate to the optional WebView entry point. Default Tkinter UI is
        # unchanged; --webview is an explicit opt-in for the spike.
        from .webview_main import main as webview_main

        return webview_main()

    paths = config.resolve_paths()
    config.ensure_directories(paths)
    setup_logging(paths.log_path)
    logging.info("app startup")

    runtime = AppRuntime(paths)
    runtime.initialize()
    app_api.set_runtime(runtime)

    try:
        app = WorkTraceApp()
        app.mainloop()
    finally:
        runtime.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
