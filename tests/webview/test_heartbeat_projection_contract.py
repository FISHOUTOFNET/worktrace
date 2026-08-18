from __future__ import annotations

from pathlib import Path


def test_heartbeat_keeps_revision_transport_but_uses_generation_policies_for_refresh():
    root = Path(__file__).resolve().parents[2]
    source = (root / "worktrace" / "webview_ui" / "js" / "init_fd_work_v5.js").read_text(encoding="utf-8")

    # Runtime transport still carries the two non-overlapping revisions for
    # continuity/diagnostics, but pageRevision is no longer the universal
    # expensive-refresh trigger.
    assert "App.timelineDate" in source
    assert "snapshot.revision" in source
    assert "revisions.page" in source
    assert "previousRuntime.liveRevision" in source
    assert "pageStructureChanged" not in source
    assert "previousRuntime.pageRevision !==" not in source

    # The single refresh coordinator consumes the durable generation namespaces
    # that the backend already publishes instead of inventing another event bus.
    assert "PAGE_REFRESH_POLICIES" in source
    assert "markPagesDirtyForGenerationChanges" in source
    for generation in (
        "report_structure",
        "classification_catalog",
        "settings",
        "privacy_catalog",
    ):
        assert generation in source

    # High-frequency report pages coalesce background changes; historical-only
    # surfaces stay dirty without being rebuilt for today's activity switches.
    assert "scheduleAutomaticPageRefresh" in source
    assert "automaticRefreshAllowedForPage" in source
    assert 'String(App.timelineDate || "") === App.localTodayStr()' in source
    assert "statisticsSelectionIncludesToday" in source
    assert 'preservePresentation: page === "statistics"' in source

    # Returning to an already-loaded clean page reuses its accepted DOM/data.
    assert "pageNeedsRefresh" in source
    assert "if (!pageNeedsRefresh(pageId)) return;" in source

    for alias in (
        "refresh_revision",
        "live_state_revision",
        "display_projection_revision",
        "page_structure_revision",
    ):
        assert alias not in source
