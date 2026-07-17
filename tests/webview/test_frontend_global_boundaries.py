"""Global WebView resource and fixed-client boundary contracts."""

from __future__ import annotations

import re
import sys

import pytest

from static_helpers import (
    ALL_JS_FILES,
    FRONTEND_RESOURCE_FILES,
    JS_DIR,
    NO_STORAGE_FILES,
    REPO_ROOT,
    WEBVIEW_UI_DIR,
    func_body,
    read_all_js,
    read_js,
    read_resource,
)

pytestmark = [
    pytest.mark.contract,
    pytest.mark.webview_static,
    pytest.mark.security_privacy,
]


def _is_defined(source: str, name: str) -> bool:
    declaration = re.search(r"\bfunction\s+" + re.escape(name) + r"\s*\(", source)
    assignment = re.search(
        r"\bApp\." + re.escape(name) + r"\s*=\s*function\b",
        source,
    )
    return bool(declaration or assignment)


def test_frontend_resource_set_is_complete_and_ordered() -> None:
    assert (WEBVIEW_UI_DIR / "index.html").is_file()
    assert (WEBVIEW_UI_DIR / "styles.css").is_file()
    assert (WEBVIEW_UI_DIR / "bridge.py").is_file()
    assert JS_DIR.is_dir()
    assert ALL_JS_FILES

    referenced = set(ALL_JS_FILES)
    on_disk = {path.name for path in JS_DIR.glob("*.js")}
    assert referenced == on_disk

    index = read_resource("index.html")
    positions = []
    for name in ALL_JS_FILES:
        assert "/" not in name and "\\" not in name and name.endswith(".js")
        marker = 'src="js/' + name + '"'
        positions.append(index.index(marker))
    assert positions == sorted(positions)
    assert 'src="app.js"' not in index
    assert not (WEBVIEW_UI_DIR / "app.js").exists()


@pytest.mark.parametrize("filename", FRONTEND_RESOURCE_FILES)
def test_frontend_resources_are_local_and_traceback_free(filename: str) -> None:
    source = read_resource(filename)
    assert not re.search(r"https?://", source, re.IGNORECASE)
    assert not re.search(r"\bcdn\b", source, re.IGNORECASE)
    assert not re.search(r"google\s*fonts", source, re.IGNORECASE)
    assert "traceback" not in source.lower()


@pytest.mark.parametrize("filename", NO_STORAGE_FILES)
def test_frontend_resources_do_not_persist_browser_state(filename: str) -> None:
    source = read_resource(filename)
    assert "localStorage" not in source
    assert "sessionStorage" not in source
    assert "document.cookie" not in source


def test_frontend_modules_share_one_namespace_and_iife_boundary() -> None:
    forbidden_patterns = (
        r"\bimport\s+[\w{}\s,]+\s+from\s",
        r"\bimport\s*\{",
        r"\bimport\s+['\"]",
        r"\bexport\s+default\b",
        r"\bexport\s*\{",
        r"\bexport\s+(?:const|let|var|function)\s+\w+",
        r"\brequire\s*\(",
    )
    for name in ALL_JS_FILES:
        source = read_js(name).strip()
        assert "var App = window.WorkTraceApp = window.WorkTraceApp || {};" in source
        assert "(function () {" in source[:400]
        assert source.endswith("})();")
        for pattern in forbidden_patterns:
            assert not re.search(pattern, source), (
                "js/" + name + " must not use module-loader syntax: " + pattern
            )


def test_only_init_module_owns_pywebview_and_startup_wiring() -> None:
    for name in ALL_JS_FILES:
        source = read_js(name)
        if name == "init.js":
            assert "window.pywebview.api" in source
            assert "DOMContentLoaded" in source
        else:
            assert "window.pywebview.api" not in source
            assert "DOMContentLoaded" not in source

    init = read_js("init.js")
    assert "App.callBridge" not in init
    assert "App.bridge = Object.freeze" in init
    assert "function invokeBridge" in init


def test_fixed_bridge_surface_is_not_dynamically_addressable() -> None:
    source = read_all_js()
    assert "App.callBridge" not in source
    assert "window.pywebview.api[method]" in read_js("init.js")
    for name in ALL_JS_FILES:
        if name != "init.js":
            assert "invokeBridge(" not in read_js(name)
            assert "fixedBridgeMethod(" not in read_js(name)


