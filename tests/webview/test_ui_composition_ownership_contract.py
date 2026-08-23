from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
JS_DIR = ROOT / "worktrace" / "webview_ui" / "js"


def source(name: str) -> str:
    return (JS_DIR / name).read_text(encoding="utf-8")


def test_rules_and_settings_own_refresh_state_and_requests():
    composition = source("ui_composition.js")
    rules = source("rules.js")
    settings = source("settings.js")

    forbidden_private_state = (
        "App.rulesLoaded",
        "App.rulesLoading",
        "App.rulesLoadPromise",
        "App.rulesRefreshPending",
        "App.rulesBackgroundRefreshPromise",
        "App.settingsLoaded",
        "App.settingsLoading",
        "App.settingsLoadPromise",
        "App.settingsRequestToken",
        "App.lastSettingsStatus",
        "App.settingsRefreshPending",
        "App.settingsBackgroundRefreshPromise",
    )
    for private_name in forbidden_private_state:
        assert private_name not in composition

    assert "getProjectRules" not in composition
    assert "getSettingsPrivacyStatus" not in composition
    assert "onDataChanged" in rules
    assert "onPageEntered" in rules
    assert "onDataChanged" in settings
    assert "onPageEntered" in settings
    assert "App.rules.onDataChanged" in composition
    assert "App.settings.onDataChanged" in composition


def test_timeline_owns_structural_pending_and_live_suppression():
    composition = source("ui_composition.js")
    timeline = source("timeline.js")

    forbidden_composition_knowledge = (
        "App.timelineStructuralRefreshPending",
        "App.suppressNextTimelineCollectionRefresh",
        "App._timelineEditingActive",
        "drainTimelineStructuralRefresh",
        "App.refreshTimeline =",
    )
    for private_name in forbidden_composition_knowledge:
        assert private_name not in composition

    assert "onRuntimeTransition" in timeline
    assert "applyLocalTick" in timeline
    assert "App.timeline.onRuntimeTransition" in composition


def test_timeline_refresh_coordinator_forwards_refresh_options():
    init = source("init_fd_work_v5.js")

    timeline_refresher = init.split(
        "        timeline: function (acceptedState, options) {", 1
    )[1].split("        statistics: function", 1)[0]
    assert "capability.onRefreshRequested(options || {})" in timeline_refresher


def test_overview_owns_live_collection_suppression():
    composition = source("ui_composition.js")
    overview = source("overview.js")

    assert "App.suppressNextOverviewCollectionRefresh" not in composition
    assert "App.showOverview =" not in composition
    assert "onRuntimeTransition" in overview
    assert "App.overview.onRuntimeTransition" in composition


def test_init_dispatches_the_existing_local_tick_to_the_active_page():
    composition = source("ui_composition.js")
    init = source("init_fd_work_v5.js")

    assert "App.applyLocalTicker =" not in composition
    local_ticker = init.split("    App.applyLocalTicker = function () {", 1)[1].split(
        "    function invalidateProjectCatalog()", 1
    )[0]
    assert "pageCapability(tickerPage)" in local_ticker
    assert 'typeof capability.applyLocalTick === "function"' in local_ticker
    assert "capability.applyLocalTick()" in local_ticker
    assert "App.bridge" not in local_ticker
    assert "pywebview" not in local_ticker


def test_statistics_owns_accepted_snapshot_ticker_and_numeric_dom_patch():
    composition = source("ui_composition.js")
    statistics = source("statistics.js")

    for private_name in (
        "App.statisticsAcceptedPayload",
        "App.statisticsLiveTickerSuspended",
        "App.statisticsLastLiveRenderKey",
        "statisticsLiveSummaryAtNow",
        "patchStatisticsLiveSummary",
        "applyStatisticsLocalTicker",
    ):
        assert private_name not in composition

    for private_dom_id in (
        "stats-total",
        "stats-by-project",
        "stats-by-file",
        "stats-by-app",
        "stats-share-bar",
    ):
        assert private_dom_id not in composition

    assert "statisticsLiveSummaryAtNow" in statistics
    assert "patchStatisticsLiveSummary" in statistics
    assert "applyStatisticsLocalTicker" in statistics
    assert "showStatistics(summary)" not in statistics.split(
        "function applyStatisticsLocalTicker()", 1
    )[1].split("function validateStatisticsDateRange", 1)[0]


def test_composition_has_no_page_data_reads_monkey_patches_or_private_dom_ids():
    composition = source("ui_composition.js")

    for bridge_read in (
        "getProjectRules",
        "getSettingsPrivacyStatus",
        "getStatisticsExportSummary",
        "getTimeline",
        "getOverview",
    ):
        assert bridge_read not in composition

    for monkey_patch in (
        "App.refreshTimeline =",
        "App.showOverview =",
        "App.applyLocalTicker =",
    ):
        assert monkey_patch not in composition

    for private_dom_id in (
        "stats-total",
        "stats-by-project",
        "stats-by-file",
        "stats-by-app",
        "stats-share-bar",
        "rules-loading",
        "settings-loading",
    ):
        assert private_dom_id not in composition
