"""unified heartbeat + live display projection contracts.

These static-contract tests verify the frontend pieces introduced by the
unified heartbeat rewrite:

- A single 1-second ``startHeartbeat`` timer owns all periodic work.
  the ``REFRESH_INTERVAL_MS`` / ``LOCAL_TICKER_INTERVAL_MS``
  constants, the ``App.refreshTimer`` / ``App.localTickerTimer`` state
  vars, and the ``startAutoRefresh`` / ``startLocalTicker`` standalone
  functions have all been removed entirely; ``startHeartbeat`` only
  manages ``App.heartbeatTimer``.
- The heartbeat first applies ``applyLocalTicker`` (DOM-only duration
  updates), then runs a lightweight ``get_refresh_state`` revision check
  under an in-flight guard; heavy interfaces are only invoked when the
  structural ``refresh_revision`` changes.
- Recent / Timeline session / Timeline detail rows carry ``duration_seconds``
  + stable data attributes so the ticker can increment durations without
  a bridge round-trip and without re-rendering the whole list.
- ``renderDurationMonotonic`` prevents 1-2s visual rollback on the same
  live continuity target while still allowing backend truth to override
  on activity / session / date changes.
- Statistics / Export shows a closed-only hint reminding the user that
  in-progress activities are not included.
"""

from __future__ import annotations

import os
import re
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static, pytest.mark.live_display]

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import (
    WEBVIEW_UI_DIR,
    read_all_js,
    read_js,
    func_body,
)




def test_heartbeat_single_timer_replaces_parallel_timers():
    """there must be exactly one 1-second timer
    (``App.heartbeatTimer``). the ``App.refreshTimer`` /
    ``App.localTickerTimer`` state vars, the removed
    ``REFRESH_INTERVAL_MS`` / ``LOCAL_TICKER_INTERVAL_MS`` constants,
    and the ``startAutoRefresh`` / ``startLocalTicker`` standalone
    functions have all been removed entirely. ``startHeartbeat`` is the
    only timer driver and only manages ``App.heartbeatTimer``."""
    init_source = read_js("init.js")
    core_source = read_js("core.js")
    # The heartbeat starter must exist and arm App.heartbeatTimer.
    assert "function startHeartbeat" in init_source, (
        "init.js must define function startHeartbeat for the unified heartbeat"
    )
    assert "App.heartbeatTimer = setInterval" in init_source, (
        "startHeartbeat must arm App.heartbeatTimer with setInterval"
    )
    # App.heartbeatTimer is the ONLY timer state; the removed timer
    # state vars must NOT appear anywhere in init.js.
    assert "App.refreshTimer" not in init_source, (
        "init.js must not reference the removed App.refreshTimer state; "
        "startHeartbeat only manages App.heartbeatTimer"
    )
    assert "App.localTickerTimer" not in init_source, (
        "init.js must not reference the removed App.localTickerTimer state; "
        "startHeartbeat only manages App.heartbeatTimer"
    )
    # The removed interval constants must NOT appear in core.js.
    assert "REFRESH_INTERVAL_MS" not in core_source, (
        "core.js must not define the removed REFRESH_INTERVAL_MS constant"
    )
    assert "LOCAL_TICKER_INTERVAL_MS" not in core_source, (
        "core.js must not define the removed LOCAL_TICKER_INTERVAL_MS constant"
    )
    # The old standalone starter functions must NOT exist as function
    # definitions in init.js (they would create parallel timers,
    # violating section 8).
    assert "function startAutoRefresh" not in init_source, (
        "init.js must not define a startAutoRefresh function; the unified "
        "heartbeat owns the single timer"
    )
    assert "function startLocalTicker" not in init_source, (
        "init.js must not define a startLocalTicker function; the unified "
        "heartbeat owns the single timer"
    )
    assert read_all_js().count("setInterval") == 1, (
        "frontend must have exactly one periodic timer: the heartbeat"
    )


def test_heartbeat_interval_is_one_second():
    """the heartbeat must tick at 1-second cadence so the
    displayed durations update every second without jumps."""
    source = read_js("core.js")
    assert "App.HEARTBEAT_INTERVAL_MS = 1000" in source, (
        "core.js must define App.HEARTBEAT_INTERVAL_MS = 1000"
    )


def test_heartbeat_runs_ticker_then_revision_check():
    """each heartbeat tick must first run the local ticker
    (display continuity) and then run the lightweight revision check
    (under in-flight guard). This guarantees the display is always
    advanced before any heavy refresh is triggered."""
    source = read_js("init.js")
    body = func_body(source, "startHeartbeat")
    # The ticker call must appear before the revision-check call inside
    # the setInterval callback.
    ticker_pos = body.find("App.applyLocalTicker")
    revision_pos = body.find("runRevisionCheck")
    assert ticker_pos != -1, (
        "startHeartbeat must call App.applyLocalTicker each tick"
    )
    assert revision_pos != -1, (
        "startHeartbeat must call runRevisionCheck each tick"
    )
    assert ticker_pos < revision_pos, (
        "startHeartbeat must run the local ticker before the revision check"
    )


def test_init_does_not_call_removed_start_auto_refresh():
    """``init()`` must not call the ``startAutoRefresh()``
    or a standalone ``startLocalTicker()``. Only ``refreshCurrentPageData()``
    + ``startHeartbeat()`` are permitted after the first-run notice is
    confirmed."""
    source = read_js("init.js")
    body = func_body(source, "init")
    assert "startAutoRefresh()" not in body, (
        "init() must not call startAutoRefresh(); it is replaced by "
        "startHeartbeat"
    )
    # A standalone startLocalTicker() call is also forbidden; the
    # heartbeat owns the only timer.
    assert "startLocalTicker()" not in body, (
        "init() must not call a standalone startLocalTicker(); the "
        "heartbeat owns the only timer"
    )


def test_revision_check_has_in_flight_guard():
    """``runRevisionCheck`` must guard against overlapping
    ``get_refresh_state`` round-trips so the heartbeat never stacks
    concurrent bridge requests."""
    source = read_js("init.js")
    body = func_body(source, "runRevisionCheck")
    assert "App.refreshCheckInFlight" in body, (
        "runRevisionCheck must use App.refreshCheckInFlight as an in-flight guard"
    )
    assert "get_refresh_state" in body, (
        "runRevisionCheck must call get_refresh_state"
    )


def test_revision_check_does_not_use_elapsed_as_change_signal():
    """``refresh_revision`` must NOT change when only
    ``elapsed_seconds`` / ``extra_seconds`` / ``snapshot_updated_at``
    advance. The frontend must not use these fields as a revision-change
    signal. This test verifies the frontend does not compute its own
    revision from those fields (the backend ``get_refresh_state`` payload
    is the only source of ``refresh_revision``)."""
    source = read_js("init.js")
    body = func_body(source, "runRevisionCheck")
    # The revision check must read ``refresh_revision`` from the backend
    # payload, not compute one itself from elapsed fields.
    assert "refresh_revision" in body, (
        "runRevisionCheck must read refresh_revision from the backend payload"
    )
    # The revision check must NOT compute its own revision from
    # elapsed_seconds / extra_seconds / snapshot_updated_at. These fields
    # advance every second and would trigger a heavy refresh every tick.
    assert "elapsed_seconds" not in body, (
        "runRevisionCheck must not use elapsed_seconds as a change signal"
    )
    assert "extra_seconds" not in body, (
        "runRevisionCheck must not use extra_seconds as a change signal"
    )


def test_revision_unchanged_does_not_trigger_heavy_refresh():
    """when ``refresh_revision`` is unchanged, the revision
    check must NOT call ``get_overview`` / ``get_recent_activities`` /
    ``get_timeline`` / ``loadProjectRules``. Only the sidebar status is
    updated from the refresh_state payload (no extra bridge call)."""
    source = read_js("init.js")
    body = func_body(source, "runRevisionCheck")
    # The unchanged-revision branch must call refreshStatusFromRefreshState
    # (which uses the payload directly) rather than refreshCurrentPageData.
    assert "refreshStatusFromRefreshState" in source, (
        "init.js must define refreshStatusFromRefreshState for the "
        "unchanged-revision branch"
    )
    # The unchanged branch must NOT call the heavy refresh helpers.
    # We check that refreshCurrentPageData is only called from the
    # revision-CHANGED branch (inside the if-block), not unconditionally.
    rcp_pos = body.find("refreshCurrentPageData(state")
    assert rcp_pos != -1, (
        "runRevisionCheck must call refreshCurrentPageData on revision change"
    )
    # The refreshStatusFromRefreshState call must also be present in the
    # body (the unchanged branch).
    assert body.find("refreshStatusFromRefreshState") != -1, (
        "runRevisionCheck must call refreshStatusFromRefreshState on "
        "revision unchanged"
    )


def test_heartbeat_does_not_auto_call_load_project_rules():
    """the heartbeat / revision-check / low-frequency
    reconciliation must NOT call ``loadProjectRules()``. Rules are only
    refreshed on user navigation / manual refresh / rules write."""
    source = read_js("init.js")
    # runRevisionCheck body must not reference loadProjectRules.
    body = func_body(source, "runRevisionCheck")
    assert "loadProjectRules" not in body, (
        "runRevisionCheck must not call loadProjectRules"
    )
    # fullReconcileCollectionViews body must not reference loadProjectRules.
    rec_body = func_body(source, "fullReconcileCollectionViews")
    assert "loadProjectRules" not in rec_body, (
        "fullReconcileCollectionViews must not call loadProjectRules"
    )


