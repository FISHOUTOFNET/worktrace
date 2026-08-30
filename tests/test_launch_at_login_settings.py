from __future__ import annotations

import sys
from pathlib import Path

import pytest

from worktrace.api.application_capabilities import SettingsApplicationService
from worktrace.api.application_lifecycle import ApplicationDataLifecycle
from worktrace.platforms.windows_startup import (
    TASK_NAME,
    StartupTaskSpec,
    WindowsStartupRegistration,
)

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.contract]


class FakeRegistry:
    def __init__(self, value: str | None = None, *, fail_delete: bool = False) -> None:
        self.value = value
        self.fail_delete = fail_delete

    def read_run_value(self, _name: str) -> str | None:
        return self.value

    def delete_run_value(self, _name: str) -> None:
        if self.fail_delete:
            raise OSError("denied")
        self.value = None


class FakeScheduler:
    def __init__(self, *, configured: bool = False, fail_register: bool = False) -> None:
        self.exists_value = configured
        self.configured = configured
        self.fail_register = fail_register

    def exists(self, _name: str) -> bool:
        return self.exists_value

    def is_configured(self, _name: str, _spec: StartupTaskSpec) -> bool:
        return self.exists_value and self.configured

    def register(self, name: str, _spec: StartupTaskSpec) -> None:
        assert name == TASK_NAME
        if self.fail_register:
            raise OSError("denied")
        self.exists_value = True
        self.configured = True

    def delete(self, name: str) -> None:
        assert name == TASK_NAME
        self.exists_value = False
        self.configured = False


def _service(
    monkeypatch,
    *,
    registry: FakeRegistry | None = None,
    scheduler: FakeScheduler | None = None,
) -> SettingsApplicationService:
    monkeypatch.setattr(sys, "platform", "win32")
    registration = WindowsStartupRegistration(
        executable_path=Path(r"C:\Program Files With Spaces\Trace.exe"),
        registry=registry or FakeRegistry(),
        scheduler=scheduler or FakeScheduler(),
    )
    return SettingsApplicationService(
        registration, data_lifecycle=ApplicationDataLifecycle(())
    )


def test_settings_status_contains_authoritative_launch_at_login(monkeypatch, temp_db) -> None:
    result = _service(
        monkeypatch, scheduler=FakeScheduler(configured=True)
    ).get_settings_privacy_status()
    assert result["ok"] is True
    assert result["status"]["launch_at_login"] == {
        "supported": True,
        "enabled": True,
    }


def test_launch_at_login_write_failure_returns_actual_rollback_state(
    monkeypatch, temp_db
) -> None:
    service = _service(monkeypatch, scheduler=FakeScheduler(fail_register=True))

    result = service.set_launch_at_login(True)

    assert result["ok"] is False
    assert result["status"]["launch_at_login"] == {
        "supported": True,
        "enabled": False,
    }


def test_launch_at_login_success_returns_full_updated_status(monkeypatch, temp_db) -> None:
    service = _service(monkeypatch)

    result = service.set_launch_at_login(True)

    assert result["ok"] is True
    assert result["status"]["launch_at_login"]["enabled"] is True
    assert "clipboard_capture_enabled" in result["status"]
