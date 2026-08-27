from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from worktrace.api import export_api
from worktrace.api.statistics_api import StatisticsSummaryError
from worktrace.runtime import statistics_application_service as statistics_runtime
from worktrace.webview_ui.bridge_statistics import StatisticsBridgeMixin


def _scope(*, runtime_consistent: bool, needs_full_refresh: bool, live_eligible: bool):
    @contextmanager
    def factory(**kwargs):
        assert kwargs["allow_unpersisted_runtime"] is True
        assert kwargs["collection_live_eligible"] is live_eligible
        yield SimpleNamespace(
            runtime_consistent=runtime_consistent,
            needs_full_refresh=needs_full_refresh,
            collection_live_eligible=live_eligible,
        )

    return factory


def test_realtime_statistics_exposes_request_runtime_sync(monkeypatch):
    monkeypatch.setattr(
        statistics_runtime,
        "page_read_scope",
        _scope(runtime_consistent=False, needs_full_refresh=True, live_eligible=True),
    )
    monkeypatch.setattr(
        statistics_runtime.StatisticsApplicationService,
        "get_statistics_export_view_model",
        lambda self, date_from, date_to, project_id=None: {
            "summary": {"total_duration_seconds": 10},
            "export_ticket": {"revision": "r1", "live_target": None},
        },
    )

    result = statistics_runtime.RealtimeStatisticsApplicationService().get_statistics_export_view_model_live(
        "2026-08-27",
        "2026-08-27",
        collection_live_eligible=True,
    )

    assert result["summary"]["total_duration_seconds"] == 10
    assert result["runtime_sync"] == {
        "runtime_consistent": False,
        "needs_full_refresh": True,
        "collection_live_eligible": True,
    }


def test_live_csv_refuses_to_freeze_degraded_runtime_snapshot(monkeypatch):
    monkeypatch.setattr(
        statistics_runtime,
        "page_read_scope",
        _scope(runtime_consistent=False, needs_full_refresh=True, live_eligible=True),
    )
    prepare_calls = 0

    def prepare(*args, **kwargs):
        nonlocal prepare_calls
        prepare_calls += 1
        return object()

    monkeypatch.setattr(statistics_runtime.export_api, "prepare_statistics_csv", prepare)

    with pytest.raises(export_api.StatisticsExportError) as exc_info:
        statistics_runtime.RealtimeStatisticsApplicationService().prepare_statistics_csv_live(
            "2026-08-27",
            "2026-08-27",
            collection_live_eligible=True,
        )

    assert exc_info.value.code == "statistics_sync_pending"
    assert prepare_calls == 0


def test_non_live_csv_can_freeze_durable_snapshot_without_retry_loop(monkeypatch):
    monkeypatch.setattr(
        statistics_runtime,
        "page_read_scope",
        _scope(runtime_consistent=True, needs_full_refresh=False, live_eligible=False),
    )
    prepared = object()
    monkeypatch.setattr(
        statistics_runtime.export_api,
        "prepare_statistics_csv",
        lambda *args, **kwargs: prepared,
    )

    result = statistics_runtime.RealtimeStatisticsApplicationService().prepare_statistics_csv_live(
        "2026-08-27",
        "2026-08-27",
        collection_live_eligible=False,
    )

    assert result is prepared


class _Runtime:
    def collection_liveness_snapshot(self):
        return {"live_eligible": True}


class _StatisticsCapability:
    StatisticsSummaryError = StatisticsSummaryError
    StatisticsExportError = export_api.StatisticsExportError

    def get_statistics_export_view_model_live(self, *args, **kwargs):
        return {
            "summary": {"total_duration_seconds": 10},
            "export_ticket": {"revision": "r1", "live_target": None},
            "runtime_sync": {
                "runtime_consistent": False,
                "needs_full_refresh": True,
                "collection_live_eligible": True,
            },
        }

    def prepare_statistics_csv_live(self, *args, **kwargs):
        raise export_api.StatisticsExportError("statistics_sync_pending")

    def format_export_duration(self, duration_seconds):
        return "00:00:00"


class _Bridge(StatisticsBridgeMixin):
    def __init__(self):
        self._services = SimpleNamespace(statistics=_StatisticsCapability())

    def _runtime(self):
        return _Runtime()

    def _choose_csv_save_path(self):
        raise AssertionError("save dialog must not open while statistics are syncing")


def test_bridge_forwards_runtime_sync_and_maps_sync_pending_export():
    bridge = _Bridge()

    summary = bridge.get_statistics_export_summary("2026-08-27", "2026-08-27")
    assert summary["ok"] is True
    assert summary["runtime_sync"]["needs_full_refresh"] is True

    exported = bridge.export_statistics_csv(
        "2026-08-27",
        "2026-08-27",
        "r1",
    )
    assert exported == {
        "ok": False,
        "error": "统计数据正在同步，请重试",
        "cancelled": False,
    }