def test_low_frequency_reconciliation_exists():
    """a low-frequency reconciliation must exist so a stalled
    revision signal cannot freeze the UI forever. It must delegate through
    ``refreshCurrentPageData`` so refresh_state is accepted before the
    current page payload is rendered.

    The delegated path refreshes status plus the current page and owns the
    Timeline editing guard."""
    source = read_js("init.js")
    assert "function fullReconcileCollectionViews" in source, (
        "init.js must define fullReconcileCollectionViews for low-frequency "
        "collection reconciliation"
    )
    body = func_body(source, "fullReconcileCollectionViews")
    assert "refreshCurrentPageData" in body, (
        "fullReconcileCollectionViews must reuse refreshCurrentPageData"
    )
    assert "refreshStatus" not in body, (
        "fullReconcileCollectionViews must not bypass refresh_state by "
        "calling refreshStatus directly"
    )
    assert "refreshOverview" not in body, (
        "fullReconcileCollectionViews must not bypass refresh_state by "
        "calling refreshOverview directly"
    )
    assert "refreshOverviewBundle" not in body, (
        "fullReconcileCollectionViews must not reference the removed "
        "refreshOverviewBundle wrapper"
    )
    # Must NOT reference Rules / Settings / Statistics.
    assert "loadProjectRules" not in body
    assert "loadSettingsPrivacyStatus" not in body
    assert "loadStatisticsExportSummary" not in body


def test_low_frequency_reconciliation_skips_timeline_when_editing():
    """the low-frequency reconciliation must NOT re-render
    the Timeline when an editor / split editor / correction shell write
    is in progress so the user's input focus is preserved."""
    source = read_js("init.js")
    body = func_body(source, "fullReconcileCollectionViews")
    refresh_body = func_body(source, "refreshCurrentPageData")
    assert "refreshCurrentPageData" in body
    assert "_timelineEditingActive" in refresh_body, (
        "fullReconcileCollectionViews must delegate to the current-page "
        "refresh path that guards Timeline re-render with App._timelineEditingActive()"
    )


def test_timeline_edit_guard_does_not_block_current_activity_header_refresh():
    """Timeline editing protects editable inputs/details, not the live
    current-activity header/state text."""
    src = _strip_js_comments(read_js("init.js"))
    refresh_body = func_body(src, "refreshCurrentPageData")
    assert "refreshCurrentActivityFromState" in refresh_body, (
        "refreshCurrentPageData must refresh Timeline current activity from "
        "the latest refresh-state payload even when full Timeline rendering "
        "is edit-guarded"
    )
    assert "if (typeof App._timelineEditingActive" in refresh_body, (
        "full Timeline rendering may still be protected by the edit guard"
    )


def test_run_revision_check_updates_timeline_header_before_guarded_refresh():
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    accept_index = body.find("acceptRefreshStateRuntime(state")
    header_index = body.find("refreshCurrentActivityFromState(state", accept_index)
    refresh_index = body.find("refreshCurrentPageData(state", accept_index)
    assert header_index != -1 and refresh_index != -1 and header_index < refresh_index, (
        "revision-change handling must update the Timeline current header "
        "from backend refresh-state before any guarded page refresh can skip "
        "the list render"
    )


def test_page_switch_immediately_refreshes_current_page():
    """page switch must immediately refresh the current page's
    live data so the user sees fresh data without waiting for the next
    heartbeat revision check."""
    source = read_js("init.js")
    body = func_body(source, "switchPage")
    assert "refreshCurrentPageData" in body, (
        "switchPage must call refreshCurrentPageData to immediately refresh "
        "the current page's live data on navigation"
    )




def test_overview_js_stores_last_recent_data_as_structural_cache():
    """``showRecent`` must save the recent payload to
    ``App.lastRecentData`` as a STRUCTURAL CACHE only — used for
    re-render on page switch / edit-guard checks. It MUST NOT be read by
    ``applyLocalTicker`` as a live-seconds source; live rows use DOM
    bases plus the accepted runtime elapsed. The
    legacy ``lastRecentSnapshot`` name has been retired."""
    source = read_js("overview.js")
    assert "App.lastRecentData" in source, (
        "overview.js must save App.lastRecentData in showRecent (structural cache)"
    )
    assert "App.lastRecentSnapshot" not in source, (
        "overview.js must not reference the retired App.lastRecentSnapshot name; "
        "use App.lastRecentData (structural cache only, not a live-seconds source)"
    )


def test_recent_item_renders_data_index_and_progress_flags():
    """each recent item must render a stable ``data-recent-index``
    attribute and use ``is_in_progress || is_live_projected`` to mark
    in-progress / live-projected rows with CSS classes. Live rows must
    carry display identity plus active elapsed offset attributes so the
    ticker can project them from the single accepted runtime.

    The ``virtual-live`` CSS class is only styling; live ticking is keyed
    by ``data-display-span-id`` for DB-overlay rows and display-only
    ``virtual_pending`` rows alike."""
    source = read_js("overview.js")
    assert 'data-recent-index' in source, (
        "overview.js must render data-recent-index on each recent item"
    )
    assert "is_in_progress" in source, (
        "overview.js must check is_in_progress on recent items"
    )
    assert "is_live_projected" in source, (
        "overview.js must check is_live_projected on recent items"
    )
    assert "in-progress" in source, (
        "overview.js must add the in-progress CSS class to live recent rows"
    )
    assert "live-projected" in source, (
        "overview.js must add the live-projected CSS class to projected rows"
    )
    # Live recent rows must carry display-span-id for identity; duration
    # projection comes from a static display base plus the single active elapsed.
    assert "data-display-span-id" in source, (
        "overview.js must render data-display-span-id on live recent rows so "
        "the ticker can keep stable identity"
    )
    assert "data-live-duration-target" in source, (
        "overview.js must render unified live duration targets on live rows"
    )
    assert "data-display-base-seconds" in source, (
        "overview.js must render data-display-base-seconds on live rows"
    )


def test_recent_item_prefers_duration_seconds_over_string():
    """recent items must prefer ``duration_seconds`` (raw int)
    over the formatted ``duration`` string so the ticker / monotonic
    helper can recompute from a stable baseline."""
    source = read_js("overview.js")
    assert "duration_seconds" in source, (
        "overview.js must use duration_seconds as the primary duration source"
    )
    assert "formatDuration" in source, (
        "overview.js must format duration_seconds via App.formatDuration"
    )


def test_timeline_js_stores_last_session_details_view_model_as_structural_cache():
    """``renderSessionDetails`` must save the details payload to
    ``App.lastSessionDetailsViewModel`` as a STRUCTURAL CACHE only — used
    for re-render on page switch / edit-guard checks. It MUST NOT be read
    by ``applyLocalTicker`` as a live-seconds source; DOM anchors plus
    the accepted live runtime is the single projection path for
    live durations. The legacy ``lastSessionDetailsData`` name has been
    retired to remove the old ticker-source semantics."""
    source = read_js("timeline.js")
    assert "App.lastSessionDetailsViewModel" in source, (
        "timeline.js must save App.lastSessionDetailsViewModel in "
        "renderSessionDetails (structural cache)"
    )
    assert "App.lastSessionDetailsData" not in source, (
        "timeline.js must not reference the retired App.lastSessionDetailsData "
        "name; use App.lastSessionDetailsViewModel (structural cache only, not a "
        "live-seconds source)"
    )


def test_timeline_detail_row_renders_data_attributes():
    """each summary row must render ``data-summary-id``,
    ``data-summary-index``, and ``data-duration-seconds`` attributes so
    the ticker can locate rows precisely without relying on array index."""
    source = read_js("timeline.js")
    assert 'data-summary-id' in source, (
        "timeline.js must render data-summary-id on summary rows"
    )
    assert 'data-summary-index' in source, (
        "timeline.js must render data-summary-index on summary rows"
    )
    assert 'data-duration-seconds' in source, (
        "timeline.js must render data-duration-seconds on detail rows"
    )


def test_timeline_detail_row_prefers_duration_seconds():
    """detail rows must prefer ``duration_seconds`` (raw int)
    over the formatted ``duration`` string."""
    source = read_js("timeline.js")
    assert "duration_seconds" in source, (
        "timeline.js must use duration_seconds as the primary detail source"
    )


def test_timeline_session_renders_data_session_id():
    """timeline session items must render ``data-session-id``
    so the ticker can locate each session's DOM precisely without relying
    on array index."""
    source = read_js("timeline.js")
    assert 'data-session-id' in source, (
        "timeline.js must render data-session-id on session items"
    )




def test_core_js_defines_monotonic_render_helpers():
    """core.js must define the monotonic-render helpers used by
    the unified live clock (``live_started_at_epoch_ms + carry_seconds``).
    The ticker computes live deltas from ``live_started_at_epoch_ms`` +
    ``carry_seconds`` directly; no separate projection helper
    exists."""
    source = read_js("core.js")
    for name in (
        "readDurationSecondsFromText",
        "renderDurationMonotonic",
        "resetMonotonicRenderState",
    ):
        assert "function " + name in source, (
            "core.js must define function " + name
        )
        assert "App." + name in source, (
            "core.js must expose App." + name
        )


def test_ticker_uses_render_duration_projected():
    """the ticker must use ``renderDurationProjected`` for
    Overview KPIs, recent items, Timeline sessions, and Timeline details
    so the same no-rollback render contract is applied everywhere."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    assert "renderLiveDurationTarget" in body, (
        "applyLocalTicker must delegate duration updates to renderLiveDurationTarget"
    )


def test_ticker_does_not_call_bridge_methods():
    """the ticker must NOT call ``callBridge`` /
    ``App.callBridge``. It only updates DOM text and never triggers a
    backend round-trip."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    assert "callBridge" not in body, (
        "applyLocalTicker must not call callBridge; the ticker is cosmetic"
    )


