from __future__ import annotations

import pytest

from worktrace.api import settings_api
from worktrace.api.app_api import ApplicationControlService
from worktrace.runtime.app_runtime import RuntimeStartResult
from worktrace.services import privacy_gate_service

pytestmark = [pytest.mark.unit, pytest.mark.contract]


class _Runtime:
    def __init__(self) -> None:
        self.start_calls = 0

    def start_authorized_collection(self) -> RuntimeStartResult:
        self.start_calls += 1
        return RuntimeStartResult(
            ok=True,
            collector_ready=True,
            workers={},
            already_running=False,
            degraded=False,
            error_code=None,
        )

    def pause_collection_now(self):
        return {"ok": True, "pause_pending": False}

    def set_clipboard_capture_enabled(self, enabled: bool) -> bool:
        return True

    def request_shutdown(self) -> None:
        return None


class _Maintenance:
    def __init__(self, blocked_reason: str | None) -> None:
        self.blocked_reason = blocked_reason


class _UnreadableMaintenance:
    @property
    def blocked_reason(self) -> str | None:
        raise RuntimeError("maintenance_state_unavailable")


def test_fail_closed_latch_blocks_resume_before_runtime_start(monkeypatch):
    runtime = _Runtime()
    control = ApplicationControlService(
        runtime,
        _Maintenance("secure_import_operation"),
    )
    monkeypatch.setattr(
        privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: True,
    )

    result = control.start_collection_after_privacy_gate()

    assert result == {
        "ok": False,
        "error": "maintenance_recovery_required",
        "message": "维护状态尚未恢复，暂不能开始记录",
    }
    assert runtime.start_calls == 0


def test_unreadable_maintenance_state_fails_closed(monkeypatch):
    runtime = _Runtime()
    control = ApplicationControlService(runtime, _UnreadableMaintenance())
    monkeypatch.setattr(
        privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: True,
    )

    result = control.start_collection_after_privacy_gate()

    assert result["error"] == "maintenance_recovery_required"
    assert runtime.start_calls == 0


def test_cleared_maintenance_state_allows_runtime_start(monkeypatch):
    runtime = _Runtime()
    control = ApplicationControlService(runtime, _Maintenance(None))
    monkeypatch.setattr(
        privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: True,
    )

    result = control.start_collection_after_privacy_gate()

    assert result["ok"] is True
    assert runtime.start_calls == 1


def test_toggle_does_not_clear_user_pause_while_fail_closed(monkeypatch):
    runtime = _Runtime()
    control = ApplicationControlService(
        runtime,
        _Maintenance("clear_database_operation"),
    )
    monkeypatch.setattr(
        privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: True,
    )
    monkeypatch.setattr(
        control,
        "get_collection_status",
        lambda: {
            "ok": True,
            "status": "paused",
            "paused": True,
            "display": "已暂停",
        },
    )
    cleared: list[bool] = []
    monkeypatch.setattr(
        settings_api,
        "set_user_paused",
        lambda value: cleared.append(bool(value)),
    )

    result = control.toggle_collection()

    assert result["error"] == "maintenance_recovery_required"
    assert runtime.start_calls == 0
    assert cleared == []
