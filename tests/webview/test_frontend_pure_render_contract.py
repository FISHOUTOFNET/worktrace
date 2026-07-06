from __future__ import annotations

import re

import pytest

from static_helpers import FRONTEND_RESOURCE_FILES, func_body, read_all_js, read_js, read_resource

pytestmark = [pytest.mark.webview_static, pytest.mark.contract, pytest.mark.live_display]


def test_frontend_has_no_second_live_clock_registry():
    source = read_all_js()
    forbidden = (
        "liveClockByPage",
        "activeSpanClockByPage",
        "recentClock",
        "timelineClock",
        "detailsClock",
        "kpiClock",
    )
    offenders = [token for token in forbidden if token in source]
    assert not offenders, "frontend must not grow page-specific live clocks: " + repr(offenders)


def test_apply_local_ticker_never_reads_structural_caches_or_bridge():
    body = func_body(read_js("core.js"), "applyLocalTicker")
    forbidden = (
        "lastOverviewSnapshot",
        "lastRecentData",
        "lastTimelineData",
        "lastSessionDetailsViewModel",
        "callBridge",
        "pywebview",
    )
    offenders = [token for token in forbidden if token in body]
    assert not offenders, (
        "applyLocalTicker must be DOM-only and must not derive live seconds "
        "from structural caches: " + repr(offenders)
    )


def test_frontend_does_not_decide_live_materialization_from_threshold_or_status():
    source = read_all_js()
    threshold_patterns = (
        r"duration_seconds\s*[><]=?\s*30",
        r"elapsed_seconds\s*[><]=?\s*30",
        r"HISTORY_PERSIST_THRESHOLD",
    )
    offenders = [pattern for pattern in threshold_patterns if re.search(pattern, source)]
    assert not offenders, (
        "frontend must not decide history/materialization from 30s thresholds: "
        + repr(offenders)
    )
    for token in ("materialize_recent", "materialize_timeline", "materialize_details"):
        assert token not in source, (
            "frontend must consume backend materialized rows, not decide " + token
        )


def test_frontend_resources_have_no_storage_network_cdn_or_module_pipeline():
    offenders: list[str] = []
    forbidden = (
        "localStorage",
        "sessionStorage",
        "XMLHttpRequest",
        "fetch(",
        "navigator.sendBeacon",
        "type=\"module\"",
        "type='module'",
        "http://",
        "https://",
        "cdn.",
    )
    for filename in FRONTEND_RESOURCE_FILES:
        source = read_resource(filename)
        for token in forbidden:
            if token in source:
                offenders.append(f"{filename}: {token}")
    assert not offenders, "frontend resources must remain local classic pure render: " + repr(offenders)


def test_live_duration_targets_use_backend_display_base_and_accepted_runtime():
    source = read_all_js()
    ticker = func_body(read_js("core.js"), "applyLocalTicker")
    assert "App.liveRuntime" in source
    assert "getActiveLiveClock()" in ticker
    assert 'data-display-base-seconds' in source
    assert "computeActiveElapsedNow(clock" in ticker
    assert "renderLiveDurationTarget(target, displayBaseSeconds, activeElapsedNowValue)" in ticker
    assert "data-live-base-seconds" in source

