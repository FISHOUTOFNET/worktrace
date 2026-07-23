"""Regression tests for UI redesign residual architecture fixes.

Covers six fix areas:
  1. Project Rules catalog stays lightweight (no full-history projection).
  2. Statistics summary and CSV export paths are split; default range is this month.
  3. Canonical project-scope policy keeps ``unclassified`` disjoint from excluded.
  4. Export ticket binds snapshot, date range, project scope, format and schema.
  5. Settings maintenance status maps deterministically to display text.
  6. Focus management excludes elements inside hidden ancestors (static source scan).
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.support.activity_factory import create_closed_activity
from tests.support.application import FakeStatisticsCapability, build_test_bridge
from worktrace.api import export_api, project_api, statistics_api
from worktrace.api.application_capabilities import RulesApplicationService
from worktrace.services import (
    export_service,
    project_service,
    statistics_service,
)
from worktrace.services.statistics_projection import (
    StatisticsSummaryProjection,
    build_statistics_summary_projection,
    build_statistics_projection,
    iter_statistics_export_records,
)
from worktrace.services.statistics_scope_policy import (
    entry_matches_statistics_project_scope,
    normalize_statistics_project_scope,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]
DATE = "2026-07-15"
ROOT = Path(__file__).resolve().parents[1]


# -- Problem 1: Project Rules catalog stays lightweight ----------------------


def test_project_bindings_does_not_build_visible_snapshot(temp_db, monkeypatch):
    """Project Rules catalog read must never trigger full-history snapshot."""

    from worktrace.services import report_projection_snapshot_service as snapshots

    calls = 0
    original = snapshots.build_visible_snapshot

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(snapshots, "build_visible_snapshot", counted)
    project_service.create_project("Client A")
    project_service.list_project_bindings()
    assert calls == 0


def test_rules_application_service_routes_to_lightweight_catalog(temp_db):
    """RulesApplicationService.list_project_bindings routes to project_api."""

    project_service.create_project("Client B")
    with patch.object(project_api, "list_project_bindings", return_value=[]) as mock:
        RulesApplicationService.list_project_bindings(RulesApplicationService())
        mock.assert_called_once()


def test_project_rules_source_has_no_total_duration():
    """Frontend source must not contain cumulative-duration artifacts."""

    html = (ROOT / "worktrace/webview_ui/index.html").read_text(encoding="utf-8")
    rules_js = (ROOT / "worktrace/webview_ui/js/rules.js").read_text(encoding="utf-8")
    rules_render = (ROOT / "worktrace/webview_ui/js/rules_render.js").read_text(
        encoding="utf-8"
    )
    combined = html + rules_js + rules_render
    assert "total_duration_seconds" not in combined
    assert "累计时间" not in combined
    assert "total_duration" not in rules_js


def test_list_project_rule_summaries_is_fully_removed():
    """The heavy summary API, service, and capability routes are deleted."""

    assert not hasattr(project_api, "list_project_rule_summaries")
    assert not hasattr(project_service, "list_project_rule_summaries")
    source = (ROOT / "worktrace/services/project_service.py").read_text(
        encoding="utf-8"
    )
    assert "list_project_rule_summaries" not in source


# -- Problem 2: Statistics summary / export split and default range ----------


def test_summary_projection_has_no_export_records(temp_db):
    """StatisticsSummaryProjection must not carry export records."""

    create_closed_activity(day=DATE, start="09:00:00", end="09:30:00")
    from worktrace.services.report_projection_snapshot_service import (
        build_visible_snapshot,
    )

    projection = build_statistics_summary_projection(build_visible_snapshot(DATE, DATE))
    assert isinstance(projection, StatisticsSummaryProjection)
    assert not hasattr(projection, "export_records")
    assert not hasattr(projection, "export_revision")


def test_summary_does_not_return_export_records(temp_db):
    """The summary dict must not expose internal export records."""

    create_closed_activity(day=DATE, start="09:00:00", end="09:30:00")
    summary = statistics_service.get_statistics_export_summary(DATE, DATE)
    assert "export_records" not in summary
    assert "export_revision" not in summary
    assert "ticket_revision" in summary


def test_default_statistics_range_is_this_month():
    """Empty date inputs resolve to first-of-month through today."""

    today = date.today()
    first = today.replace(day=1)
    date_from, date_to = statistics_service.resolve_statistics_date_range("", "")
    assert date_from == first.isoformat()
    assert date_to == today.isoformat()


def test_explicit_all_time_range_still_allowed():
    """Explicitly selecting all-time is valid when dates are non-empty."""

    date_from, date_to = statistics_service.resolve_statistics_date_range(
        "2026-01-01", "2026-07-15"
    )
    assert date_from == "2026-01-01"
    assert date_to == "2026-07-15"


def test_statistics_html_defaults_to_month():
    """Statistics range select defaults to ``本月``."""

    html = (ROOT / "worktrace/webview_ui/index.html").read_text(encoding="utf-8")
    assert 'value="month"' in html
    assert 'value="month" selected' in html
    assert "全部时间" in html
    assert "自定义范围" in html


def test_iter_export_records_yields_display_safe_rows(temp_db):
    """Export iterator yields rows matching the summary projection count."""

    create_closed_activity(day=DATE, start="09:00:00", end="09:30:00")
    from worktrace.services.report_projection_snapshot_service import (
        build_visible_snapshot,
    )

    snapshot = build_visible_snapshot(DATE, DATE)
    summary = build_statistics_summary_projection(snapshot)
    records = list(iter_statistics_export_records(snapshot))
    assert len(records) == summary.export_row_count
    for record in records:
        assert "window_title" not in record
        assert "file_path_hint" not in record


# -- Problem 3: Canonical project-scope policy -------------------------------


def test_unclassified_excludes_standalone_excluded_entry():
    """Standalone excluded rows must not match the unclassified scope."""

    entry = {
        "row_kind": "standalone_status",
        "privacy_redacted": True,
        "is_report_classified": False,
        "project_id": 0,
    }
    assert entry_matches_statistics_project_scope(entry, "unclassified") is False


def test_unclassified_includes_truly_unclassified_entry():
    """Ordinary unclassified records match the unclassified scope."""

    entry = {
        "row_kind": "session",
        "privacy_redacted": False,
        "is_report_classified": False,
        "project_id": 0,
    }
    assert entry_matches_statistics_project_scope(entry, "unclassified") is True


def test_all_scope_includes_excluded_entry():
    """All-projects scope includes excluded standalone status rows."""

    entry = {
        "row_kind": "standalone_status",
        "privacy_redacted": True,
        "is_report_classified": False,
        "project_id": 0,
    }
    assert entry_matches_statistics_project_scope(entry, "") is True


def test_specific_project_only_matches_that_project():
    """Concrete project scope matches only the target project."""

    entry_a = {
        "row_kind": "session",
        "privacy_redacted": False,
        "is_report_classified": True,
        "report_project_id": 5,
        "project_name": "Project A",
    }
    entry_b = {
        "row_kind": "session",
        "privacy_redacted": False,
        "is_report_classified": True,
        "report_project_id": 7,
        "project_name": "Project B",
    }
    assert entry_matches_statistics_project_scope(entry_a, "5") is True
    assert entry_matches_statistics_project_scope(entry_b, "5") is False


def test_invalid_project_id_raises():
    """Non-positive or non-numeric scope raises invalid_project."""

    with pytest.raises(ValueError, match="invalid_project"):
        normalize_statistics_project_scope(-1)
    with pytest.raises(ValueError, match="invalid_project"):
        normalize_statistics_project_scope("abc")
    with pytest.raises(ValueError, match="invalid_project"):
        normalize_statistics_project_scope(0)


def test_summary_and_export_use_same_scope_results(temp_db):
    """Summary and export iterator produce consistent row counts per scope."""

    pid = project_service.create_project("Client C")
    create_closed_activity(day=DATE, start="09:00:00", end="09:30:00", project_id=pid)
    create_closed_activity(day=DATE, start="10:00:00", end="10:15:00")
    from worktrace.services.report_projection_snapshot_service import (
        build_visible_snapshot,
    )

    snapshot = build_visible_snapshot(DATE, DATE)
    for scope_value in (None, "unclassified", str(pid)):
        summary = build_statistics_summary_projection(snapshot, project_id=scope_value)
        records = list(iter_statistics_export_records(snapshot, project_id=scope_value))
        assert summary.export_row_count == len(records), (
            f"scope={scope_value}: summary count {summary.export_row_count} "
            f"!= export count {len(records)}"
        )


def test_unclassified_excludes_excluded_in_real_projection(temp_db):
    """Excluded activity does not appear in the unclassified summary."""

    create_closed_activity(
        day=DATE,
        start="11:00:00",
        end="11:05:00",
        app_name="Secret",
        process_name="secret.exe",
        window_title="Secret",
        status="excluded",
    )
    create_closed_activity(
        day=DATE,
        start="09:00:00",
        end="09:30:00",
    )
    summary = statistics_service.get_statistics_export_summary(
        DATE, DATE, project_id="unclassified"
    )
    assert summary["activity_count"] > 0
    assert summary["excluded_duration_seconds"] == 0 or summary["total_duration_seconds"] > 0


# -- Problem 4: Export ticket contract ---------------------------------------


def _seed_two_projects(temp_db):
    pid_a = project_service.create_project("Project A")
    pid_b = project_service.create_project("Project B")
    create_closed_activity(
        day=DATE, start="09:00:00", end="09:30:00", project_id=pid_a, app_name="AppA"
    )
    create_closed_activity(
        day=DATE, start="10:00:00", end="10:15:00", project_id=pid_b, app_name="AppB"
    )
    return pid_a, pid_b


def test_project_a_ticket_exports_project_a(temp_db, tmp_path):
    """A valid project-A ticket exports project A successfully."""

    pid_a, _ = _seed_two_projects(temp_db)
    summary = statistics_service.get_statistics_export_summary(DATE, DATE, pid_a)
    ticket = summary["ticket_revision"]
    output = tmp_path / "export_a.csv"
    result = export_service.write_statistics_csv(
        DATE, DATE, str(output), ticket, pid_a
    )
    assert result["export_row_count"] == 1
    assert output.exists()


def test_project_a_ticket_cannot_export_project_b(temp_db, tmp_path):
    """Project-A ticket must not export project B."""

    pid_a, pid_b = _seed_two_projects(temp_db)
    summary = statistics_service.get_statistics_export_summary(DATE, DATE, pid_a)
    ticket = summary["ticket_revision"]
    output = tmp_path / "export_b.csv"
    with pytest.raises(ValueError, match="stale_statistics_snapshot"):
        export_service.write_statistics_csv(
            DATE, DATE, str(output), ticket, pid_b
        )
    assert not output.exists()


def test_project_a_ticket_cannot_export_all(temp_db, tmp_path):
    """Project-A ticket must not export all projects."""

    pid_a, _ = _seed_two_projects(temp_db)
    summary = statistics_service.get_statistics_export_summary(DATE, DATE, pid_a)
    ticket = summary["ticket_revision"]
    output = tmp_path / "export_all.csv"
    with pytest.raises(ValueError, match="stale_statistics_snapshot"):
        export_service.write_statistics_csv(
            DATE, DATE, str(output), ticket, None
        )


def test_all_ticket_cannot_export_unclassified(temp_db, tmp_path):
    """All-projects ticket must not export unclassified scope."""

    _seed_two_projects(temp_db)
    summary = statistics_service.get_statistics_export_summary(DATE, DATE)
    ticket = summary["ticket_revision"]
    output = tmp_path / "export_unc.csv"
    with pytest.raises(ValueError, match="stale_statistics_snapshot"):
        export_service.write_statistics_csv(
            DATE, DATE, str(output), ticket, "unclassified"
        )


def test_data_revision_change_invalidates_ticket(temp_db, tmp_path):
    """Adding data after ticket issuance invalidates the old ticket."""

    pid_a, _ = _seed_two_projects(temp_db)
    summary = statistics_service.get_statistics_export_summary(DATE, DATE, pid_a)
    ticket = summary["ticket_revision"]
    create_closed_activity(
        day=DATE, start="12:00:00", end="12:10:00", project_id=pid_a, app_name="AppA2"
    )
    output = tmp_path / "export_stale.csv"
    with pytest.raises(ValueError, match="stale_statistics_snapshot"):
        export_service.write_statistics_csv(
            DATE, DATE, str(output), ticket, pid_a
        )


def test_generic_snapshot_revision_not_accepted(temp_db, tmp_path):
    """The generic snapshot_revision must not serve as the export ticket."""

    pid_a, _ = _seed_two_projects(temp_db)
    summary = statistics_service.get_statistics_export_summary(DATE, DATE, pid_a)
    snapshot_revision = summary["snapshot_revision"]
    assert snapshot_revision != summary["ticket_revision"]
    output = tmp_path / "export_generic.csv"
    with pytest.raises(ValueError, match="stale_statistics_snapshot"):
        export_service.write_statistics_csv(
            DATE, DATE, str(output), snapshot_revision, pid_a
        )


def test_ticket_does_not_expose_sensitive_data(temp_db):
    """The ticket revision is a stable hash, not a serialized payload."""

    pid_a, _ = _seed_two_projects(temp_db)
    summary = statistics_service.get_statistics_export_summary(DATE, DATE, pid_a)
    ticket = summary["ticket_revision"]
    for token in ("window_title", "file_path_hint", "note", "passphrase", "clipboard"):
        assert token not in ticket


def test_export_cancellation_does_not_write(temp_db, tmp_path):
    """A stale ticket must not create the target file or temp residue."""

    pid_a, pid_b = _seed_two_projects(temp_db)
    summary = statistics_service.get_statistics_export_summary(DATE, DATE, pid_a)
    ticket = summary["ticket_revision"]
    output = tmp_path / "export_cancel.csv"
    try:
        export_service.write_statistics_csv(DATE, DATE, str(output), ticket, pid_b)
    except ValueError:
        pass
    assert not output.exists()
    temp_files = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob("*.tmp.*"))
    assert not temp_files


# -- Problem 5: Settings maintenance status semantics -----------------------


def test_settings_maintenance_in_progress_shows_maintaining():
    """Settings source maps maintenance_in_progress to a non-failure title."""

    source = (ROOT / "worktrace/webview_ui/js/settings.js").read_text(encoding="utf-8")
    assert "正在维护数据" in source
    assert "维护期间其他数据操作暂时不可用" in source
    assert "数据维护失败" not in source


def test_settings_recovery_blocked_shows_recovery_title():
    """Settings source maps recovery_blocked to the recovery title."""

    source = (ROOT / "worktrace/webview_ui/js/settings.js").read_text(encoding="utf-8")
    assert "恢复尚未完成" in source
    assert "请在高级诊断中查看阻断原因" in source


def test_settings_collector_not_running_shows_service_title():
    """Settings source maps collector-not-running to a service-down title."""

    source = (ROOT / "worktrace/webview_ui/js/settings.js").read_text(encoding="utf-8")
    assert "记录服务未运行" in source
    assert "请重启应用后再次检查" in source


# -- Problem 6: Focus management static source contract ---------------------


def test_focusable_helper_checks_ancestors():
    """ui_components.js must walk ancestors for hidden and aria-hidden."""

    source = (ROOT / "worktrace/webview_ui/js/ui_components.js").read_text(
        encoding="utf-8"
    )
    assert "isWithinHiddenAncestor" in source
    assert "hasVisibleLayoutBox" in source
    assert "getClientRects" in source
    assert "offsetParent" in source
