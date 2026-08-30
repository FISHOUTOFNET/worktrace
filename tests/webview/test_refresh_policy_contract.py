from __future__ import annotations

from pathlib import Path


def test_statistics_background_refresh_is_single_owner_silent_and_incremental():
    root = Path(__file__).resolve().parents[2]
    js_dir = root / "worktrace" / "webview_ui" / "js"
    statistics = (js_dir / "statistics.js").read_text(encoding="utf-8")
    composition = (js_dir / "ui_composition.js").read_text(encoding="utf-8")
    init = (js_dir / "init_fd_work_v5.js").read_text(encoding="utf-8")

    assert "policy.preservePresentation === true" in init
    assert "preservePresentation: true" in statistics
    assert "if (!preservePresentation) setStatisticsLoading(true);" in statistics
    assert "reconcileStatisticsPresentation(data.summary);" in statistics
    assert "App.suspendStatisticsLiveTicker" in statistics
    assert "App.statisticsLiveTickerSuspended === true" in statistics
    assert 'runtimeGeneration(previous, "report_structure")' in composition

    # init_fd_work_v5.js is the only periodic statistics refresh coordinator.
    assert "backgroundStatisticsRefresh" not in composition
    assert 'refreshComposedPage("statistics"' not in composition
    assert "statisticsNeedsEntryRefresh" not in composition
    assert "getStatisticsExportSummary" not in composition


def test_statistics_all_time_keeps_native_dates_with_controlled_empty_presentation():
    root = Path(__file__).resolve().parents[2]
    statistics = (root / "worktrace" / "webview_ui" / "js" / "statistics.js").read_text(encoding="utf-8")
    styles = (root / "worktrace" / "webview_ui" / "styles.css").read_text(encoding="utf-8")
    index = (root / "worktrace" / "webview_ui" / "index_fd_work_v5.html").read_text(encoding="utf-8")

    assert 'input.setAttribute("data-empty", String(!String(input.value || "")));' in statistics
    assert 'input.type = "text"' not in statistics
    assert 'input.type = "date"' not in statistics
    assert index.count("YYYY/MM/DD") == 2
    assert 'class="date-control statistics-date-control" type="date"' in index
    assert "--date-control-width: 116px" in styles
    assert "--statistics-date-width" not in styles


def test_statistics_quick_ranges_use_summary_cache_not_four_range_snapshots():
    root = Path(__file__).resolve().parents[2]
    source = (root / "worktrace" / "services" / "statistics_snapshot_provider.py").read_text(encoding="utf-8")

    # Today/week/month/all summaries may all remain reusable, but the heavier
    # compact range projection is deliberately limited to two stable LRU slots.
    assert "_MAX_RANGE_SLOTS = 2" in source
    assert "_MAX_SUMMARY_SLOTS = 32" in source
    assert "cached_summary = _get_cached_summary" in source
    assert source.index("cached_summary = _get_cached_summary") < source.index(
        "range_projection = _get_range_with_context"
    )
    assert "_MAX_SLOTS = 4" not in source
