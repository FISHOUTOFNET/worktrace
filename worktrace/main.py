from __future__ import annotations

import logging
from typing import Sequence


def setup_logging(log_path) -> None:
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    # WebView is the sole shipping UI (no Tkinter fallback); a missing WebView2
    # Runtime or pywebview dependency is a blocking error that exits non-zero.
    from .webview_main import main as webview_main

    return webview_main()


if __name__ == "__main__":
    raise SystemExit(main())
