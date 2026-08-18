from __future__ import annotations

from pathlib import Path


def test_heartbeat_keeps_revision_transport_but_uses_generation_policies_for_refresh():
    root = Path(__file__).resolve().parents[2]
    source = (root / "worktrace" / "webview_ui" / "js" / "init_fd_work_v5.js").read_text(encoding="utf-8")

    assert "App.timelineDate" in source
    assert "snapshot.revision" in source
    assert "revisions.page" in source
    assert "previousRuntime.liveRevision" in source
    assert "pageStructureChanged" not in source
    assert "previousRuntime.pageRevision !==" not in source
    assert "PAGE_REFRESH_POLICIES" in source
    assert "markPagesDirtyForGenerationChanges" in source
    for generation in (
        "report_structure",
        "classification_catalog",
        "settings",
        "privacy_catalog",
    ):
        assert generation in source
    assert "scheduleAutomaticPageRefresh" in source
    assert "automaticRefreshAllowedForPage" in source
    assert 'String(App.timelineDate || "") === App.localTodayStr()' in source
    assert "statisticsSelectionIncludesToday" in source
    assert 'preservePresentation: page === "statistics"' in source
    assert "pageNeedsRefresh" in source
    assert "if (!pageNeedsRefresh(pageId)) return;" in source

    for alias in (
        "refresh_revision",
        "live_state_revision",
        "display_projection_revision",
        "page_structure_revision",
    ):
        assert alias not in source
