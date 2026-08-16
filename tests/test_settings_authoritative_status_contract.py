from __future__ import annotations

import pytest

from tests.support.application import (
    FakeFDWorkCapability,
    FakeSettingsCapability,
    build_test_bridge,
)

pytestmark = [pytest.mark.integration, pytest.mark.db, pytest.mark.contract]


def _authoritative_status(*, clipboard: bool, launch: bool) -> dict[str, object]:
    return {
        "clipboard_capture_enabled": clipboard,
        "launch_at_login": {"supported": True, "enabled": launch},
    }


def _enabled_fd_work() -> FakeFDWorkCapability:
    fd_work = FakeFDWorkCapability()
    fd_work.enabled = True
    return fd_work


def test_clipboard_write_returns_complete_authoritative_settings_status(temp_db) -> None:
    settings = FakeSettingsCapability()
    settings.get_settings_privacy_status_return = {
        "ok": True,
        "status": _authoritative_status(clipboard=False, launch=True),
    }
    bridge = build_test_bridge(settings=settings, fd_work=_enabled_fd_work())

    result = bridge.set_clipboard_capture_enabled(False)

    assert result["ok"] is True
    assert result["status"]["clipboard_capture_enabled"] is False
    assert result["status"]["launch_at_login"] == {
        "supported": True,
        "enabled": True,
    }
    assert result["status"]["fd_work"]["enabled"] is True


def test_launch_write_preserves_other_settings_authority(temp_db) -> None:
    settings = FakeSettingsCapability()
    settings.set_launch_at_login_return = {
        "ok": True,
        "status": {"launch_at_login": {"supported": True, "enabled": True}},
    }
    settings.get_settings_privacy_status_return = {
        "ok": True,
        "status": _authoritative_status(clipboard=True, launch=True),
    }
    bridge = build_test_bridge(settings=settings, fd_work=_enabled_fd_work())

    result = bridge.set_launch_at_login(True)

    assert result["ok"] is True
    assert result["status"]["clipboard_capture_enabled"] is True
    assert result["status"]["launch_at_login"]["enabled"] is True
    assert result["status"]["fd_work"]["enabled"] is True


def test_recovery_failure_never_exposes_maintenance_as_full_settings_state(temp_db) -> None:
    settings = FakeSettingsCapability()
    settings.recover_database_maintenance_for_webview_return = {
        "ok": False,
        "error": "maintenance_recovery_not_verified",
        "maintenance": {
            "maintenance_in_progress": False,
            "maintenance_restored": False,
            "recovery_blocked": True,
        },
    }
    settings.get_settings_privacy_status_return = {
        "ok": True,
        "status": _authoritative_status(clipboard=True, launch=True),
    }
    bridge = build_test_bridge(settings=settings, fd_work=_enabled_fd_work())

    result = bridge.recover_database_maintenance()

    assert result["ok"] is False
    assert "maintenance" not in result
    assert result["status"]["clipboard_capture_enabled"] is True
    assert result["status"]["launch_at_login"]["enabled"] is True
    assert result["status"]["fd_work"]["enabled"] is True


def test_clear_all_replaces_lower_layer_partial_status_with_authority(temp_db) -> None:
    settings = FakeSettingsCapability()
    settings.clear_all_local_data_for_webview_return = {
        "ok": True,
        "message": "本地数据已清空",
        "maintenance": {"maintenance_restored": True},
        "status": {"clipboard_capture_enabled": False},
    }
    settings.get_settings_privacy_status_return = {
        "ok": True,
        "status": _authoritative_status(clipboard=False, launch=True),
    }
    bridge = build_test_bridge(settings=settings, fd_work=_enabled_fd_work())

    result = bridge.clear_all_local_data("清空本地数据")

    assert result["ok"] is True
    assert result["status"]["clipboard_capture_enabled"] is False
    assert result["status"]["launch_at_login"]["enabled"] is True
    assert result["status"]["fd_work"]["enabled"] is True
