"""Release guard contracts for bounded interactive Statistics ranges."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from worktrace.api import export_api, statistics_api
from worktrace.api.statistics_interactive_range_policy import (
    INTERACTIVE_STATISTICS_MAX_RANGE_DAYS,
    validate_interactive_statistics_range,
)
from worktrace.services import export_service, statistics_service


pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[1]


def test_interactive_policy_accepts_complete_leap_year() -> None:
    assert INTERACTIVE_STATISTICS_MAX_RANGE_DAYS == 366
    validate_interactive_statistics_range("2024-01-01", "2024-12-31")


def test_interactive_policy_rejects_367_days_and_all_time() -> None:
    with pytest.raises(ValueError, match="range_too_large"):
        validate_interactive_statistics_range("2024-01-01", "2025-01-01")
    with pytest.raises(ValueError, match="range_too_large"):
        validate_interactive_statistics_range("", "")


def test_core_all_time_semantics_remain_available() -> None:
    date_from, date_to = statistics_service.resolve_statistics_date_range("", "")
    assert date_from == statistics_service.STATISTICS_ALL_TIME_START_DATE
    assert date_to


def test_statistics_view_model_rejects_before_realtime_service(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("oversized Statistics range reached the heavy service")

    monkeypatch.setattr(
        statistics_service,
        "get_statistics_realtime_export_summary",
        forbidden,
    )

    for date_from, date_to in (
        ("2024-01-01", "2025-01-01"),
        ("", ""),
    ):
        with pytest.raises(statistics_api.StatisticsSummaryError) as exc_info:
            statistics_api.get_statistics_export_view_model(date_from, date_to)
        assert exc_info.value.code == "range_too_large"


def test_statistics_summary_rejects_before_durable_service(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("oversized Statistics range reached the durable service")

    monkeypatch.setattr(
        statistics_service,
        "get_statistics_export_summary",
        forbidden,
    )

    with pytest.raises(statistics_api.StatisticsSummaryError) as exc_info:
        statistics_api.get_statistics_export_summary("2024-01-01", "2025-01-01")
    assert exc_info.value.code == "range_too_large"


def test_csv_prepare_rejects_before_snapshot_preparation(monkeypatch) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("oversized CSV range reached snapshot preparation")

    monkeypatch.setattr(export_service, "prepare_statistics_csv", forbidden)

    for date_from, date_to in (
        ("2024-01-01", "2025-01-01"),
        ("", ""),
    ):
        with pytest.raises(export_api.StatisticsExportError) as exc_info:
            export_api.prepare_statistics_csv(date_from, date_to)
        assert exc_info.value.code == "range_too_large"


def test_legacy_csv_api_uses_the_same_range_policy(monkeypatch, tmp_path) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("oversized legacy CSV range reached snapshot materialization")

    monkeypatch.setattr(export_service, "write_statistics_csv", forbidden)

    with pytest.raises(export_api.StatisticsExportError) as exc_info:
        export_api.export_statistics_csv(
            "2024-01-01",
            "2025-01-01",
            tmp_path / "blocked.csv",
            "revision",
        )
    assert exc_info.value.code == "range_too_large"


def test_shipping_ui_hides_all_time_loads_policy_and_packages_it() -> None:
    html = (ROOT / "worktrace/webview_ui/index_fd_work_v5.html").read_text(
        encoding="utf-8"
    )
    policy_js = (
        ROOT / "worktrace/webview_ui/js/statistics_interactive_range_policy.js"
    ).read_text(encoding="utf-8")
    spec = (ROOT / "WorkTrace.spec").read_text(encoding="utf-8")

    page_tag = re.search(r'<section id="page-statistics"[^>]*>', html)
    assert page_tag is not None
    assert f'data-max-range-days="{INTERACTIVE_STATISTICS_MAX_RANGE_DAYS}"' in page_tag.group(0)

    all_button = re.search(r'<button id="statistics-all-btn"[^>]*>', html)
    assert all_button is not None
    for attribute in ("hidden", "disabled", 'aria-hidden="true"'):
        assert attribute in all_button.group(0)

    statistics_script = 'src="js/statistics.js?'
    policy_script = 'src="js/statistics_interactive_range_policy.js?'
    compatibility_script = 'src="js/statistics_live_projection.js?'
    assert html.index(statistics_script) < html.index(policy_script) < html.index(compatibility_script)

    assert 'page.getAttribute("data-max-range-days")' in policy_js
    assert 'if (type === "all") return Promise.resolve(null);' in policy_js
    assert "App.applyStatisticsDraftSelection = function ()" in policy_js
    assert "单次统计最多支持 " in policy_js
    assert "Date.UTC" in policy_js

    statistics_asset = "'statistics.js'"
    policy_asset = "'statistics_interactive_range_policy.js'"
    compatibility_asset = "'statistics_live_projection.js'"
    assert policy_asset in spec
    assert spec.index(statistics_asset) < spec.index(policy_asset) < spec.index(compatibility_asset)
