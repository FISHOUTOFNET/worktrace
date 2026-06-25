from __future__ import annotations

import logging
import sys
from typing import Sequence


def setup_logging(log_path) -> None:
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def _has_webview_compat_flag(argv: Sequence[str]) -> bool:
    """Detect the legacy ``--webview`` opt-in flag.

    Phase 1 made WebView the default UI, so the flag is now a no-op kept only
    for backwards compatibility. It must not change behavior: ``main([])``
    and ``main(["--webview"])`` both start the WebView UI.
    """
    return "--webview" in argv


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # ``--webview`` is accepted as a harmless compatibility flag and does not
    # alter behavior. WebView is the only shipping UI as of Phase 1.
    _has_webview_compat_flag(args)

    # WebView is the sole shipping UI. There is no Tkinter fallback: a missing
    # WebView2 Runtime or pywebview dependency is a blocking error that exits
    # with a non-zero status and a clear message.
    from .webview_main import main as webview_main

    return webview_main()


if __name__ == "__main__":
    raise SystemExit(main())
