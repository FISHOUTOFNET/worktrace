from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.packaging, pytest.mark.contract, pytest.mark.parallel_safe]

ROOT = Path(__file__).resolve().parents[1]


def test_maintenance_shutdown_command_bypasses_webview_startup(monkeypatch) -> None:
    import worktrace.main as main_mod
    import worktrace.desktop.update_shutdown as shutdown_mod

    calls: list[float] = []

    def request(*, timeout_seconds: float) -> bool:
        calls.append(timeout_seconds)
        return True

    monkeypatch.setattr(shutdown_mod, "request_running_instance_shutdown", request)
    with patch("worktrace.webview_main.main") as webview_main:
        assert main_mod.main(["--shutdown-for-maintenance"]) == 0
        webview_main.assert_not_called()

    assert calls == [20.0]


def test_maintenance_shutdown_timeout_returns_nonzero_without_starting_webview(
    monkeypatch,
) -> None:
    import worktrace.main as main_mod
    import worktrace.desktop.update_shutdown as shutdown_mod

    monkeypatch.setattr(
        shutdown_mod,
        "request_running_instance_shutdown",
        lambda **_kwargs: False,
    )
    with patch("worktrace.webview_main.main") as webview_main:
        assert main_mod.main(["--shutdown-for-maintenance"]) == 5
        webview_main.assert_not_called()


def test_frozen_bootstrap_keeps_maintenance_control_noninteractive() -> None:
    source = (ROOT / "scripts" / "pyinstaller_entry.py").read_text(encoding="utf-8")

    assert '_MAINTENANCE_SHUTDOWN_ARGUMENT = "--shutdown-for-maintenance"' in source
    assert "maintenance_control = _MAINTENANCE_SHUTDOWN_ARGUMENT in argv" in source
    assert source.count("not background and not maintenance_control") >= 2