def test_ticker_does_not_use_browser_storage():
    """the ticker must NOT use browser storage APIs
    (localStorage / sessionStorage). All state lives in the in-memory
    App namespace."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    assert "localStorage" not in body, (
        "applyLocalTicker must not use localStorage"
    )
    assert "sessionStorage" not in body, (
        "applyLocalTicker must not use sessionStorage"
    )


def test_ticker_locates_live_targets_via_data_live_duration_target():
    """the ticker must walk every DOM node carrying
    ``data-live-duration-target`` (via ``querySelectorAll``) and render it
    from that node's display base plus the page active elapsed.
    This is the single DOM-walk path for every live duration — the old
    per-region ``[data-session-id="..."]`` selectors are gone."""
    source = read_js("core.js")
    body = func_body(source, "applyLocalTicker")
    # The unified selector + DOM walk drive every live row.
    assert 'data-live-duration-target' in body, (
        "applyLocalTicker must use the unified live duration target selector"
    )
    assert 'querySelectorAll' in body, (
        "applyLocalTicker must walk DOM nodes via querySelectorAll"
    )
    assert 'renderLiveDurationTarget' in body, (
        "applyLocalTicker must render live targets via display base + active elapsed"
    )


def test_ticker_skips_detail_updates_when_editing():
    """the ticker only updates DOM text and never re-renders lists,
    so it no longer needs the ``_timelineEditingActive`` guard itself.
    The editing guard has moved to the page-refresh / reconciliation
    level (``refreshCurrentPageData`` / ``fullReconcileCollectionViews``)
    which DO re-render lists. ``_timelineEditingActive`` must still be
    defined in ``core.js`` via ``function timelineEditingActive``."""
    core_source = read_js("core.js")
    assert "function timelineEditingActive" in core_source, (
        "core.js must still define function timelineEditingActive so the "
        "page-refresh / reconciliation paths can guard against editing"
    )
    init_source = read_js("init.js")
    refresh_body = func_body(init_source, "refreshCurrentPageData")
    reconcile_body = func_body(init_source, "fullReconcileCollectionViews")
    assert "_timelineEditingActive" in refresh_body or "_timelineEditingActive" in reconcile_body, (
        "the editing guard must live in refreshCurrentPageData or "
        "fullReconcileCollectionViews (the page-refresh / reconciliation paths), "
        "not in applyLocalTicker"
    )


def test_render_duration_projected_prevents_any_same_continuity_rollback():
    """``renderDurationProjected`` must keep the current visual value
    whenever the new projected seconds are less than the last rendered
    value for the same live continuity. State / activity / session / date
    changes still allow factual backend overwrite with ``allowDecrease``."""
    source = read_js("core.js")
    body = func_body(source, "renderDurationProjected")
    # Must check allowDecrease and compare lastSeconds vs next.
    assert "allowDecrease" in body, (
        "renderDurationProjected must accept an allowDecrease option"
    )
    assert "lastSeconds" in body, (
        "renderDurationProjected must track lastSeconds per continuity key"
    )
    assert "next = entry.lastSeconds" in body, (
        "renderDurationProjected must clamp any same-continuity rollback"
    )


def test_render_duration_monotonic_allows_overwrite_on_state_change():
    """when the activity / session / date changes, the backend
    truth must be allowed to overwrite the displayed value. This is
    implemented by seeding ``_monotonicRenderState`` from the backend
    refresh (in showOverview / showRecent / showTimeline /
    renderSessionDetails) so the next tick's monotonic guard starts from
    the new fetched value instead of the old one."""
    for module in ("overview.js", "timeline.js"):
        source = read_js(module)
        assert "_monotonicRenderState" in source, (
            module + " must seed App._monotonicRenderState after re-render "
            "from the projected-now value"
        )




def test_statistics_page_has_closed_only_hint():
    """the Statistics page must show a closed-only hint
    reminding the user that in-progress activities are not included in
    the statistics summary or the export preview."""
    source = (WEBVIEW_UI_DIR / "index.html").read_text(encoding="utf-8")
    # The hint must appear near both the summary grid and the export preview.
    assert "stats-closed-only-hint" in source, (
        "index.html must define a .stats-closed-only-hint element"
    )
    # The hint text must mention that in-progress activities are not
    # included.
    assert "仅包含已完成活动" in source, (
        "index.html closed-only hint must mention 仅包含已完成活动"
    )
    assert "当前进行中活动不会计入" in source, (
        "index.html closed-only hint must mention 当前进行中活动不会计入"
    )


def test_statistics_page_has_closed_only_hint_css():
    """the closed-only hint must have a dedicated CSS class
    so it is visually distinct from the export hint."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".stats-closed-only-hint" in source, (
        "styles.css must define the .stats-closed-only-hint class"
    )




def test_active_elapsed_projection_helpers_replace_removed_ticker_helpers():
    """``computeActiveElapsedNow`` is the only wall-clock projection helper,
    and ``projectFromDisplayBase`` applies the single live delta formula.
    The old per-region ticker helpers are gone."""
    source = read_js("core.js")
    assert "function computeActiveElapsedNow" in source, (
        "core.js must define computeActiveElapsedNow for the canonical active live time"
    )
    assert "function projectFromDisplayBase" in source, (
        "core.js must define projectFromDisplayBase for row/KPI projection"
    )
    elapsed_body = func_body(source, "computeActiveElapsedNow")
    project_body = func_body(source, "projectFromDisplayBase")
    assert "projectClockSeconds" in elapsed_body, (
        "computeActiveElapsedNow must use the canonical active live time projection"
    )
    assert "activeElapsedNowValue" in project_body, (
        "projectFromDisplayBase must add the single active elapsed value"
    )
    assert "activeElapsedAtRender" not in project_body, (
        "projectFromDisplayBase must not subtract a render-time active offset"
    )
    row_body = func_body(source, "renderLiveDurationTarget")
    assert "projectLiveDeltaSeconds" not in row_body, (
        "row rendering must not use projectLiveDeltaSeconds as the core contract"
    )
    assert "duration_seconds_at_sample" not in row_body, (
        "row rendering must not subtract a row clock duration_seconds_at_sample"
    )
    # Compatibility helpers may exist, but the ticker/row path must not use them.
    ticker_body = func_body(source, "applyLocalTicker")
    assert "projectLiveDeltaSeconds" not in ticker_body
    assert "projectLiveBaseSeconds" not in ticker_body
    assert "function projectLiveDeltaSeconds" not in source, (
        "core.js must not retain the old projectLiveDeltaSeconds projection path"
    )
    assert "function projectLiveBaseSeconds" not in source, (
        "core.js must not retain the old projectLiveBaseSeconds projection path"
    )
    # The removed helpers must NOT be re-introduced.
    assert "function tickerLiveEligible" not in source, (
        "core.js must not re-introduce the removed tickerLiveEligible helper"
    )
    assert "function tickerDeltaSeconds" not in source, (
        "core.js must not re-introduce the removed tickerDeltaSeconds helper"
    )

def test_ticker_uses_unified_clock_not_cached_snapshot():
    """the ticker must NOT read from page-level cached snapshots
    (``rItem.duration_seconds``). It reads DOM anchors and renders rows
    through ``renderLiveDurationTarget`` using the page active live time."""
    source = read_js("core.js")
    body = func_body(source, "applyLocalTicker")
    assert "rItem.duration_seconds" not in body, (
        "applyLocalTicker must not read rItem.duration_seconds from a cached "
        "page-level snapshot; the unified live clock is the single source"
    )
    assert "renderLiveDurationTarget" in body, (
        "applyLocalTicker must render live targets via renderLiveDurationTarget"
    )
    assert "getActiveLiveClock" in body, (
        "applyLocalTicker must read the active clock via getActiveLiveClock()"
    )
    assert "getActiveCurrentActivityClock" not in body, (
        "applyLocalTicker must not read current activity from a separate clock"
    )


def test_ticker_locates_live_rows_via_duration_target():
    """the ticker locates every live duration via the unified
    ``data-live-duration-target`` DOM walk and renders all roles from
    the same active elapsed value."""
    source = read_js("core.js")
    body = func_body(source, "applyLocalTicker")
    assert "data-live-duration-target" in body, (
        "applyLocalTicker must locate live durations via data-live-duration-target"
    )
    assert "computeActiveElapsedNow" in body, (
        "applyLocalTicker must compute the active elapsed once from the page live time"
    )
    assert "is_virtual_live" not in body, (
        "applyLocalTicker must not reference the removed is_virtual_live flag"
    )


def test_ticker_does_not_read_structural_caches_as_live_seconds_source():
    """Spec 三.4: ``applyLocalTicker`` MUST NOT read the structural
    caches (``lastRecentData`` / ``lastSessionDetailsViewModel``) NOR the
    retired legacy names (``lastRecentSnapshot`` /
    ``lastSessionDetailsData``) NOR the old per-region delta
    accumulators (``recentDelta`` / ``tlDelta`` / ``detailDelta``) as a
    live-row seconds computation source. DOM duration anchors plus
    ``computeActiveElapsedNow(getActiveLiveClock())`` are the single source of
    truth for every live ROW duration.

    Live seconds come exclusively from the
    ``[data-live-duration-target="1"]`` DOM walk + ``projectFromDisplayBase``. The
    recent / details structural caches, the retired names, and the old
    delta accumulators must NEVER appear in the ticker body at all.
    """
    source = read_js("core.js")
    body = func_body(source, "applyLocalTicker")
    forbidden = [
        # Retired legacy structural-cache names (old ticker-source semantics).
        "lastRecentSnapshot",
        "lastSessionDetailsData",
        # Current recent / details structural caches — the ticker must NOT
        # read these at all (live rows come from the DOM walk).
        "lastRecentData",
        "lastSessionDetailsViewModel",
        # Old per-region delta accumulators (multi-ticker legacy).
        "recentDelta",
        "tlDelta",
        "detailDelta",
    ]
    for token in forbidden:
        assert token not in body, (
            "applyLocalTicker must not reference '" + token + "'; the unified "
            "active live time + display_base_seconds is the single "
            "live-row seconds source"
        )


def test_page_switch_refresh_does_not_use_boolean_pending_replay():
    """Page-switch refresh must not replay an unscoped boolean pending
    request under a new page/date/runtime context."""
    source = read_js("init.js")
    assert "pendingPageRefresh" not in source
    body = func_body(source, "refreshCurrentPageData")
    assert "get_refresh_state" in body
    assert "acceptRefreshStateRuntime" in body


def test_timeline_editing_guard_covers_open_editors():
    """issue 12: ``_timelineEditingActive`` must cover not just
    saving states but also editors that are OPEN BUT NOT YET SAVED
    (``editingActivityId`` / ``editingSplitActivityId``) and dirty session
    edits (``editingSession`` + ``isEditDirty()``)."""
    source = read_js("core.js")
    body = func_body(source, "timelineEditingActive")
    # Must check open editor IDs (not just saving flags).
    assert "editingActivityId" in body, (
        "timelineEditingActive must check editingActivityId (open editor)"
    )
    assert "editingSplitActivityId" in body, (
        "timelineEditingActive must check editingSplitActivityId (open split)"
    )
    assert "editingSession" in body, (
        "timelineEditingActive must check editingSession + isEditDirty()"
    )
    assert "isEditDirty" in body, (
        "timelineEditingActive must call isEditDirty() for unsaved edits"
    )


