from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[1]


def _webview_entry_source() -> str:
    return (REPO_ROOT / "worktrace" / "webview_main.py").read_text(encoding="utf-8")


def _run_webview_ui_source() -> str:
    source = _webview_entry_source()
    start = source.index("def _run_webview_ui(")
    end = source.index("\ndef _wait_after_failed_headless_ui", start)
    return source[start:end]


def test_first_window_path_has_no_auxiliary_webview_or_shell_readiness_gate():
    source = _run_webview_ui_source()
    callback_start = source.index("        def handle_webview_initialized() -> None:")
    before_callback = source[:callback_start]

    assert before_callback.count("webview.create_window(") == 1
    assert "prepare_window_before_start" not in before_callback
    assert "shell.start()" not in before_callback


def test_auxiliary_shell_and_deferred_fd_work_prepare_only_after_webview_start_enters():
    source = _run_webview_ui_source()
    callback_start = source.index("        def handle_webview_initialized() -> None:")
    webview_start = source.index("        webview.start(", callback_start)
    callback = source[callback_start:webview_start]

    assert "shell.start()" in callback
    assert "services.fd_work.prepare_session(" in callback
    assert "runtime_started_before_renderer" in callback


def test_main_window_load_has_elapsed_startup_marker():
    source = _webview_entry_source()

    assert '"startup stage=main_window_loaded elapsed_ms=%s"' in source
