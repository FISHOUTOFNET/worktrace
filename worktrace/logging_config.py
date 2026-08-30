"""Bounded application file logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 4
_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_OWNED_MARKER = "_worktrace_owned_file_handler"


def configure_file_logging(
    log_path,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    backup_count: int = _DEFAULT_BACKUP_COUNT,
) -> RotatingFileHandler:
    """Install one WorkTrace-owned rotating handler without disturbing host handlers."""

    root = logging.getLogger()
    for handler in tuple(root.handlers):
        if getattr(handler, _OWNED_MARKER, False):
            root.removeHandler(handler)
            handler.close()

    path = Path(log_path)
    handler = RotatingFileHandler(
        path,
        maxBytes=max(1, int(max_bytes)),
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
        delay=True,
    )
    setattr(handler, _OWNED_MARKER, True)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return handler


__all__ = ["configure_file_logging"]