def test_render_session_details_skips_rerender_when_editing():
    """issue 17: ``renderSessionDetails`` must NOT re-render the
    detail list (which would overwrite user input) when an inline editor /
    split editor is open and dirty or a save is in progress."""
    source = read_js("timeline.js")
    body = func_body(source, "renderSessionDetails")
    assert "editingActivityId" in body or "editingSplitActivityId" in body, (
        "renderSessionDetails must check open editor IDs before re-rendering"
    )
    assert "isEditDirty" in body or "activityTimeSaving" in body, (
        "renderSessionDetails must check isEditDirty / saving state before "
        "re-rendering so user input is not overwritten"
    )




def test_ticker_renders_per_row_base_plus_live_delta():
    """Rows use Single Live Delta Projection:
    ``display_base_seconds + current_elapsed_now``. The target stores only
    a static base; it does not own a clock or active elapsed offset."""
    source = read_js("core.js")
    project_body = func_body(source, "projectClockSeconds")
    assert "live_started_at_epoch_ms" in project_body, (
        "projectClockSeconds must read live_started_at_epoch_ms from the clock"
    )
    assert "carry_seconds" in project_body, (
        "projectClockSeconds must read carry_seconds from the clock"
    )
    # applyLocalTicker must read each row's base seconds from the DOM.
    ticker_body = func_body(source, "applyLocalTicker")
    assert "data-display-base-seconds" in ticker_body, (
        "applyLocalTicker must read each row's base seconds from the "
        "data-display-base-seconds DOM attribute"
    )
    assert "data-active-elapsed-at-render" not in ticker_body, (
        "applyLocalTicker must not read each row's active elapsed offset"
    )
    row_body = func_body(source, "renderLiveDurationTarget")
    assert "projectFromDisplayBase" in row_body, (
        "renderLiveDurationTarget must compute row base + active elapsed"
    )
    assert "projectLiveDeltaSeconds" not in row_body, (
        "renderLiveDurationTarget must not use per-row clock delta ownership"
    )
    # The removed helper must NOT be re-introduced.
    assert "function tickerDeltaSeconds" not in source, (
        "core.js must not re-introduce the removed tickerDeltaSeconds helper"
    )


def test_live_duration_targets_publish_duration_semantic_contract():
    core = read_js("core.js")
    overview = read_js("overview.js")
    timeline = read_js("timeline.js")

    current_body = func_body(core, "renderCurrentActivityElement")
    assert 'data-duration-semantic="current-live"' in current_body
    assert 'data-display-base-seconds="0"' in current_body

    anchor_body = func_body(core, "setLiveProjectionAnchor")
    assert 'data-duration-semantic", "aggregate-live"' in anchor_body

    assert "duration_semantic" in overview
    assert "data-duration-semantic" in overview
    assert "duration_semantic" in timeline
    assert "data-duration-semantic" in timeline


def test_recent_and_timeline_sessions_do_not_fallback_to_current_live():
    overview_body = func_body(read_js("overview.js"), "showRecent")
    timeline_body = func_body(read_js("timeline.js"), "showTimeline")

    assert 'item.duration_semantic || "current_live"' not in overview_body
    assert 's.duration_semantic || "current_live"' not in timeline_body
    assert "recent_session_missing_duration_semantic" in overview_body
    assert "recent_session_non_aggregate_live" in overview_body
    assert "timeline_session_missing_duration_semantic" in timeline_body
    assert "timeline_session_non_aggregate_live" in timeline_body
    assert 'durationSemantic !== "aggregate-live"' in overview_body
    assert 'sessionDurationSemantic !== "aggregate-live"' in timeline_body


def test_ticker_rejects_current_live_targets_with_nonzero_base():
    source = read_js("core.js")
    ticker_body = func_body(source, "applyLocalTicker")
    assert "data-duration-semantic" in ticker_body
    assert "current-live" in ticker_body
    assert "current_live_target_nonzero_base" in ticker_body
    assert "recordLiveClockContractViolation" in ticker_body


def test_frontend_js_does_not_contain_removed_live_clock_fields():
    """Static boundary test (spec §VIII Live clock boundary): the entire
    frontend JS bundle must NOT contain the removed live-clock
    field names ``snapshot_at_epoch_ms`` or ``baseline_epoch_ms`` anywhere.
    The unified live clock uses only ``live_started_at_epoch_ms`` +
    ``carry_seconds`` and must not regress in comments, fallback logic, or
    payload parsing."""
    all_js = read_all_js()
    assert "snapshot_at_epoch_ms" not in all_js, (
        "frontend JS must not contain the snapshot_at_epoch_ms field; "
        "the unified live clock uses live_started_at_epoch_ms + carry_seconds"
    )
    assert "baseline_epoch_ms" not in all_js, (
        "frontend JS must not contain the baseline_epoch_ms field; "
        "the unified live clock uses live_started_at_epoch_ms + carry_seconds"
    )


def test_ticker_uses_stable_live_key_hash_for_continuity():
    """``liveContinuityKey`` must use
    ``stable_live_key_hash`` as the continuity anchor so the same activity
    survives the virtual → persisted_open transition without a false reset."""
    source = read_js("core.js")
    assert "function liveContinuityKey" in source, (
        "core.js must define function liveContinuityKey"
    )
    body = func_body(source, "liveContinuityKey")
    assert "stable_live_key_hash" in body, (
        "liveContinuityKey must use stable_live_key_hash for continuity"
    )


def test_overview_has_request_token():
    """``refreshOverview`` must use a request token
    so stale responses cannot overwrite newer ones."""
    source = read_js("init.js")
    assert "App.overviewRequestToken" in source, (
        "init.js must define App.overviewRequestToken state"
    )
    body = func_body(source, "refreshOverview")
    assert "overviewRequestToken" in body, (
        "refreshOverview must use overviewRequestToken for stale-response discard"
    )


def test_recent_has_request_token():
    """The Overview refresh must use a request token so stale
    responses cannot overwrite newer recent-activity renders. The
    ``recentRequestToken`` is now driven by the unified ``refreshOverview``
    entry (which fuses Overview KPIs + recent activities + live_clock
    from one backend ViewModel sample)."""
    source = read_js("init.js")
    assert "App.recentRequestToken" in source, (
        "init.js must define App.recentRequestToken state"
    )
    body = func_body(source, "refreshOverview")
    assert "recentRequestToken" in body, (
        "refreshOverview must drive recentRequestToken for stale-response discard"
    )


def test_render_session_details_cache_after_guard():
    """``renderSessionDetails`` must set
    ``App.lastSessionDetailsViewModel`` AFTER the dirty-editor / saving
    guard, not before. When the DOM render is skipped, the cache must
    also be skipped so they stay atomic."""
    source = read_js("timeline.js")
    body = func_body(source, "renderSessionDetails")
    # The guard (isEditDirty / activityTimeSaving) must appear BEFORE the
    # cache assignment in the function body.
    guard_pos = body.find("isEditDirty")
    cache_pos = body.find("App.lastSessionDetailsViewModel = data")
    assert guard_pos != -1, (
        "renderSessionDetails must check isEditDirty before caching"
    )
    assert cache_pos != -1, (
        "renderSessionDetails must set App.lastSessionDetailsViewModel"
    )
    assert guard_pos < cache_pos, (
        "renderSessionDetails must set the cache AFTER the dirty-editor guard "
        "so cache/DOM stay atomic"
    )


def test_clear_sessions_invalidates_pending_detail_request():
    """when sessions are cleared (empty list),
    ``detailsRequestToken`` must be incremented so a stale
    ``get_timeline_session_details`` response does not backfill."""
    source = read_js("timeline.js")
    body = func_body(source, "showTimeline")
    # The empty-sessions branch must increment detailsRequestToken.
    empty_pos = body.find("当日暂无活动记录")
    assert empty_pos != -1, "showTimeline must handle empty sessions"
    # After the empty marker, detailsRequestToken must be incremented.
    after_empty = body[empty_pos:]
    assert "detailsRequestToken" in after_empty, (
        "showTimeline must invalidate detailsRequestToken when sessions are empty"
    )


def test_date_switch_invalidates_pending_detail_request():
    """when switching dates (goPrevDay / goNextDay /
    goToday), ``detailsRequestToken`` must be incremented so a stale
    response from the previous date does not backfill."""
    source = read_js("timeline.js")
    reset_body = func_body(source, "resetTimelineReportSelection")
    assert "detailsRequestToken" in reset_body, (
        "resetTimelineReportSelection must invalidate detailsRequestToken"
    )
    assert "lastSessionDetailsViewModel" in reset_body, (
        "resetTimelineReportSelection must clear lastSessionDetailsViewModel"
    )
    for fn_name in ("goPrevDay", "goNextDay", "goToday"):
        body = func_body(source, fn_name)
        assert "loadTimelineReport" in body and "resetSelection: true" in body, (
            fn_name + " must route date switches through loadTimelineReport(resetSelection)"
        )


def test_virtual_session_click_does_not_open_edit_panel():
    """``selectTimelineSession`` must NOT call
    ``populateEditPanel`` for virtual sessions (``edit_disabled`` /
    ``is_virtual``). Instead, it must call ``clearEditPanel``."""
    source = read_js("timeline.js")
    body = func_body(source, "selectTimelineSession")
    assert "edit_disabled" in body or "is_virtual" in body, (
        "selectTimelineSession must check edit_disabled / is_virtual before "
        "opening the edit panel"
    )
    assert "clearEditPanel" in body, (
        "selectTimelineSession must call clearEditPanel for virtual sessions"
    )


