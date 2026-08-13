from __future__ import annotations

import threading
from pathlib import Path

import pytest

from worktrace.desktop.windows_tray import WindowsTrayHost

pytestmark = [pytest.mark.packaging, pytest.mark.contract]


def test_query_end_session_allows_windows_shutdown_and_requests_exit_once() -> None:
    requested = threading.Event()
    calls = 0

    def on_session_end() -> None:
        nonlocal calls
        calls += 1
        requested.set()

    tray = WindowsTrayHost(
        icon_path=Path("unused.ico"),
        on_open=lambda: None,
        on_exit=lambda: None,
        on_session_end=on_session_end,
    )

    assert tray._on_query_end_session(0, 0, 0, 0) == 1
    assert requested.wait(1.0)
    assert tray._on_end_session(0, 0, 1, 0) == 0
    assert calls == 1


def test_cancelled_end_session_does_not_create_a_new_exit_request() -> None:
    calls = 0

    def on_session_end() -> None:
        nonlocal calls
        calls += 1

    tray = WindowsTrayHost(
        icon_path=Path("unused.ico"),
        on_open=lambda: None,
        on_exit=lambda: None,
        on_session_end=on_session_end,
    )

    assert tray._on_end_session(0, 0, 0, 0) == 0
    assert calls == 0
