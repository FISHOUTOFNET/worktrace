from __future__ import annotations

from contextlib import contextmanager

import pytest

from worktrace.api import settings_api
from worktrace.api.app_api import ApplicationControlService
from worktrace.runtime.contracts import RuntimeStartResult
from worktrace.services import privacy_gate_service
from worktrace.services.database_maintenance_service import (
    MaintenanceInProgressError,
)
from worktrace.write_gate import DATABASE_MAINTENANCE_ERROR, DATABASE_RECOVERY_ERROR

pytestmark = [
    pytest.mark.unit,
    pytest.mark.contract,
    pytest.mark.collector_runtime,
]

_DEFAULT_RESULT = object()


class _Runtime:
    def __init__(self, start_result: object = _DEFAULT_RESULT) -> None:
        self.start_calls = 0
        self.start_result = start_result

    def start_authorized_collection(self) -> object:
        self.start_calls += 1
        if self.start_result is not _DEFAULT_RESULT:
            return self.start_result
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

    @contextmanager
    def external_runtime_mutation_guard(self):
        if self.blocked_reason is not None:
            raise MaintenanceInProgressError(DATABASE_RECOVERY_ERROR)
        yield


class _UnreadableMaintenance:
    @property
    def blocked_reason(self) -> str | None:
        raise RuntimeError("maintenance_state_unavailable")

    @contextmanager
    def external_runtime_mutation_guard(self):
        raise MaintenanceInProgressError(DATABASE_RECOVERY_ERROR)


class _TruthyStartupResult:
    def __bool__(self) -> bool:
        return True


class _ToDictStartupResult:
    def to_dict(self) -> dict[str, object]:
        return {"ok": True, "collector_ready": True, "workers": {}}


def _allow_sensitive_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: True,
    )


def test_fail_closed_latch_blocks_resume_before_runtime_start(monkeypatch):
    runtime = _Runtime()
    control = ApplicationControlService(
        runtime,
        _Maintenance("secure_import_operation"),
    )
    _allow_sensitive_runtime(monkeypatch)

    result = control.start_collection_after_privacy_gate()

    assert result == {
        "ok": False,
        "error": DATABASE_RECOVERY_ERROR,
        "message": "维护状态尚未恢复，暂不能开始记录",
    }
    assert runtime.start_calls == 0


def test_unreadable_maintenance_state_fails_closed(monkeypatch):
    runtime = _Runtime()
    control = ApplicationControlService(runtime, _UnreadableMaintenance())
    _allow_sensitive_runtime(monkeypatch)

    result = control.start_collection_after_privacy_gate()

    assert result["error"] == DATABASE_RECOVERY_ERROR
    assert runtime.start_calls == 0


def test_cleared_maintenance_state_allows_exact_runtime_result(monkeypatch):
    runtime = _Runtime()
    control = ApplicationControlService(runtime, _Maintenance(None))
    _allow_sensitive_runtime(monkeypatch)

    result = control.start_collection_after_privacy_gate()

    assert result["ok"] is True
    assert runtime.start_calls == 1


@pytest.mark.parametrize(
    "invalid_result",
    [
        {},
        True,
        _TruthyStartupResult(),
        _ToDictStartupResult(),
    ],
    ids=["dict", "bool", "truthy-object", "to-dict-object"],
)
def test_structurally_similar_runtime_results_are_rejected(
    monkeypatch,
    invalid_result,
):
    runtime = _Runtime(invalid_result)
    control = ApplicationControlService(runtime, _Maintenance(None))
    _allow_sensitive_runtime(monkeypatch)

    result = control.start_collection_after_privacy_gate()

    assert result == {"ok": False, "error": "collector_start_failed"}
    assert runtime.start_calls == 1


def test_toggle_does_not_clear_user_pause_while_fail_closed(monkeypatch):
    runtime = _Runtime()
    control = ApplicationControlService(
        runtime,
        _Maintenance("clear_database_operation"),
    )
    _allow_sensitive_runtime(monkeypatch)
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

    assert result["error"] == DATABASE_RECOVERY_ERROR
    assert runtime.start_calls == 0
    assert cleared == []


class _ClipboardTrackingRuntime:
    def __init__(self) -> None:
        self.enable_calls = 0
        self.disable_calls = 0

    def start_authorized_collection(self) -> object:
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
        if enabled:
            self.enable_calls += 1
        else:
            self.disable_calls += 1
        return True

    def request_shutdown(self) -> None:
        return None


def test_clipboard_enable_during_active_maintenance_is_rejected(monkeypatch):
    runtime = _ClipboardTrackingRuntime()
    control = ApplicationControlService(
        runtime,
        _Maintenance("active_maintenance"),
    )
    _allow_sensitive_runtime(monkeypatch)

    with pytest.raises(MaintenanceInProgressError):
        control.set_clipboard_capture_enabled(True)

    assert runtime.enable_calls == 0