def test_init_accepts_refresh_state_before_first_page_refresh_and_heartbeat():
    """``init`` must accept refresh_state before the first page render and
    before starting the heartbeat."""
    source = read_js("init.js")
    # Use "function init(" to distinguish from "function initNav" / "initButtons".
    init_start = source.find("function init(")
    assert init_start != -1, "init.js must define function init()"
    # Find the end of init() — the next function at the same indent level.
    init_end = source.find("\n    App.init = init;", init_start)
    if init_end == -1:
        init_end = source.find("\n    function ", init_start + 1)
    body = source[init_start:init_end] if init_end != -1 else source[init_start:]
    state_pos = body.find("get_refresh_state")
    accept_pos = body.find("acceptRefreshStateRuntime")
    refresh_pos = body.find("refreshCurrentPageData(state")
    heartbeat_pos = body.find("startHeartbeat()")
    assert state_pos != -1, "init must call get_refresh_state"
    assert accept_pos != -1, "init must accept refresh_state"
    assert refresh_pos != -1, "init must call refreshCurrentPageData with state"
    assert heartbeat_pos != -1, "init must call startHeartbeat"
    assert state_pos < accept_pos < refresh_pos < heartbeat_pos
    assert ".then" in body, (
        "init must chain get_refresh_state -> accept -> refresh -> heartbeat"
    )


def test_init_initializes_last_reconcile_after_first_refresh():
    """``lastReconcileAtEpochMs`` must be initialized
    AFTER the first refresh completes, not left at 0. Without this, the
    first heartbeat tick sees ``now - 0 >= RECONCILE_INTERVAL_MS`` and
    immediately triggers low-frequency reconciliation."""
    source = read_js("init.js")
    init_start = source.find("function init(")
    assert init_start != -1, "init.js must define function init()"
    init_end = source.find("\n    App.init = init;", init_start)
    if init_end == -1:
        init_end = source.find("\n    function ", init_start + 1)
    body = source[init_start:init_end] if init_end != -1 else source[init_start:]
    assert "lastReconcileAtEpochMs" in body, (
        "init must initialize lastReconcileAtEpochMs"
    )
    assert "Date.now()" in body, (
        "init must set lastReconcileAtEpochMs to Date.now() after first refresh"
    )


def test_revision_check_skips_reconciliation_on_same_tick():
    """when a revision-change heavy refresh is
    triggered, the low-frequency reconciliation must NOT also be triggered
    on the same tick. The revision check must track whether a heavy refresh
    was triggered and skip reconciliation if so."""
    source = read_js("init.js")
    body = func_body(source, "runRevisionCheck")
    assert "triggeredHeavyRefresh" in body, (
        "runRevisionCheck must track whether a heavy refresh was triggered "
        "on this tick to skip concurrent reconciliation"
    )


def test_reconciliation_skips_when_page_refresh_inflight():
    """low-frequency reconciliation must NOT run when
    ``activePageRefreshInFlight`` is true so it does not concurrently
    re-pull the same data."""
    source = read_js("init.js")
    body = func_body(source, "runRevisionCheck")
    assert "activePageRefreshInFlight" in body, (
        "runRevisionCheck must check activePageRefreshInFlight before "
        "triggering low-frequency reconciliation"
    )


def test_revision_check_uses_live_scope_not_timeline_report_date():
    """``runRevisionCheck`` must fetch live scope only. Timeline report
    dates are loaded by the Timeline report request path, not by
    ``get_refresh_state``."""
    source = read_js("init.js")
    body = func_body(source, "runRevisionCheck")
    assert "get_refresh_state" in body, (
        "runRevisionCheck must call get_refresh_state"
    )
    assert "App.timelineDate" not in body
    assert 'get_refresh_state",' not in body




def _strip_js_comments(src: str) -> str:
    """Remove block comments and line comments so the forbidden-pattern
    scan does not false-positive on documentation that mentions the old
    patterns."""
    import re

    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def test_show_recent_seeds_via_live_continuity_key():
    """Architecture contract: ``showRecent`` must seed the monotonic
    render state via ``App.liveContinuityKey(item, "recent")``. The array
    index (``"recent-" + i``) MUST NOT be used as the seeding key because
    it changes across the virtual → persisted_open transition while
    ``stable_live_key_hash`` stays the same."""
    src = _strip_js_comments(read_js("overview.js"))
    body = func_body(src, "showRecent")
    assert "liveContinuityKey" in body, (
        "showRecent must call App.liveContinuityKey to build the seeding key"
    )
    # The old index-based concatenation must not appear in the code.
    for forbidden in ('"recent-" +', "'recent-' +"):
        assert forbidden not in body, (
            "showRecent must not use " + forbidden + " as a live row key; "
            "use App.liveContinuityKey(item, 'recent') instead"
        )


def test_show_timeline_seeds_via_live_continuity_key():
    """Architecture contract: ``showTimeline`` must seed the monotonic
    render state via ``App.liveContinuityKey(s, "session")``. The session
    id (``"session-" + session_id``) MUST NOT be used as the seeding key."""
    src = _strip_js_comments(read_js("timeline.js"))
    body = func_body(src, "showTimeline")
    assert "liveContinuityKey" in body, (
        "showTimeline must call App.liveContinuityKey to build the seeding key"
    )
    for forbidden in ('"session-" +', "'session-' +"):
        assert forbidden not in body, (
            "showTimeline must not use " + forbidden + " as a live row key; "
            "use App.liveContinuityKey(s, 'session') instead"
        )


def test_render_session_details_seeds_via_live_continuity_key():
    """Architecture contract: ``renderSessionDetails`` must seed the
    monotonic render state via ``App.liveContinuityKey(item, "detail")``.
    The activity id (``"detail-" + activity_id``) MUST NOT be used as the
    seeding key."""
    src = _strip_js_comments(read_js("timeline.js"))
    body = func_body(src, "renderSessionDetails")
    assert "liveContinuityKey" in body, (
        "renderSessionDetails must call App.liveContinuityKey to build the "
        "seeding key"
    )
    for forbidden in ('"detail-" +', "'detail-' +"):
        assert forbidden not in body, (
            "renderSessionDetails must not use " + forbidden + " as a live "
            "row key; use App.liveContinuityKey(item, 'detail') instead"
        )


def test_live_continuity_key_is_single_source_of_truth():
    """Architecture contract: ``liveContinuityKey`` in core.js must be the
    ONLY place that constructs a live-row continuity key. The function
    must use ``stable_live_key_hash`` as the primary anchor so the
    continuity survives the virtual → persisted_open transition."""
    src = _strip_js_comments(read_js("core.js"))
    assert "function liveContinuityKey" in src, (
        "core.js must define function liveContinuityKey"
    )
    body = func_body(src, "liveContinuityKey")
    assert "stable_live_key_hash" in body, (
        "liveContinuityKey must use stable_live_key_hash for continuity"
    )


# Frontend contract tests for the unified live duration math (spec §IV):
# per-row base + accepted runtime elapsed, monotonic key consistency,
# no legacy ``live_projection`` / ``live_display`` propagation.


def test_live_runtime_acceptance_has_refresh_state_and_page_model_sources():
    """refresh_state and full page ViewModels share one runtime accept path."""
    src = _strip_js_comments(read_js("core.js"))
    common_body = func_body(src, "acceptLiveRuntimePayload")
    accept_body = func_body(src, "acceptRefreshStateRuntime")
    page_body = func_body(src, "acceptPagePayloadRuntime")
    assert "App.liveRuntime" in common_body
    assert "rebaseIncomingClockWithoutRollback" in common_body
    assert "liveStateRevision" in common_body
    assert 'source: "refresh_state"' in accept_body
    assert 'source: "page_model"' in page_body
    assert "App.lastRefreshState = payload" in common_body
    assert 'options.source === "refresh_state"' in common_body
    for removed in (
        "commitPageActiveSpanClock",
        "observeRefreshStateActiveSpan",
        "registerLiveClock",
        "activeSpanClockByPage",
    ):
        assert removed not in src


def test_get_active_live_clock_reads_accepted_runtime_only():
    """``getActiveLiveClock`` must read only the accepted runtime and must
    not suppress live ticking for historical Timeline report dates."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "getActiveLiveClock")
    assert "App.liveRuntime" in body
    assert "runtime.liveClock" in body
    assert "currentPage" in body, (
        "getActiveLiveClock must confirm the accepted runtime's page"
    )
    assert "Object.keys" not in body, (
        "getActiveLiveClock must not iterate registry keys"
    )
    assert "runtimeReportDateForPage" not in body
    assert "App.timelineDate" not in body


def test_ticker_reads_dom_continuity_key_for_monotonic_guard():
    """The ticker must read the continuity key from the DOM's
    ``data-live-continuity-key`` attribute so the render seed and the
    ticker share the SAME monotonic guard key. Spec §IV.4: render seed
    and ticker must use the same continuity key; mismatched keys (e.g.
    ``recent:live:<hash>`` for render vs ``span:<spanId>`` for ticker)
    break the monotonic guard."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "renderLiveDurationTarget")
    assert "data-live-continuity-key" in body, (
        "renderLiveDurationTarget must read data-live-continuity-key from each live "
        "DOM node so the ticker uses the SAME key the renderer seeded"
    )


