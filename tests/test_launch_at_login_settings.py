from __future__ import annotations

from pathlib import Path

import pytest

from worktrace.api.application_capabilities import SettingsApplicationService
from worktrace.platforms.windows_startup import WindowsStartupRegistration

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.contract]


class FakeRegistry:
    def __init__(self, value: str | None = None, *, fail_write: bool = False) -> None:
        self.value = value
        self.fail_write = fail_write

    def read_run_value(self, _name: str) -> str | None:
        return self.value

    def write_run_value(self, _name: str, value: str) -> None:
        if self.fail_write:
            raise OSError("denied")
        self.value = value

    def delete_run_value(self, _name: str) -> None:
        self.value = None


def _service(registry: FakeRegistry) -> SettingsApplicationService:
    registration = WindowsStartupRegistration(
        executable_path=Path(r"C:\Program Files With Spaces\WorkTrace.exe"),
        registry=registry,
    )
    return SettingsApplicationService(registration)


def test_settings_status_contains_authoritative_launch_at_login(temp_db) -> None:
    registry = FakeRegistry(
        r'"C:\Program Files With Spaces\WorkTrace.exe" --background'
    )
    result = _service(registry).get_settings_privacy_status()
    assert result["ok"] is True
    assert result["status"]["launch_at_login"] == {
        "supported": True,
        "enabled": True,
    }


def test_launch_at_login_write_failure_returns_actual_rollback_state(temp_db) -> None:
    service = _service(FakeRegistry(fail_write=True))

    result = service.set_launch_at_login(True)

    assert result["ok"] is False
    assert result["status"]["launch_at_login"] == {
        "supported": True,
        "enabled": False,
    }


def test_launch_at_login_success_returns_full_updated_status(temp_db) -> None:
    service = _service(FakeRegistry())

    result = service.set_launch_at_login(True)

    assert result["ok"] is True
    assert result["status"]["launch_at_login"]["enabled"] is True
    assert "clipboard_capture_enabled" in result["status"]

