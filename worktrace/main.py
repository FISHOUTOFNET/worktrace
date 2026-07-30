from __future__ import annotations

import argparse
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


def main(argv: Sequence[str] | None = None) -> int:
    # WebView is the sole shipping UI (no Tkinter fallback); a missing WebView2
    # Runtime or pywebview dependency is a blocking error that exits non-zero.
    from .webview_main import main as webview_main

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--background", action="store_true")
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    options, _unknown = parser.parse_known_args(raw_argv)
    return webview_main(background=options.background)


if __name__ == "__main__":
    raise SystemExit(main())