def test_apply_local_ticker_renders_node_base_plus_delta_for_dom_rows():
    """Spec §IV.1.1: live rows render from DOM display base + active elapsed
    using the one current page active live time."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    # Must read the per-node base from the DOM.
    assert "data-display-base-seconds" in body, (
        "applyLocalTicker must read data-display-base-seconds from each live "
        "duration target"
    )
    assert "data-active-elapsed-at-render" not in body, (
        "applyLocalTicker must not read each node's active elapsed offset"
    )
    assert "liveClockBySpanId[spanId]" not in body, (
        "applyLocalTicker must not resolve row-owned clocks by span id"
    )
    assert "renderLiveDurationTarget" in body, (
        "applyLocalTicker must delegate row projection to renderLiveDurationTarget"
    )


def test_show_timeline_suppresses_timeline_total_target_on_historical_date():
    """Historical Timeline payloads must not seed a live duration target for
    ``#timeline-total``; the generic ticker only updates targets that renderers
    explicitly mark."""
    src = _strip_js_comments(read_js("timeline.js"))
    body = func_body(src, "showTimeline")
    assert "isTodayForTotal" in body
    assert "clearLiveProjectionAnchor" in body
    assert "timeline-total" in body


def test_frontend_js_does_not_read_live_projection_or_live_display():
    """Spec §IV.2 / §VI: the frontend JS bundle must NOT read or
    propagate ``live_projection`` or ``live_display`` as compatibility
    aliases. These legacy fields have been removed from the backend;
    the frontend must use ``current_activity`` / ``live_clock`` /
    ``activity_display_model`` / ``display_span_id`` / ``sample_id``
    only."""
    all_js = read_all_js()
    # Strip comments so documentation mentions don't false-positive.
    all_js_stripped = _strip_js_comments(all_js)
    assert "live_projection" not in all_js_stripped, (
        "frontend JS must not read or propagate live_projection; the legacy "
        "alias has been removed from the backend"
    )
    # ``live_display`` is allowed ONLY in the historical CSS class name
    # ``live-display`` and the registry helper ``clearLiveClockRegistry``
    # is fine. But as a payload KEY (``.live_display`` / ``["live_display"]``)
    # it must not appear. Check for the dotted/bracketed access pattern.
    assert ".live_display" not in all_js_stripped, (
        "frontend JS must not access payload.live_display; the legacy alias "
        "has been removed from the backend"
    )
    assert '["live_display"]' not in all_js_stripped, (
        "frontend JS must not access payload['live_display']; the legacy "
        "alias has been removed from the backend"
    )


def test_init_refresh_overview_does_not_propagate_live_projection_or_live_display():
    """Spec §IV.2.1: ``refreshOverview`` must NOT propagate
    ``bundle.live_projection`` or ``bundle.live_display`` into the
    ``showOverview`` / ``showRecent`` payloads. Only ``current_activity``
    / ``live_clock`` / ``activity_display_model`` / ``display_span_id``
    / ``sample_id`` may be propagated."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "refreshOverview")
    assert "live_projection" not in body, (
        "refreshOverview must not propagate bundle.live_projection"
    )
    assert "live_display" not in body, (
        "refreshOverview must not propagate bundle.live_display"
    )
    # Must propagate the new fields.
    assert "current_activity" in body, (
        "refreshOverview must propagate current_activity"
    )
    assert "live_clock" in body, (
        "refreshOverview must propagate live_clock"
    )


def test_apply_local_ticker_records_missing_node_clock_contract_violation():
    """When the accepted live runtime clock is missing, ``applyLocalTicker`` must
    record diagnostics instead of silently hiding the contract break."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    assert "getActiveLiveClock" in body, (
        "applyLocalTicker must obtain the clock via getActiveLiveClock"
    )
    assert "App.liveClockBySpanId[spanId] || clock" not in body, (
        "applyLocalTicker must not fall back from a missing row clock to another clock"
    )
    assert "if (!nodeClock) continue" not in body, (
        "applyLocalTicker must not silently continue when a row clock is missing"
    )
    assert "recordLiveClockContractViolation" in body, (
        "applyLocalTicker must record diagnostics for a missing accepted clock"
    )
    assert "missing_active_span_clock" in body, (
        "missing active span clock diagnostics must use a display-safe reason"
    )


def test_live_clock_contract_violation_refresh_is_consumed_outside_ticker():
    core = _strip_js_comments(read_js("core.js"))
    ticker_body = func_body(core, "applyLocalTicker")
    assert "callBridge" not in ticker_body, (
        "applyLocalTicker must stay bridge-free even when reporting diagnostics"
    )
    init = _strip_js_comments(read_js("init.js"))
    revision_body = func_body(init, "runRevisionCheck")
    assert "liveClockContractRefreshRequested" in revision_body, (
        "runRevisionCheck must consume live clock diagnostics"
    )
    assert "refreshCurrentPageData" in revision_body, (
        "runRevisionCheck must trigger a controlled page refresh for diagnostics"
    )


def test_renderers_diagnose_live_rows_missing_span_id():
    overview_body = func_body(_strip_js_comments(read_js("overview.js")), "showRecent")
    timeline_src = _strip_js_comments(read_js("timeline.js"))
    timeline_body = func_body(timeline_src, "showTimeline")
    details_body = func_body(timeline_src, "renderSessionDetails")

    assert "recent_live_row_missing_span_id" in overview_body
    assert "session_live_row_missing_span_id" in timeline_body
    assert "summary_live_row_missing_span_id" in details_body
    for body in (overview_body, timeline_body, details_body):
        assert "recordLiveClockContractViolation" in body, (
            "live row renderers must diagnose missing display_span_id"
        )


def test_frontend_status_display_uses_display_contract_helper():
    core = _strip_js_comments(read_js("core.js"))
    overview_body = func_body(_strip_js_comments(read_js("overview.js")), "showRecent")
    correction_body = func_body(
        _strip_js_comments(read_js("timeline_correction.js")),
        "renderCorrectionShell",
    )

    helper_body = func_body(core, "displayStatusText")
    assert "display_status" in helper_body
    assert "status_label" in helper_body
    assert "status_summary" in helper_body
    for raw in ("idle", "paused", "excluded", "error", "normal"):
        assert raw not in helper_body
    for label in ("空闲", "已暂停", "已排除", "异常", "正常"):
        assert label not in helper_body

    assert "App.displayStatusText(item)" in overview_body
    assert "item.status ||" not in overview_body
    assert "App.displayStatusText(session)" in correction_body
    assert "session.status" not in correction_body


def test_status_only_recent_rows_never_register_live_targets():
    overview_body = func_body(_strip_js_comments(read_js("overview.js")), "showRecent")

    assert 'item.row_kind === "status_only"' in overview_body
    assert "var canTick = !isStatusOnly" in overview_body
    assert "item.live_delta_eligible === true" in overview_body
    assert "!!item.display_span_id" in overview_body
    assert 'if (canTick) cls += " live-projected"' in overview_body
    assert "var spanId = canTick ?" in overview_body
    assert 'data-live-duration-target="1"' in overview_body
    assert 'recent_live_row_missing_span_id' in overview_body


def test_current_activity_live_target_requires_current_live_contract():
    current_body = func_body(_strip_js_comments(read_js("core.js")), "renderCurrentActivityElement")

    assert "var canTickCurrent = current.current_duration_live === true" in current_body
    assert "&& !!displaySpanId" in current_body
    assert "&& !!currentActivityDisplaySpanId" in current_body
    assert "&& !!currentResourceIdentityHash" in current_body
    assert "App.computeActiveElapsedNow(clock, Date.now())" in current_body
    assert "canTickCurrent ? ' data-live-duration-target=\"1\"'" in current_body
    assert "canTickCurrent ? ' data-duration-semantic=\"current-live\"'" in current_body
    assert "data-display-base-seconds=\"0\"" in current_body
    assert "data-live-base-seconds=\"0\"" in current_body


def test_full_reconcile_reuses_current_page_refresh_state_path():
    body = func_body(_strip_js_comments(read_js("init.js")), "fullReconcileCollectionViews")

    assert "refreshCurrentPageData(null" in body
    assert "refreshOverview(" not in body
    assert "refreshTimeline(" not in body
    assert "finally" in body


# ---------------------------------------------------------------------------
# Accepted runtime sample contract (Section 33.9)
# ---------------------------------------------------------------------------


def test_accept_refresh_state_runtime_uses_rebase():
    """The accepted runtime rebases same-continuity refresh_state clocks
    through the shared runtime accept path."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "acceptLiveRuntimePayload")
    assert "rebaseIncomingClockWithoutRollback" in body
    assert "sameLiveContinuity" in body
    assert "App.liveRuntime" in body


def test_runtime_rebases_same_continuity_without_live_state_gate():
    """Same continuity is determined by display span or stable hash. A
    live-state transition must not force a visual reset."""
    src = _strip_js_comments(read_js("core.js"))
    accept_body = func_body(src, "acceptLiveRuntimePayload")
    continuity_body = func_body(src, "sameLiveContinuity")
    assert "display_span_id" in continuity_body, (
        "sameLiveContinuity must treat matching display_span_id as continuous"
    )
    assert "stable_live_key_hash" in continuity_body, (
        "sameLiveContinuity must treat matching stable_live_key_hash as continuous"
    )
    assert "live_state" not in continuity_body, (
        "sameLiveContinuity must not use live_state as a negative continuity condition"
    )
    assert "sameLiveContinuity" in accept_body and "rebaseIncomingClockWithoutRollback" in accept_body
    rebase_body = func_body(src, "rebaseIncomingClockWithoutRollback")
    for field in (
        "live_started_at_epoch_ms",
        "carry_seconds",
        "duration_seconds_at_sample",
    ):
        assert field in rebase_body, (
            "rebaseIncomingClockWithoutRollback must be able to adjust " + field
        )


def test_runtime_visual_continuity_key_excludes_structural_revisions():
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "runtimeVisualContinuityKey")
    for required in (
        "page",
        "displaySpanId",
        "stableLiveKeyHash",
        "currentActivityDisplaySpanId",
        "currentResourceIdentityHash",
    ):
        assert required in body
    for forbidden in (
        "liveStateRevision",
        "refreshRevision",
        "pageStructureRevision",
        "reportDate",
        "is_persisted",
        "persisted_id",
    ):
        assert forbidden not in body


def test_accept_runtime_keeps_monotonic_state_when_only_live_state_revision_changes():
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "acceptLiveRuntimePayload")
    reset_pos = body.find("App._monotonicRenderState = {}")
    key_pos = body.find("runtimeVisualContinuityKey")
    assert reset_pos != -1
    assert key_pos != -1 and key_pos < reset_pos
    assert "previousKey !== runtimeVisualContinuityKey(App.liveRuntime)" in body


def test_virtual_to_persisted_same_visual_identity_keeps_no_rollback_guard():
    src = _strip_js_comments(read_js("core.js"))
    key_body = func_body(src, "runtimeVisualContinuityKey")
    render_body = func_body(src, "renderDurationProjected")
    assert "stableLiveKeyHash" in key_body
    assert "displaySpanId" in key_body
    assert "liveStateRevision" not in key_body
    assert "next < entry.lastSeconds" in render_body
    assert "next = entry.lastSeconds" in render_body


