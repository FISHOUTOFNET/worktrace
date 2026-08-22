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
    )
    for marker in forbidden:
        assert marker not in source, f"refresh coordinator must not read page-private state: {marker}"

    for capability in (
        "hasLoadedData",
        "refreshEvidence",
        "reportDate",
        "isLoading",
        "isEditing",
        "automaticRefreshAllowed",
        "refreshScopeKey",
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
        "setTimeout(",
        "setInterval(",
    ):
        assert marker not in source, f"page lifecycle boundary must not own coordinator state: {marker}"

    for page in ("overview", "timeline", "statistics", "rules", "settings"):
        assert f'extendPage("{page}"' in source


def test_page_lifecycle_boundary_is_packaged() -> None:
    from pathlib import Path

    spec = (Path(__file__).resolve().parents[2] / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'page_lifecycle.js'" in spec
