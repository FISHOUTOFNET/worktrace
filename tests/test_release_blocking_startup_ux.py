"""Release-blocking installer and packaged startup UX contracts."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = ROOT / "installer" / "WorkTrace.iss"


def test_fd_work_availability_notice_is_red_and_bound_to_tasks_page() -> None:
    source = INSTALLER_PATH.read_text(encoding="utf-8")
    fd_work_line = next(
        line for line in source.splitlines() if line.startswith("Name: fdwork;")
    )

    assert 'Description: "启用 FD Work 插件"' in fd_work_line
    assert "Flags: unchecked" not in fd_work_line
    assert "FDWorkTaskNotice: TNewStaticText;" in source
    assert "FDWorkTaskNotice.Parent := WizardForm.SelectTasksPage;" in source
    assert (
        "'FD Work 仅方达律师事务所用户可用；非方达用户请取消勾选。';"
        in source
    )
    assert "FDWorkTaskNotice.Font.Color := clRed;" in source


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