def test_run_revision_check_accepts_refresh_state_without_row_clock_commit():
    """Every revision check accepts refresh_state runtime and must not call
    old compatibility clock paths or rewrite row projection anchors."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    fast_body = func_body(src, "refreshCurrentActivityFromState")
    assert "acceptRefreshStateRuntime(state)" in body
    assert "registerLiveClock" not in body, (
        "runRevisionCheck must not use registerLiveClock for refresh_state"
    )
    assert "commitPageActiveSpanClock" not in fast_body
    assert "preserveSameSpanSample" not in body, (
        "runRevisionCheck must not use legacy source-specific preservation flags"
    )


def test_page_model_runtime_acceptance_is_full_payload_plus_details_runtime():
    """Full page payloads and Timeline Details accept backend runtime before render."""
    core = _strip_js_comments(read_js("core.js"))
    page_body = func_body(core, "acceptPagePayloadRuntime")
    assert "acceptLiveRuntimePayload" in page_body
    for fname in ("overview.js", "timeline.js"):
        src = _strip_js_comments(read_js(fname))
        assert "commitPageActiveSpanClock" not in src
        assert "registerLiveClock" not in src
    details_body = func_body(_strip_js_comments(read_js("timeline.js")), "renderSessionDetails")
    details_accept_body = func_body(_strip_js_comments(read_js("timeline.js")), "acceptTimelineDetailsPayload")
    assert "commitPageActiveSpanClock" not in details_body, (
        "renderSessionDetails partial payload must not replace the accepted live runtime"
    )
    assert "acceptLiveRuntimePayload" in details_accept_body
    assert 'source: "details_model"' in details_accept_body


def test_run_revision_check_does_not_register_current_clock_on_revision_change():
    """Revision changes must fast-render current activity from refresh_state.

    Heavy page refreshes still backfill KPI/recent/timeline rows, but the
    current activity card/header must not wait for them.
    """
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    assert "revision" in body.lower(), (
        "runRevisionCheck must compare refresh_revision"
    )
    assert "registerCurrentActivityClock" not in body, (
        "runRevisionCheck must not register current_activity_clock from refresh_state"
    )
    assert "patchCurrentActivityFromRefreshState" not in body, (
        "runRevisionCheck must not patch current activity duration from refresh_state"
    )
    accept_index = body.find("acceptRefreshStateRuntime(state")
    fast_index = body.find("refreshCurrentActivityFromState(state", accept_index)
    status_index = body.find("refreshStatusFromRefreshState(state)", accept_index)
    assert fast_index != -1, (
        "runRevisionCheck must fast-render current activity from refresh_state"
    )
    assert status_index != -1 and fast_index < status_index, (
        "current activity fast-render must happen before status/heavy refresh work"
    )
    changed_index = body.find("pageStructureChanged")
    refresh_index = body.find("refreshCurrentPageData(state", changed_index)
    assert refresh_index != -1, (
        "page-structure changed branch must trigger heavy refresh with the "
        "existing refresh_state payload"
    )


def test_run_revision_check_updates_current_cache_when_revision_unchanged():
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    fast_body = func_body(src, "refreshCurrentActivityFromState")

    accept_index = body.find("acceptRefreshStateRuntime(state")
    fast_index = body.find("refreshCurrentActivityFromState(state", accept_index)
    heavy_index = body.find("refreshCurrentPageData(state", accept_index)
    assert fast_index != -1
    assert heavy_index == -1 or fast_index < heavy_index, (
        "current fast path must not depend on heavy refresh"
    )
    assert "updateCurrentActivityCacheFromRefreshState(state)" in fast_body
    assert "if (options.forceRender !== true) return" in fast_body
    assert "forceRender: renderCurrentActivity" in body
    assert "currentActivityIdentityChanged" in body


def test_refresh_current_activity_from_state_supports_overview_and_timeline():
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "refreshCurrentActivityFromState")
    cache_body = func_body(src, "updateCurrentActivityCacheFromRefreshState")

    assert 'App.currentPage === "overview"' in body
    assert 'document.getElementById("current-activity")' in body
    assert "App.lastOverviewSnapshot.current_activity" in cache_body
    assert 'App.currentPage === "timeline"' in body
    assert 'document.getElementById("timeline-current")' in body
    assert "App.lastTimelineData.current_activity" in cache_body
    assert "updateCurrentActivityCacheFromRefreshState(state)" in body
    assert "commitPageActiveSpanClock" not in body
    assert "App.applyLocalTicker()" not in body
    assert "options.forceRender" in body
    assert "_timelineEditingActive" not in body, (
        "Timeline editing may protect list/detail inputs, not the current header"
    )


def test_revision_change_auto_refresh_reuses_refresh_state_payload():
    src = _strip_js_comments(read_js("init.js"))
    refresh_body = func_body(src, "refreshCurrentPageData")
    revision_body = func_body(src, "runRevisionCheck")

    assert "function refreshCurrentPageData(state, options)" in refresh_body
    assert "refreshStatusFromRefreshState(acceptedState)" in refresh_body
    assert "refreshStatus()" in refresh_body
    assert "refreshCurrentPageData(state" in revision_body


def test_frontend_does_not_locally_promote_thirty_second_history_state():
    src = _strip_js_comments(read_all_js())

    forbidden_patterns = [
        r"elapsed\s*>=\s*30",
        r"elapsedSeconds\s*>=\s*30",
        r"durationSeconds\s*>=\s*30",
        r"已进入历史",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, src), (
            "frontend must not locally infer the 30s persisted/history label"
        )


def test_fast_path_requires_accepted_runtime_before_render():
    core = _strip_js_comments(read_js("core.js"))
    init = _strip_js_comments(read_js("init.js"))
    accept_body = func_body(core, "acceptRefreshStateRuntime")
    common_body = func_body(core, "acceptLiveRuntimePayload")
    fast_body = func_body(init, "refreshCurrentActivityFromState")

    assert "App.liveRuntime" in common_body
    assert "rebaseIncomingClockWithoutRollback" in common_body
    assert "acceptLiveRuntimePayload" in accept_body
    assert "App.liveRuntime.refreshRevision" in fast_body
    assert "App.currentPage" in fast_body


# ---------------------------------------------------------------------------
# Accepted live runtime (Section 五)
# ---------------------------------------------------------------------------


def test_refresh_state_runtime_acceptor_records_page_scope_and_revisions():
    """Section 五: accepted runtime records page/date and backend revisions."""
    src = _strip_js_comments(read_js("core.js"))
    refresh_body = func_body(src, "acceptRefreshStateRuntime")
    body = func_body(src, "acceptLiveRuntimePayload")
    assert "App.currentPage" in refresh_body
    assert "reportDate" in refresh_body
    assert "refreshRevision" in body
    assert "liveStateRevision" in body
    assert "pageStructureRevision" in body


def test_current_activity_clock_registry_is_removed():
    src = _strip_js_comments(read_js("core.js"))
    helper_body = func_body(src, "findClockInPayload")
    assert "currentActivityClockByPage" not in src
    assert "registerCurrentActivityClock" not in src
    assert "getActiveCurrentActivityClock" not in src
    assert "current_activity_clock" not in helper_body
    assert "payload.live_clock" in helper_body
    assert "activity_display_model.live_clock" in helper_body


def test_no_current_activity_clock_rebase_path_remains():
    src = _strip_js_comments(read_js("core.js"))
    assert "sameCurrentContinuity" not in src
    assert "registerCurrentActivityClock" not in src
    assert "currentActivityContinuityKey" in src


def test_active_live_time_does_not_require_project_duration_flag():
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "isActiveLiveTime")
    assert "is_live" in body
    assert "project_duration_live" not in body, (
        "active live time registration must not require project-duration eligibility"
    )


def test_current_activity_continuity_uses_current_resource_identity():
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "currentActivityContinuityKey")
    assert "current_resource_identity_hash" in body
    assert "current_activity_display_span_id" in body
    assert "start_time" in body
    assert "stable_live_key_hash" in body


def test_render_current_activity_no_rollback_is_key_scoped():
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "renderCurrentActivityElement")
    assert "data-current-continuity-key" in body
    assert "previousContinuity !== continuity" in body
    assert "resetMonotonicRenderState(previousContinuity)" in body
    assert "App._monotonicRenderState[continuity]" in body


def test_apply_local_ticker_current_activity_does_not_fallback_to_project_clock():
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    assert "getActiveCurrentActivityClock" not in body
    assert "currentActivityClock" not in body
    assert "computeActiveElapsedNow" in body


def test_renderers_do_not_write_project_or_current_runtime():
    overview = _strip_js_comments(read_js("overview.js"))
    timeline = _strip_js_comments(read_js("timeline.js"))
    for src, name in ((overview, "overview.js"), (timeline, "timeline.js")):
        assert "commitPageActiveSpanClock" not in src
        assert "registerLiveClock" not in src
        assert "registerCurrentActivityClock" not in src, name + " must not register current activity clock"


def test_timeline_details_edit_guard_keeps_dom_and_does_not_register_clocks():
    src = _strip_js_comments(read_js("timeline.js"))
    body = func_body(src, "renderSessionDetails")
    reg_pos = body.find("registerCurrentActivityClock")
    guard_pos = body.find("_timelineEditingActive")
    render_pos = body.find("detailsList.innerHTML")
    assert reg_pos == -1 and guard_pos != -1
    assert guard_pos < render_pos, "Details edit guard must run before DOM redraw"
    assert "commitPageActiveSpanClock" not in body, (
        "Details partial render must not replace the accepted live runtime"
    )


def test_get_active_live_clock_reads_runtime_scope():
    """Section 五: ``getActiveLiveClock`` MUST read the accepted runtime and
    verify it still matches the current page."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "getActiveLiveClock")
    assert "currentPage" in body, (
        "getActiveLiveClock must read App.currentPage to scope the lookup"
    )
    assert "App.liveRuntime" in body
    assert "runtime.liveClock" in body
    assert "activeDisplaySpanId" not in body, (
        "getActiveLiveClock must NOT fall back to App.activeDisplaySpanId; "
        "accepted runtime is the single source of truth"
    )


