from __future__ import annotations

import re

import pytest

from static_helpers import FRONTEND_RESOURCE_FILES, func_body, read_all_js, read_js, read_resource

pytestmark = [pytest.mark.webview_static, pytest.mark.contract, pytest.mark.live_display]


def _assigned_app_function(source: str, name: str) -> str:
    marker = f"App.{name} = function ("
    start = source.find(marker)
    assert start != -1, f"frontend must assign App.{name}"
    end = source.find("\n    };", start)
    assert end != -1, f"App.{name} assignment must close"
    return source[start:end]


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


def test_frontend_live_identity_excludes_candidate_metadata_and_retired_states():
    """Continuity is backend-owned persisted-row identity, not inference metadata."""
    source = read_all_js()
    for forbidden in (
        "candidate_project",
        "current_candidate_project",
        "suggested_project_name",
        "inferred_project_name",
        "project_transition",
        "current_only_pending",
        "borrowed_anchor_pending",
        "virtual_pending",
        "absorbed_pending",
        "current_only_zero",
        "borrowed_anchor_static",
        "is_virtual_live",
        "is_virtual",
        "virtual-live",
    ):
        assert forbidden not in source, (
            "frontend identity/rendering must not consume retired live semantics: "
            + forbidden
        )

    declared_owners = {
        "runtimeIdentityFromPayload": read_js("init.js"),
        "runtimeVisualContinuityKey": read_js("init.js"),
    }
    assigned_owners = {
        "liveContinuityKey": read_js("core.js"),
        "currentActivityContinuityKey": read_js("core.js"),
    }
    bodies = {
        **{
            name: func_body(owner_source, name)
            for name, owner_source in declared_owners.items()
        },
        **{
            name: _assigned_app_function(owner_source, name)
            for name, owner_source in assigned_owners.items()
        },
    }
    for function_name, body in bodies.items():
        for forbidden in (
            "candidate_project",
            "current_candidate_project",
            "suggested_project_name",
            "inferred_project_name",
            "project_transition",
        ):
            assert forbidden not in body, (
                function_name + " must not use candidate metadata as identity: " + forbidden
            )


def test_frontend_uses_only_single_live_delta_clock_fields():
    source = read_all_js()
    for forbidden in (
        "baseline_epoch_ms",
        "snapshot_baseline_epoch_ms",
        "snapshot_at_epoch_ms",
        "liveClockByPage",
        "liveClockBySpanId",
        "activeSpanClockByPage",
    ):
        assert forbidden not in source, (
            "frontend must not restore a second live clock: " + forbidden
        )


def test_apply_local_ticker_never_reads_structural_caches_or_bridge():
    core = read_js("core.js")
    init = read_js("init.js")
    assert "applyLocalTicker" not in core
    body = _assigned_app_function(init, "applyLocalTicker")
    forbidden = (
        "lastOverviewSnapshot",
        "lastRecentData",
        "lastTimelineData",
        "lastSessionDetailsViewModel",
        "callBridge",
        "pywebview",
        "App.bridge",
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
        'type="module"',
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


def test_live_duration_targets_use_exact_clock_and_accepted_runtime():
    source = read_all_js()
    core = read_js("core.js")
    init = read_js("init.js")
    ticker = _assigned_app_function(init, "applyLocalTicker")
    assert "liveRuntimeStore.get()" in ticker
    assert "App.readLiveClockTarget(target)" in ticker
    assert "App.liveTargetCompatibleWithRuntime(target, runtime)" in ticker
    assert "App.renderLiveDurationTarget(target, clock, Date.now())" in ticker
    assert "App.getActiveLiveClock = function" in init
    assert "App.getActiveLiveClock ? App.getActiveLiveClock() : null" in core
    assert source.count("App.getActiveLiveClock") == 2
    for retired in (
        "projectAcceptedClock(clock",
        "data-display-base-seconds",
        "data-live-base-seconds",
    ):
        assert retired not in source


def test_runtime_transport_and_clock_have_one_frontend_owner():
    source = read_all_js()
    core = read_js("core.js")
    init = read_js("init.js")
    for retired in (
        "runtimeIdentityFromPayload",
        "acceptLiveRuntimePayload",
        "acceptRefreshStateRuntime",
        "acceptPagePayloadRuntime",
        "applyLocalTicker",
        "rebaseIncomingClockWithoutRollback",
        "findClockInPayload",
        "activity_display_model",
    ):
        assert retired not in core
    for required in (
        "runtimeIdentityFromPayload",
        "acceptLiveRuntimePayload",
        "acceptRefreshStateRuntime",
        "acceptPagePayloadRuntime",
        "App.applyLocalTicker",
        "App.getActiveLiveClock = function",
        "Number(envelope.schema_version) !== 2",
    ):
        assert required in init
    assert source.count("setInterval(") == 1
    assert init.count("setInterval(") == 1
    assert "schema_version || 0) !== 1" not in source
