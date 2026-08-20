from __future__ import annotations

from pathlib import Path


def test_statistics_background_refresh_is_single_owner_silent_and_incremental():
    root = Path(__file__).resolve().parents[2]
    js_dir = root / "worktrace" / "webview_ui" / "js"
    statistics = (js_dir / "statistics.js").read_text(encoding="utf-8")
    composition = (js_dir / "ui_composition.js").read_text(encoding="utf-8")
    init = (js_dir / "init_fd_work_v5.js").read_text(encoding="utf-8")

    assert 'preservePresentation: page === "statistics"' in init
    assert "if (!preservePresentation) setStatisticsLoading(true);" in statistics
    assert "reconcileStatisticsPresentation(data.summary, filters);" in statistics
    assert "App.suspendStatisticsLiveTicker" in statistics
    assert "App.statisticsLiveTickerSuspended === true" in composition
    assert 'runtimeGeneration(previous, "report_structure")' in composition

    # init_fd_work_v5.js is the only periodic statistics refresh coordinator.
    assert "backgroundStatisticsRefresh" not in composition
    assert 'refreshComposedPage("statistics"' not in composition
    assert "statisticsNeedsEntryRefresh" not in composition
    assert "getStatisticsExportSummary" not in composition


def test_statistics_all_time_keeps_same_editable_dates_with_zero_placeholder():
    root = Path(__file__).resolve().parents[2]
    statistics = (root / "worktrace" / "webview_ui" / "js" / "statistics.js").read_text(encoding="utf-8")
    styles = (root / "worktrace" / "webview_ui" / "styles.css").read_text(encoding="utf-8")

    assert 'element("statistics-date-inputs").hidden = false;' in statistics
    assert 'element("statistics-all-time-label").hidden = true;' in statistics
    assert 'input.placeholder = "0000/00/00";' in statistics
    assert 'input.type = "text"' in statistics
    assert 'input.type = "date"' in statistics
    assert "--date-control-width: 116px" in styles
    assert "--statistics-date-width" not in styles


def test_statistics_snapshot_cache_covers_all_four_fixed_quick_ranges():
    root = Path(__file__).resolve().parents[2]
    source = (root / "worktrace" / "services" / "statistics_snapshot_provider.py").read_text(encoding="utf-8")

    assert "_MAX_SLOTS = 4" in source