def test_critical_frontend_capabilities_remain_defined() -> None:
    source = read_all_js()
    required = (
        "showError",
        "clearError",
        "showTimelineError",
        "clearTimelineError",
        "handleResult",
        "showStatus",
        "safeText",
        "escapeHtml",
        "formatTimeRange",
        "shiftDate",
        "localTodayStr",
        "formatDuration",
        "showOverview",
        "showRecent",
        "showTimeline",
        "selectTimelineSession",
        "loadSessionDetails",
        "renderSessionDetails",
        "loadTimeline",
        "refreshTimeline",
        "loadProjects",
        "saveEdit",
        "cancelEdit",
        "loadStatisticsExportSummary",
        "showStatistics",
        "renderStatsTable",
        "validateStatisticsDateRange",
        "exportStatisticsCsv",
        "refreshAll",
        "togglePause",
        "switchPage",
        "initNav",
        "initButtons",
        "startHeartbeat",
        "init",
    )
    missing = [name for name in required if not _is_defined(source, name)]
    assert not missing, "missing frontend capabilities: " + ", ".join(missing)


def test_frontend_state_is_namespaced() -> None:
    source = read_all_js()
    code = "\n".join(line.split("//", 1)[0] for line in source.splitlines())
    state_names = (
        "timelineDate",
        "timelineLoaded",
        "timelineLoading",
        "timelineRequestToken",
        "projectsCache",
        "projectsLoading",
        "currentSessions",
        "editingSession",
        "editSaving",
        "statisticsLoaded",
        "statisticsLoading",
        "statisticsRequestToken",
        "statisticsExportSaving",
        "lastTimelineData",
    )
    bare = []
    for name in state_names:
        pattern = re.compile(r"(?<![\w.])" + re.escape(name) + r"(?!\w)")
        if pattern.search(code):
            bare.append(name)
    assert not bare, "frontend state accessed without App namespace: " + ", ".join(bare)


def test_overview_surface_has_required_user_contracts() -> None:
    index = read_resource("index.html")
    for label in ("概览", "时间详情", "统计与导出", "项目规则", "设置与隐私"):
        assert label in index
    for dom_id in (
        "kpi-date",
        "kpi-total",
        "kpi-projects",
        "kpi-classified",
        "kpi-uncategorized",
        "current-activity",
        "recent-list",
        "overview-error",
        "toggle-pause-btn",
        "status-display",
    ):
        assert 'id="' + dom_id + '"' in index
    assert "WebView 迁移中" not in index


def test_overview_uses_numeric_live_bases_and_safe_error_surface() -> None:
    source = read_all_js()
    assert "overview-error" in source
    assert "showError" in source and "clearError" in source
    assert "kpi_live_base" in source
    assert "classified_seconds" in source
    assert "uncategorized_seconds" in source

    body = func_body(read_js("overview.js"), "showOverview")
    assert "classified_seconds" in body
    assert "uncategorized_seconds" in body
    assert "classified_duration" not in body
    assert "uncategorized_duration" not in body


def test_startup_waits_for_privacy_notice_before_refresh_and_heartbeat() -> None:
    body = func_body(read_js("init.js"), "init()")
    notice = body.index("App.loadFirstRunNotice()")
    refresh = body.index("refreshCurrentPageData(state")
    heartbeat = body.index("startHeartbeat()")
    assert notice < refresh
    assert notice < heartbeat
    assert ".then(function" in body[notice:refresh]


def test_local_ticker_never_calls_backend() -> None:
    core = read_js("core.js")
    body = func_body(core, "applyLocalTicker")
    assert "App.applyLocalTicker" in core
    assert "callBridge" not in body
    assert "App.bridge" not in body
    assert "App.LOCAL_TICKER_INTERVAL_MS" not in core
    assert "App.REFRESH_INTERVAL_MS" not in core


def test_packaging_includes_current_frontend_resources() -> None:
    spec = (REPO_ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "styles.css" in spec and "index.html" in spec
    for name in ALL_JS_FILES:
        assert name in spec
    assert "app.js" not in spec


def test_webview_entry_is_import_safe_and_resolves_resources(monkeypatch) -> None:
    import worktrace.webview_main as webview_main

    assert callable(webview_main.main)
    assert webview_main.resource_path("index.html").is_file()

    monkeypatch.setitem(sys.modules, "webview", None)
    with pytest.raises(RuntimeError) as exc_info:
        webview_main._check_pywebview_available()
    assert "pywebview" in str(exc_info.value)
    assert "未安装" in str(exc_info.value)
