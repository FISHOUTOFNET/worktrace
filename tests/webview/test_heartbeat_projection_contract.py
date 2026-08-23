from __future__ import annotations

from pathlib import Path


def test_heartbeat_keeps_revision_transport_but_uses_generation_policies_for_refresh():
    root = Path(__file__).resolve().parents[2]
    init_source = (root / "worktrace" / "webview_ui" / "js" / "init_fd_work_v5.js").read_text(encoding="utf-8")
    lifecycle_source = (root / "worktrace" / "webview_ui" / "js" / "page_lifecycle.js").read_text(encoding="utf-8")
    page_sources = "\n".join(
        (root / "worktrace" / "webview_ui" / "js" / name).read_text(encoding="utf-8")
        for name in ("overview.js", "timeline.js", "statistics.js", "rules.js", "settings.js")
    )

    assert "App.timelineDate" not in init_source
    assert "pageReportDate(App.currentPage)" in init_source
    assert "App.timelineDate" not in lifecycle_source
    assert "reportDate: function" in page_sources
    assert "snapshot.revision" in init_source
    assert "revisions.page" in init_source
    assert "previousRuntime.liveRevision" in init_source
    assert "pageStructureChanged" not in init_source
    assert "previousRuntime.pageRevision !==" not in init_source
    assert "PAGE_REFRESH_POLICIES" not in init_source
    assert "capability.refreshPolicy" in init_source
    assert "markPagesDirtyForGenerationChanges" in init_source
    for generation in (
        "report_structure",
        "classification_catalog",
        "settings",
        "privacy_catalog",
    ):
        assert generation in page_sources
    assert "scheduleAutomaticPageRefresh" in init_source
    assert "automaticRefreshAllowedForPage" in init_source
    assert "capability.automaticRefreshAllowed(App.localTodayStr())" in init_source
    assert "statisticsSelectionIncludesToday" not in init_source
    assert "App.statisticsSelection" not in lifecycle_source
    assert "preservePresentation: true" in page_sources
    assert "pageNeedsRefresh" in init_source
    assert "if (!pageNeedsRefresh(pageId)) return;" in init_source

    for alias in (
        "refresh_revision",
        "live_state_revision",
        "display_projection_revision",
        "page_structure_revision",
    ):
        assert alias not in init_source
