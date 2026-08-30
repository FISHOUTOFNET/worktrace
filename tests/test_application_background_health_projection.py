from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from worktrace.api import app_api
from worktrace.api.app_api import ApplicationControlService


pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.parallel_safe]


class _Runtime:
    def __init__(self, phase: str, snapshot: dict[str, object]) -> None:
        self.phase = SimpleNamespace(value=phase)
        self._snapshot = snapshot
        self.collector_control = SimpleNamespace(hold_state=SimpleNamespace(value="operational"))

    def worker_health_snapshot(self) -> dict[str, object]:
        return self._snapshot


class _Maintenance:
    blocked_reason = None

    def operation_active(self) -> bool:
        return False

    def recovery_blocked(self) -> bool:
        return False

    def external_runtime_mutation_guard(self):
        return nullcontext()


def _patch_collector_settings(monkeypatch, *, health_state: str = "healthy") -> None:
    monkeypatch.setattr(app_api.settings_api, "get_collector_status", lambda: "running")
    monkeypatch.setattr(app_api.settings_api, "get_collector_health_state", lambda: health_state)
    monkeypatch.setattr(app_api.settings_api, "is_user_paused", lambda: False)
    monkeypatch.setattr(
        app_api.settings_api,
        "get_collector_last_successful_observation_at",
        lambda: "",
    )
    monkeypatch.setattr(app_api.settings_api, "get_collector_last_failure_code", lambda: "")
    monkeypatch.setattr(app_api.settings_api, "get_collector_consecutive_failures", lambda: 0)


def test_first_worker_failure_is_visible_even_before_health_threshold(monkeypatch) -> None:
    _patch_collector_settings(monkeypatch)
    runtime = _Runtime(
        "degraded",
        {
            "workers": {
                "folder_index": {
                    "running": True,
                    "consecutive_failures": 1,
                    "last_failure_code": "database_busy",
                }
            },
            "degraded_workers": [],
        },
    )
    status = ApplicationControlService(runtime, _Maintenance()).get_collection_status()

    assert status["background_health_state"] == "degraded"
    assert status["background_degraded_workers"] == ["folder_index"]
    assert status["display"] == "记录中，部分后台任务异常"


def test_runtime_starting_projects_background_preparation_without_false_failure(
    monkeypatch,
) -> None:
    _patch_collector_settings(monkeypatch)
    runtime = _Runtime(
        "starting",
        {
            "workers": {
                "folder_index": {
                    "running": True,
                    "consecutive_failures": 0,
                    "last_failure_code": "",
                }
            },
            "degraded_workers": [],
        },
    )
    status = ApplicationControlService(runtime, _Maintenance()).get_collection_status()

    assert status["background_health_state"] == "starting"
    assert status["background_degraded_workers"] == []
    assert status["display"] == "记录中，后台任务正在准备"


def test_collector_failing_display_has_priority_over_derived_worker_degradation(
    monkeypatch,
) -> None:
    _patch_collector_settings(monkeypatch, health_state="failing")
    runtime = _Runtime(
        "degraded",
        {
            "workers": {
                "history": {
                    "running": False,
                    "consecutive_failures": 3,
                    "last_failure_code": "history_iteration_failed",
                }
            },
            "degraded_workers": ["history"],
        },
    )
    status = ApplicationControlService(runtime, _Maintenance()).get_collection_status()

    assert status["background_health_state"] == "degraded"
    assert status["display"] == "采集可能中断，请重试"


def test_healthy_runtime_keeps_normal_collection_display(monkeypatch) -> None:
    _patch_collector_settings(monkeypatch)
    runtime = _Runtime(
        "running",
        {
            "workers": {
                "inference": {
                    "running": True,
                    "consecutive_failures": 0,
                    "last_failure_code": "",
                }
            },
            "degraded_workers": [],
        },
    )
    status = ApplicationControlService(runtime, _Maintenance()).get_collection_status()

    assert status["background_health_state"] == "healthy"
    assert status["background_degraded_workers"] == []
    assert status["display"] == "记录中"
