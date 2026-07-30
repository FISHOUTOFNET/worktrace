"""DTO contract tests for ApplicationControlService.accept_privacy_notice_and_start.

Verifies that the unified privacy-accept + collector-start DTO carries the
exact key set and field types across all four branches:
  1. full success (accepted + collector started)
  2. accepted but maintenance blocked
  3. accepted but collector start raised
  4. authorization persistence failure
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

import pytest

from worktrace.api import settings_api
from worktrace.api.app_api import ApplicationControlService
from worktrace.runtime.contracts import RuntimeStartResult
from worktrace.services import privacy_gate_service
from worktrace.services.database_maintenance_service import (
    MaintenanceInProgressError,
)
from worktrace.write_gate import DATABASE_RECOVERY_ERROR

pytestmark = [
    pytest.mark.unit,
    pytest.mark.contract,
    pytest.mark.security_privacy,
    pytest.mark.collector_runtime,
]

# Exact key set every branch must return — no more, no fewer.
_DTO_KEYS = {
    "ok",
    "accepted",
    "collector_started",
    "collector_status",
    "error_code",
    "message",
}

_COLLECTOR_STATUS_KEYS = {"status", "paused", "display"}


class _Runtime:
    """Minimal runtime fake; start_authorized_collection can be overridden."""

    def __init__(self, start_side_effect: Any = None) -> None:
        self._start_side_effect = start_side_effect

    def start_authorized_collection(self) -> RuntimeStartResult:
        if isinstance(self._start_side_effect, Exception):
            raise self._start_side_effect
        if isinstance(self._start_side_effect, RuntimeStartResult):
            return self._start_side_effect
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
    def __init__(self, blocked_reason: str | None = None) -> None:
        self.blocked_reason = blocked_reason

    @contextmanager
    def external_runtime_mutation_guard(self):
        if self.blocked_reason is not None:
            raise MaintenanceInProgressError(DATABASE_RECOVERY_ERROR)
        yield


def _patch_collector_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch settings_api collector-status reads so _slim_collector_status works."""
    monkeypatch.setattr(settings_api, "get_collector_status", lambda: "running")
    monkeypatch.setattr(settings_api, "get_collector_health_state", lambda: "healthy")
    monkeypatch.setattr(settings_api, "is_user_paused", lambda: False)
    monkeypatch.setattr(
        settings_api, "get_collector_last_successful_observation_at", lambda: None
    )
    monkeypatch.setattr(
        settings_api, "get_collector_last_failure_code", lambda: None
    )
    monkeypatch.setattr(
        settings_api, "get_collector_consecutive_failures", lambda: 0
    )


def _allow_privacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        privacy_gate_service, "is_sensitive_runtime_allowed", lambda: True
    )


def _patch_accept_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_api,
        "accept_first_run_notice_for_webview",
        lambda: {"ok": True, "accepted": True},
    )


def _patch_accept_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_api,
        "accept_first_run_notice_for_webview",
        lambda: {"ok": False, "error": "确认隐私说明失败"},
    )


# ---------------------------------------------------------------------------
# 1. Full success
# ---------------------------------------------------------------------------

def test_accept_and_start_full_success_dto(monkeypatch):
    _patch_accept_success(monkeypatch)
    _allow_privacy(monkeypatch)
    _patch_collector_status(monkeypatch)
    control = ApplicationControlService(_Runtime(), _Maintenance())

    result = control.accept_privacy_notice_and_start()

    assert set(result) == _DTO_KEYS
    assert result["ok"] is True
    assert result["accepted"] is True
    assert result["collector_started"] is True
    assert result["error_code"] is None
    assert result["message"] == "已确认隐私说明"
    assert isinstance(result["collector_status"], dict)
    assert set(result["collector_status"]) == _COLLECTOR_STATUS_KEYS
    # JSON-serializable
    json.loads(json.dumps(result))


# ---------------------------------------------------------------------------
# 2. Accepted but maintenance blocked
# ---------------------------------------------------------------------------

def test_accept_and_start_maintenance_blocked_dto(monkeypatch):
    _patch_accept_success(monkeypatch)
    _allow_privacy(monkeypatch)
    _patch_collector_status(monkeypatch)
    control = ApplicationControlService(
        _Runtime(), _Maintenance(blocked_reason="secure_import_operation")
    )

    result = control.accept_privacy_notice_and_start()

    assert set(result) == _DTO_KEYS
    assert result["ok"] is False
    assert result["accepted"] is True
    assert result["collector_started"] is False
    assert result["error_code"] == "database_maintenance_recovery_required"
    assert result["message"] == "维护状态尚未恢复，暂不能开始记录"
    # collector_status may be a dict or None; must be JSON-serializable either way.
    assert result["collector_status"] is None or isinstance(
        result["collector_status"], dict
    )
    json.loads(json.dumps(result))


# ---------------------------------------------------------------------------
# 3. Accepted but collector start raised an exception
# ---------------------------------------------------------------------------

