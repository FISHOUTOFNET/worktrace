"""Contracts for the frozen executable's earliest startup boundary."""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.serial]

ROOT = Path(__file__).resolve().parents[1]
ENTRY_PATH = ROOT / "scripts" / "pyinstaller_entry.py"


def test_frozen_entry_initializes_diagnostics_before_application_import() -> None:
    source = ENTRY_PATH.read_text(encoding="utf-8")

    assert '_STARTUP_LOG_NAME = "startup.log"' in source
    assert "_open_startup_log()" in source
    assert "_attach_windowed_streams(stream)" in source
    assert "sys.stdout is None" in source
    assert "sys.stderr is None" in source
    assert source.index("_open_startup_log()") < source.index("from worktrace.main import main")


def test_frozen_entry_records_uncaught_startup_exceptions() -> None:
    source = ENTRY_PATH.read_text(encoding="utf-8")

    assert "except BaseException:" in source
    assert '"unhandled startup exception"' in source
    assert "traceback.print_exc(file=stream)" in source
    assert "_show_fatal_startup_message" in source
    assert "MessageBoxW" in source


def test_nonzero_startup_exit_is_visible_only_for_interactive_foreground_mode() -> None:
    source = ENTRY_PATH.read_text(encoding="utf-8")

    assert 'background = "--background" in argv' in source
    assert '_MAINTENANCE_SHUTDOWN_ARGUMENT = "--shutdown-for-maintenance"' in source
    assert "maintenance_control = _MAINTENANCE_SHUTDOWN_ARGUMENT in argv" in source
    assert "if exit_code != 0:" in source
    assert "if not background and not maintenance_control:" in source
    assert "_format_fatal_message(log_path=log_path, exit_code=exit_code)" in source


def test_probe_helper_keeps_its_closed_stdout_stderr_contract() -> None:
    source = ENTRY_PATH.read_text(encoding="utf-8")

    helper_start = source.index("def _run_windows_probe_helper")
    helper_end = source.index("def _run_application", helper_start)
    helper = source[helper_start:helper_end]
    assert 'open(1, "w", encoding="utf-8", closefd=False)' in helper
    assert 'open(2, "w", encoding="utf-8", closefd=False)' in helper