def test_clipboard_disable_during_active_maintenance_still_succeeds(monkeypatch):
    runtime = _ClipboardTrackingRuntime()
    control = ApplicationControlService(
        runtime,
        _Maintenance("active_maintenance"),
    )
    _allow_sensitive_runtime(monkeypatch)

    control.set_clipboard_capture_enabled(False)

    assert runtime.disable_calls == 1


class _PrivacyInvalidatingMaintenance:
    """Guard that flips privacy to False after acquiring, simulating TOCTOU."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._monkeypatch = monkeypatch

    @property
    def blocked_reason(self) -> str | None:
        return None

    @contextmanager
    def external_runtime_mutation_guard(self):
        self._monkeypatch.setattr(
            privacy_gate_service,
            "is_sensitive_runtime_allowed",
            lambda: False,
        )
        yield


def test_guard_acquired_then_privacy_false_blocks_collector_start(monkeypatch):
    _allow_sensitive_runtime(monkeypatch)
    runtime = _Runtime()
    control = ApplicationControlService(
        runtime,
        _PrivacyInvalidatingMaintenance(monkeypatch),
    )

    result = control.start_collection_after_privacy_gate()

    assert result == {"ok": False, "error": "请先确认隐私说明"}
    assert runtime.start_calls == 0


def test_guard_acquired_then_gate_exception_blocks_collector_start(monkeypatch):
    _allow_sensitive_runtime(monkeypatch)
    runtime = _Runtime()
    maintenance = _PrivacyInvalidatingMaintenance(monkeypatch)
    control = ApplicationControlService(runtime, maintenance)

    def raising_gate():
        raise RuntimeError("gate unavailable after guard acquired")

    monkeypatch.setattr(
        privacy_gate_service,
        "is_sensitive_runtime_allowed",
        lambda: True,
    )

    @contextmanager
    def gate_breaking_guard():
        monkeypatch.setattr(
            privacy_gate_service,
            "is_sensitive_runtime_allowed",
            raising_gate,
        )
        yield

    maintenance.external_runtime_mutation_guard = gate_breaking_guard

    result = control.start_collection_after_privacy_gate()

    assert result == {"ok": False, "error": "collector_start_failed"}
    assert runtime.start_calls == 0


def test_clipboard_enable_checks_gate_inside_guard(monkeypatch):
    _allow_sensitive_runtime(monkeypatch)
    runtime = _ClipboardTrackingRuntime()
    control = ApplicationControlService(
        runtime,
        _PrivacyInvalidatingMaintenance(monkeypatch),
    )

    with pytest.raises(privacy_gate_service.PrivacyGateRequiredError):
        control.set_clipboard_capture_enabled(True)

    assert runtime.enable_calls == 0


def test_external_guard_holding_blocks_maintenance_operation(
    _isolate_maintenance_coordinator,
):
    import threading

    coordinator = _isolate_maintenance_coordinator
    guard_acquired = threading.Event()
    release_guard = threading.Event()
    maintenance_blocked = threading.Event()

    def hold_guard():
        with coordinator.external_runtime_mutation_guard():
            guard_acquired.set()
            release_guard.wait(timeout=2)

    def try_maintenance():
        guard_acquired.wait(timeout=2)
        acquired = coordinator._operation_lock.acquire(blocking=False)
        if not acquired:
            maintenance_blocked.set()
        else:
            coordinator._operation_lock.release()

    guard_thread = threading.Thread(target=hold_guard, daemon=True)
    maintenance_thread = threading.Thread(target=try_maintenance, daemon=True)
    guard_thread.start()
    maintenance_thread.start()

    maintenance_thread.join(timeout=2)
    assert not maintenance_thread.is_alive(), "maintenance thread did not terminate"
    assert maintenance_blocked.is_set(), "maintenance acquired lock while guard held"

    release_guard.set()
    guard_thread.join(timeout=2)
    assert not guard_thread.is_alive(), "guard thread did not terminate"


def test_guard_body_exception_releases_lock(_isolate_maintenance_coordinator):
    coordinator = _isolate_maintenance_coordinator

    with pytest.raises(RuntimeError):
        with coordinator.external_runtime_mutation_guard():
            raise RuntimeError("body failure")

    with coordinator.external_runtime_mutation_guard():
        pass


def test_coordinator_internal_restore_does_not_self_lock(
    _isolate_maintenance_coordinator,
    monkeypatch,
):
    from tests.support.application import TestRuntimeMaintenanceControl
    from worktrace.services.database_maintenance_service import (
        RuntimeMaintenanceState,
    )

    coordinator = _isolate_maintenance_coordinator
    control = TestRuntimeMaintenanceControl()
    coordinator.register_runtime_control(control)

    coordinator._operation_lock.acquire()

    try:
        state = RuntimeMaintenanceState(
            collector_running=True,
            privacy_notice_accepted=True,
            user_paused=False,
            collector_status="running",
            runtime_generation=1,
            replacement_epoch=0,
        )
        result = control.restore_after_maintenance(state, timeout_seconds=1.0)
        assert result["terminal_state"] == "operational"
    finally:
        coordinator._operation_lock.release()