def test_accept_and_start_collector_exception_dto(monkeypatch):
    _patch_accept_success(monkeypatch)
    _allow_privacy(monkeypatch)
    _patch_collector_status(monkeypatch)
    control = ApplicationControlService(
        _Runtime(start_side_effect=RuntimeError("worker_crash")),
        _Maintenance(),
    )

    result = control.accept_privacy_notice_and_start()

    assert set(result) == _DTO_KEYS
    assert result["ok"] is False
    assert result["accepted"] is True
    assert result["collector_started"] is False
    assert result["error_code"] == "collector_start_failed"
    assert isinstance(result["message"], str) and result["message"]
    json.loads(json.dumps(result))


# ---------------------------------------------------------------------------
# 4. Authorization persistence failure
# ---------------------------------------------------------------------------

def test_accept_and_start_privacy_persist_failed_dto(monkeypatch):
    _patch_accept_failure(monkeypatch)
    _patch_collector_status(monkeypatch)
    control = ApplicationControlService(_Runtime(), _Maintenance())

    result = control.accept_privacy_notice_and_start()

    assert set(result) == _DTO_KEYS
    assert result["ok"] is False
    assert result["accepted"] is False
    assert result["collector_started"] is False
    assert result["error_code"] == "privacy_accept_failed"
    assert isinstance(result["message"], str) and result["message"]
    assert result["collector_status"] is None
    json.loads(json.dumps(result))


# ---------------------------------------------------------------------------
# 5. Privacy gate not yet authorized (start_collection returns gate error)
# ---------------------------------------------------------------------------

def test_accept_and_start_privacy_gate_still_required_dto(monkeypatch):
    _patch_accept_success(monkeypatch)
    # Gate still closed — accept persisted but gate service disagrees.
    monkeypatch.setattr(
        privacy_gate_service, "is_sensitive_runtime_allowed", lambda: False
    )
    _patch_collector_status(monkeypatch)
    control = ApplicationControlService(_Runtime(), _Maintenance())

    result = control.accept_privacy_notice_and_start()

    assert set(result) == _DTO_KEYS
    assert result["ok"] is False
    assert result["accepted"] is True
    assert result["collector_started"] is False
    assert result["error_code"] == "privacy_gate_required"
    json.loads(json.dumps(result))


# ---------------------------------------------------------------------------
# 6. RuntimeStartResult.error_code must reach the public DTO (not be
#    downgraded to collector_start_failed).
# ---------------------------------------------------------------------------

def test_accept_and_start_runtime_maintenance_error_code_preserved(monkeypatch):
    """RuntimeStartResult.error_code=database_maintenance_recovery_required
    must surface that exact code on the public DTO, not collector_start_failed."""
    _patch_accept_success(monkeypatch)
    _allow_privacy(monkeypatch)
    _patch_collector_status(monkeypatch)
    runtime_result = RuntimeStartResult(
        ok=False,
        collector_ready=False,
        workers={},
        already_running=False,
        degraded=True,
        error_code="database_maintenance_recovery_required",
    )
    control = ApplicationControlService(
        _Runtime(start_side_effect=runtime_result), _Maintenance()
    )

    result = control.accept_privacy_notice_and_start()

    assert set(result) == _DTO_KEYS
    assert result["ok"] is False
    assert result["accepted"] is True
    assert result["collector_started"] is False
    # The authoritative runtime error_code must be preserved, not downgraded
    # to collector_start_failed.
    assert result["error_code"] == "database_maintenance_recovery_required"
    assert isinstance(result["message"], str) and result["message"]
    json.loads(json.dumps(result))


def test_accept_and_start_runtime_unknown_error_code_maps_to_collector_start_failed(monkeypatch):
    """A RuntimeStartResult carrying an unrecognized error_code (e.g.
    runtime_stopping) must map to the public collector_start_failed code.

    The public error code system is not expanded here; unrecognized runtime
    start errors collapse to collector_start_failed so the DTO stays stable.
    """
    _patch_accept_success(monkeypatch)
    _allow_privacy(monkeypatch)
    _patch_collector_status(monkeypatch)
    runtime_result = RuntimeStartResult(
        ok=False,
        collector_ready=False,
        workers={},
        already_running=False,
        degraded=True,
        error_code="runtime_stopping",
    )
    control = ApplicationControlService(
        _Runtime(start_side_effect=runtime_result), _Maintenance()
    )

    result = control.accept_privacy_notice_and_start()

    assert set(result) == _DTO_KEYS
    assert result["ok"] is False
    assert result["accepted"] is True
    assert result["collector_started"] is False
    assert result["error_code"] == "collector_start_failed"
    assert isinstance(result["message"], str) and result["message"]
    json.loads(json.dumps(result))


def test_accept_and_start_runtime_worker_start_failed_maps_to_collector_start_failed(monkeypatch):
    """A RuntimeStartResult carrying worker_start_failed must also map to
    collector_start_failed (no new public error code is introduced)."""
    _patch_accept_success(monkeypatch)
    _allow_privacy(monkeypatch)
    _patch_collector_status(monkeypatch)
    runtime_result = RuntimeStartResult(
        ok=False,
        collector_ready=False,
        workers={},
        already_running=False,
        degraded=True,
        error_code="worker_start_failed",
    )
    control = ApplicationControlService(
        _Runtime(start_side_effect=runtime_result), _Maintenance()
    )

    result = control.accept_privacy_notice_and_start()

    assert set(result) == _DTO_KEYS
    assert result["ok"] is False
    assert result["error_code"] == "collector_start_failed"
    json.loads(json.dumps(result))
