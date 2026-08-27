from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import pytest

from worktrace.logging_config import configure_file_logging

pytestmark = pytest.mark.unit


def test_application_file_logging_is_bounded_without_removing_host_handlers(tmp_path):
    root = logging.getLogger()
    host_handler = logging.NullHandler()
    root.addHandler(host_handler)
    handler = None
    try:
        handler = configure_file_logging(
            tmp_path / "worktrace.log",
            max_bytes=1024,
            backup_count=2,
        )
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == 1024
        assert handler.backupCount == 2
        assert host_handler in root.handlers
    finally:
        if handler is not None and handler in root.handlers:
            root.removeHandler(handler)
            handler.close()
        if host_handler in root.handlers:
            root.removeHandler(host_handler)
