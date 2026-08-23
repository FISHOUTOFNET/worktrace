from __future__ import annotations

import pytest

from static_helpers import ALL_JS_FILES, read_js

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]


def test_refresh_coordinator_uses_page_lifecycle_capabilities() -> None:
    source = read_js("init_fd_work_v5.js")
    forbidden = (
        "App.lastOverviewSnapshot",
        "App.timelineLoaded",
        "App.timelineLoading",
        "App.lastTimelineData",
        "App.timelineDate",
        "App._timelineEditingActive",
        "App.statisticsLoaded",
        "App.statisticsAcceptedPayload",
        "App.statisticsSelection",
        "App.rulesLoaded",
        "App.lastProjectRulesData",
        "App.settingsLoaded",
        "App.lastSettingsStatus",
        "App.timelineAutosaveQueued",
        "App.editingSession",
        "App.rulesLoading",
        "App.rulesRefreshPending",
        "App.settingsWriteInProgress",
        "ACTIVE_PAGE_REFRESHERS",
        "PAGE_LEAVE_RESETTERS",
        'page === "statistics"',
        'pageId === "statistics"',
        'page === "settings"',
    )
    for marker in forbidden:
        assert marker not in source, f"refresh coordinator must not read page-private state: {marker}"

    for capability in (
        "onRefreshRequested",
        "onPageEntered",
        "onPageLeft",
        "bindEvents",
        "refreshPolicy",
        "refreshEvidence",
        "updateCurrentActivity",
    ):
        assert capability in source


def test_page_lifecycle_boundary_is_stateless_and_loaded_before_init() -> None:
    source = read_js("page_lifecycle.js")
    assert ALL_JS_FILES.index("page_lifecycle.js") < ALL_JS_FILES.index("init_fd_work_v5.js")

    for marker in (
        "pageRefreshDirty",
        "pageRefreshEpoch",
        "runtimeState",
        "App.timelineDate",
        "App.statisticsSelection",
        "App.rulesLoaded",
        "App.settingsLoaded",
        "document.",
        "setTimeout(",
        "setInterval(",
    ):
        assert marker not in source, f"page lifecycle boundary must not own coordinator state: {marker}"

    for capability in ("capability", "forEach", "bindEvents", "onPageLeft", "resetGeneration"):
        assert capability in source


def test_each_page_owner_exposes_its_own_lifecycle_facts() -> None:
    required = {
        "overview.js": ("refreshPolicy", "hasLoadedData", "refreshEvidence", "onRefreshRequested"),
        "timeline.js": ("refreshPolicy", "hasLoadedData", "refreshEvidence", "onRefreshRequested"),
        "statistics.js": ("refreshPolicy", "hasLoadedData", "refreshEvidence", "onRefreshRequested"),
        "rules.js": ("refreshPolicy", "hasLoadedData", "refreshEvidence", "onRefreshRequested"),
        "settings.js": ("refreshPolicy", "hasLoadedData", "refreshEvidence", "onRefreshRequested"),
    }
    for filename, capabilities in required.items():
        source = read_js(filename)
        for capability in capabilities:
            assert capability in source, f"{filename} must own {capability}"


def test_init_does_not_bind_page_private_dom_controls() -> None:
    source = read_js("init_fd_work_v5.js")
    for private_id in (
        "timeline-prev-btn",
        "edit-project-select",
        "timeline-details-close",
        "statistics-today-btn",
        "statistics-apply-range-btn",
        "settings-clipboard-toggle",
        "settings-backup-export-btn",
        "settings-privacy-notice-btn",
    ):
        assert private_id not in source


def test_timeline_request_state_does_not_reset_other_owners() -> None:
    source = read_js("timeline_request_state.js")
    for foreign_state in (
        "App.statisticsAcceptedPayload",
        "App.rulesLoadPromise",
        "App.refreshCheckInFlight",
        "App.activePageRefreshInFlight",
        "App.activePageRefreshPromise",
        "App.activePageRefreshPending",
    ):
        assert foreign_state not in source


def test_page_lifecycle_boundary_is_packaged() -> None:
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[2] / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'page_lifecycle.js'" in spec
