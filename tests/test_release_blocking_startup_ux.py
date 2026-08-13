"""Release-blocking installer and packaged startup UX contracts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = ROOT / "installer" / "WorkTrace.iss"


def test_fd_work_availability_notice_is_bound_to_the_task_label() -> None:
    source = INSTALLER_PATH.read_text(encoding="utf-8")
    fd_work_line = next(
        line for line in source.splitlines() if line.startswith("Name: fdwork;")
    )

    assert 'Description: "启用 FD Work 插件（仅方达律师事务所可用）"' in fd_work_line
    assert "FDWorkNotice" not in source
    assert "TasksList.Height :=" not in source


def test_packaged_foreground_runtime_missing_is_user_visible(monkeypatch, capsys) -> None:
    import worktrace.webview_main as webview_main

    shown_messages: list[str] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(webview_main, "missing_runtime_message", lambda: "runtime missing")
    monkeypatch.setattr(
        webview_main,
        "_show_blocking_startup_message",
        shown_messages.append,
    )

    result = webview_main._report_runtime_missing(background=False)

    assert result == 2
    assert shown_messages == ["runtime missing"]
    assert "runtime missing" in capsys.readouterr().err


def test_source_foreground_runtime_missing_keeps_console_only(monkeypatch) -> None:
    import worktrace.webview_main as webview_main

    shown_messages: list[str] = []
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(webview_main, "missing_runtime_message", lambda: "runtime missing")
    monkeypatch.setattr(
        webview_main,
        "_show_blocking_startup_message",
        shown_messages.append,
    )

    assert webview_main._report_runtime_missing(background=False) == 2
    assert shown_messages == []


def test_packaged_foreground_generic_startup_failure_is_user_visible(
    monkeypatch,
) -> None:
    import worktrace.webview_main as webview_main

    shown_messages: list[str] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        webview_main,
        "_show_blocking_startup_message",
        shown_messages.append,
    )

    assert webview_main._report_startup_failure("startup failed", background=False) == 2
    assert shown_messages == ["startup failed"]