def test_full_reconcile_does_not_unconditionally_call_refresh_overview():
    """Section 五: ``fullReconcileCollectionViews`` MUST NOT unconditionally
    call ``refreshOverview()``. When the current page is NOT Overview
    (e.g. Timeline historical date), the reconcile must only refresh
    status + the current page so a hidden Overview refresh does not
    overwrite the accepted runtime.
    """
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "fullReconcileCollectionViews")
    assert "refreshCurrentPageData" in body
    assert "refreshOverview(" not in body
    assert "refreshTimeline(" not in body
    refresh_body = func_body(src, "refreshCurrentPageData")
    assert 'currentPage === "overview"' in refresh_body, (
        "refreshCurrentPageData must gate refreshOverview on the current page "
        "so a hidden Overview refresh does not overwrite the accepted runtime"
    )


def test_overview_js_uses_runtime_gate_not_runtime_write():
    """Section 五: Overview page payloads are accepted before render."""
    src = _strip_js_comments(read_js("overview.js"))
    init = _strip_js_comments(read_js("init.js"))
    assert "commitPageActiveSpanClock" not in src
    assert 'acceptPagePayloadRuntime(bundle, "overview"' in init


def test_timeline_js_uses_runtime_gate_not_runtime_write():
    """Section 五: Timeline page payloads are accepted before render."""
    src = _strip_js_comments(read_js("timeline.js"))
    assert "commitPageActiveSpanClock" not in src
    assert "acceptTimelinePayload" in src
    body = func_body(src, "acceptTimelinePayload")
    assert 'String(App.currentPage || "overview") !== "timeline"' in body
    assert 'App.runtimeReportDateForPage("timeline", date)' in body
    assert "App.isPagePayloadCompatibleWithRuntime" in body
    assert "App.noteRejectedPagePayload" in body
    assert "return true" in body


def test_init_refresh_overview_gates_with_runtime():
    """Section 五: ``refreshOverview`` in ``init.js`` accepts page runtime."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "refreshOverview")
    assert 'acceptPagePayloadRuntime(bundle, "overview", bundle.date)' in body


def test_run_revision_check_refreshes_on_live_state_revision_change_without_page_structure_change():
    """A live-state transition is structural for live rows even when the
    page-structure revision string is unchanged."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    live_pos = body.find("liveStateChanged")
    page_pos = body.find("pageStructureChanged")
    refresh_pos = body.find("refreshCurrentPageData(state")
    assert live_pos != -1, "runRevisionCheck must compute liveStateChanged"
    assert page_pos != -1, "runRevisionCheck must still compute pageStructureChanged"
    assert refresh_pos != -1, "runRevisionCheck must trigger a heavy refresh"
    condition = body[body.rfind("if", 0, refresh_pos):refresh_pos]
    assert "liveStateChanged" in condition
    assert "pageStructureChanged" in condition
    assert "liveClockContractRefreshRequested" in condition


def test_refresh_overview_accepts_page_payload_runtime_before_render():
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "refreshOverview")
    accept_pos = body.find('acceptPagePayloadRuntime(bundle, "overview", bundle.date)')
    overview_pos = body.find("App.showOverview", accept_pos)
    recent_pos = body.find("App.showRecent", accept_pos)
    assert accept_pos != -1
    assert overview_pos != -1 and accept_pos < overview_pos
    assert recent_pos != -1 and accept_pos < recent_pos


def test_refresh_timeline_accepts_page_payload_runtime_before_render():
    timeline = _strip_js_comments(read_js("timeline.js"))
    accept_body = func_body(timeline, "acceptTimelinePayload")
    load_body = func_body(timeline, "timelineReportRequest")
    details_body = func_body(timeline, "acceptTimelineDetailsPayload")
    assert "acceptPagePayloadRuntime" not in accept_body
    assert 'App.runtimeReportDateForPage("timeline", date)' in accept_body
    assert "App.acceptLiveRuntimePayload" in accept_body
    assert "return true" in accept_body
    accept_pos = load_body.find("acceptTimelinePayload(data, date)")
    show_pos = load_body.find("showTimeline(data)", accept_pos)
    assert accept_pos != -1 and show_pos != -1 and accept_pos < show_pos
    assert "acceptPagePayloadRuntime" not in details_body
    assert "acceptLiveRuntimePayload" in details_body


def test_details_payload_accepts_runtime_before_render():
    timeline = _strip_js_comments(read_js("timeline.js"))
    load_body = func_body(timeline, "loadSessionDetails")
    accept_body = func_body(timeline, "acceptTimelineDetailsPayload")
    render_pos = load_body.find("renderSessionDetails(data)")
    accept_pos = load_body.find("acceptTimelineDetailsPayload(data, date)")
    assert "isPagePayloadCompatibleWithRuntime" in accept_body
    assert "acceptLiveRuntimePayload" in accept_body
    assert 'source: "details_model"' in accept_body
    assert "return true" in accept_body
    assert accept_pos != -1 and render_pos != -1 and accept_pos < render_pos


def test_overview_kpi_live_targets_are_backend_owned_static_contract():
    overview = _strip_js_comments(read_js("overview.js"))
    show_body = func_body(overview, "showOverview")
    assert "kpi_live_targets" in overview
    assert "currentIsUncategorized" not in overview
    assert "current.is_classified" not in show_body
    assert "current.is_uncategorized" not in show_body
    assert "target.enabled" in overview


def test_hidden_or_stale_page_payload_cannot_overwrite_runtime():
    core = _strip_js_comments(read_js("core.js"))
    gate_body = func_body(core, "isPagePayloadCompatibleWithRuntime")
    assert "payload.ok" in gate_body
    assert 'expectedPage !== String(App.currentPage || "overview")' in gate_body
    assert 'expectedPage === "timeline"' in gate_body
    assert "runtimeReportDateForPage" in gate_body
    assert "App.localTodayStr()" in gate_body
    assert "sameLiveContinuity(currentClock, incomingClock)" in gate_body
    assert "currentActivity.active === true" in gate_body
    assert "currentActivityDisplaySpanId" in gate_body
    assert "currentResourceIdentityHash" in gate_body
    init_body = func_body(_strip_js_comments(read_js("init.js")), "refreshOverview")
    timeline_body = func_body(_strip_js_comments(read_js("timeline.js")), "timelineReportRequest")
    assert "token !== App.overviewRequestToken" in init_body
    assert "token !== App.timelineRequestToken" in timeline_body


def test_run_revision_check_accepts_live_scope_runtime():
    """Section 五: ``runRevisionCheck`` accepts the live-scope refresh_state
    payload without passing Timeline report dates."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    assert "acceptRefreshStateRuntime(state)" in body
    assert "App.timelineDate" not in body


def test_page_switch_clears_runtime_scope_immediately():
    """Section 五: page switches may update scope metadata but must not
    clear the accepted live clock."""
    src = _strip_js_comments(read_js("core.js"))
    switch_body = func_body(_strip_js_comments(read_js("init.js")), "switchPage")
    body = func_body(src, "setLiveRuntimeScope")
    assert "existing.liveClock" in body
    assert "App._monotonicRenderState = {}" not in body
    assert "App.setLiveRuntimeScope" in switch_body


# ---------------------------------------------------------------------------
# Accepted runtime + scoped ticker DOM walk hardening.
# ---------------------------------------------------------------------------


def test_get_active_live_clock_reads_accepted_runtime_only_again():
    """``getActiveLiveClock`` MUST read ``App.liveRuntime`` and MUST NOT
    read legacy clock mirrors."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "getActiveLiveClock")
    assert "App.liveRuntime" in body
    assert "App.currentPage" in body, (
        "getActiveLiveClock must read App.currentPage to confirm runtime scope"
    )
    assert "App.activeDisplaySpanId" not in body, (
        "getActiveLiveClock must NOT read App.activeDisplaySpanId; the "
        "legacy global fallback was removed"
    )
    assert "liveClockBySpanId" not in body


def test_legacy_live_clock_mirrors_are_removed():
    src = _strip_js_comments(read_js("core.js"))
    for removed in (
        "liveClockBySpanId",
        "liveClockByPage",
        "activeLiveTimeByPage",
        "activeDisplaySpanIdByPage",
        "activeDisplaySpanId",
        "mirrorActiveSpanClockForCompatibility",
    ):
        assert removed not in src, (
            "core.js must not retain legacy live-clock mirror: " + removed
        )


def test_frontend_does_not_locally_decide_history_threshold():
    src = _strip_js_comments(read_all_js())
    forbidden_patterns = (
        r"elapsed\s*>?=\s*30",
        r"30\s*<=\s*elapsed",
        r"已进入历史",
        r"暂不入历史",
        r"thresholdWatcher",
        r"persistWatcher",
        r"rowClockRegistry",
    )
    for pattern in forbidden_patterns:
        assert re.search(pattern, src) is None, (
            "frontend must not locally decide persisted/history state: " + pattern
        )


def test_apply_local_ticker_does_not_use_global_live_node_query():
    """``applyLocalTicker`` MUST NOT use
    ``document.querySelectorAll("[data-live-duration-target...]")`` as a global
    live-row query. The ticker must scope the DOM walk to the current
    page container (``#page-<currentPage>``) so a hidden page's stale
    live DOM is never updated with the current page's delta.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    assert 'document.querySelectorAll("[data-live-duration-target' not in body, (
        "applyLocalTicker must NOT use a global "
        'document.querySelectorAll("[data-live-duration-target...]") query; scope '
        "the walk to the current page container"
    )


def test_apply_local_ticker_uses_page_container_for_live_nodes():
    """``applyLocalTicker`` MUST scope the live-node walk to the current
    page container: ``document.getElementById("page-" + page)`` followed
    by ``pageRoot.querySelectorAll("[data-live-duration-target...]")``. This
    prevents a hidden page's live DOM from being updated with the
    current page's live delta.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    assert 'getElementById("page-"' in body, (
        "applyLocalTicker must resolve the current page container via "
        'document.getElementById("page-" + page)'
    )
    assert "pageRoot.querySelectorAll" in body, (
        "applyLocalTicker must call pageRoot.querySelectorAll(...) on the "
        "page container so only the current page's live nodes are visited"
    )
    assert 'data-live-duration-target' in body, (
        "applyLocalTicker must use the data-live-duration-target selector "
        "but scoped to pageRoot"
    )
    # Must derive the page scope from App.currentPage so a hidden page's
    # DOM is never walked.
    assert "App.currentPage" in body, (
        "applyLocalTicker must derive the page scope from App.currentPage"
    )
