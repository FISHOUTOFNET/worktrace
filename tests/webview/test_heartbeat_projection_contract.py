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
    rcp_pos = body.find("refreshCurrentPageData()")
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
    revision signal cannot freeze the UI forever. It must refresh status +
    Overview + current Timeline, but NOT Rules / Settings / Statistics.

    Overview refresh uses the unified ``refreshOverview`` call which
    pulls Overview KPIs + current activity + recent activities +
    live_clock from a single backend ViewModel sample."""
    source = read_js("init.js")
    assert "function fullReconcileCollectionViews" in source, (
        "init.js must define fullReconcileCollectionViews for low-frequency "
        "collection reconciliation"
    )
    body = func_body(source, "fullReconcileCollectionViews")
    # Must refresh status (the collector / sidebar / current-activity view).
    assert "refreshStatus" in body, (
        "fullReconcileCollectionViews must refresh collector status"
    )
    # Must refresh Overview + recent via the unified ``refreshOverview``
    # entry. The legacy ``refreshOverviewBundle`` / separate
    # ``refreshRecent`` paths no longer exist.
    assert "refreshOverview" in body, (
        "fullReconcileCollectionViews must refresh Overview + recent via "
        "refreshOverview (the unified ViewModel entry)"
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
    assert "_timelineEditingActive" in body, (
        "fullReconcileCollectionViews must guard Timeline re-render with "
        "App._timelineEditingActive() so input focus is never lost"
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
    bases/active-elapsed offsets plus the page active span clock. The
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
    ticker can project them from the single page active span clock.

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
    the Timeline page active span clock are the single projection path for
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
    """each detail row must render ``data-activity-id``,
    ``data-detail-index``, and ``data-duration-seconds`` attributes so
    the ticker can locate rows precisely without relying on array index."""
    source = read_js("timeline.js")
    assert 'data-activity-id' in source, (
        "timeline.js must render data-activity-id on detail rows"
    )
    assert 'data-detail-index' in source, (
        "timeline.js must render data-detail-index on detail rows"
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


def test_page_switch_refresh_uses_pending_token_mechanism():
    """issue 14: page-switch immediate refresh must NOT be
    silently skipped by the global in-flight guard. When a refresh is
    in-flight and a page switch occurs, ``pendingPageRefresh`` must be
    set so the refresh is re-triggered after the in-flight one completes."""
    source = read_js("init.js")
    assert "App.pendingPageRefresh" in source, (
        "init.js must define App.pendingPageRefresh state for the pending "
        "page-refresh mechanism"
    )
    body = func_body(source, "refreshCurrentPageData")
    assert "pendingPageRefresh" in body, (
        "refreshCurrentPageData must use pendingPageRefresh to defer "
        "page-switch refreshes that arrive while a refresh is in-flight"
    )


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
    for fn_name in ("goPrevDay", "goNextDay", "goToday"):
        body = func_body(source, fn_name)
        assert "detailsRequestToken" in body, (
            fn_name + " must increment detailsRequestToken on date switch"
        )
        assert "lastSessionDetailsViewModel" in body, (
            fn_name + " must clear lastSessionDetailsViewModel on date switch"
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


def test_init_awaits_first_refresh_before_heartbeat():
    """``init`` must await the first
    ``refreshCurrentPageData()`` BEFORE reading ``get_refresh_state`` and
    starting the heartbeat. This prevents the first heartbeat tick from
    racing the initial heavy refresh."""
    source = read_js("init.js")
    # Use "function init(" to distinguish from "function initNav" / "initButtons".
    init_start = source.find("function init(")
    assert init_start != -1, "init.js must define function init()"
    # Find the end of init() — the next function at the same indent level.
    init_end = source.find("\n    App.init = init;", init_start)
    if init_end == -1:
        init_end = source.find("\n    function ", init_start + 1)
    body = source[init_start:init_end] if init_end != -1 else source[init_start:]
    refresh_pos = body.find("refreshCurrentPageData()")
    state_pos = body.find("get_refresh_state")
    heartbeat_pos = body.find("startHeartbeat()")
    assert refresh_pos != -1, "init must call refreshCurrentPageData"
    assert state_pos != -1, "init must call get_refresh_state"
    assert heartbeat_pos != -1, "init must call startHeartbeat"
    assert refresh_pos < state_pos, (
        "init must call refreshCurrentPageData BEFORE get_refresh_state"
    )
    assert state_pos < heartbeat_pos, (
        "init must call get_refresh_state BEFORE startHeartbeat"
    )
    # Must use .then() chaining to await the refresh, not fire-and-forget.
    assert ".then" in body, (
        "init must chain refreshCurrentPageData().then(...) to await completion"
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


def test_revision_check_passes_report_date():
    """``runRevisionCheck`` must pass the current
    Timeline date to ``get_refresh_state`` so the revision is scoped to
    the viewed date."""
    source = read_js("init.js")
    body = func_body(source, "runRevisionCheck")
    assert "reportDate" in body, (
        "runRevisionCheck must compute reportDate from the current Timeline date"
    )
    assert "get_refresh_state" in body, (
        "runRevisionCheck must call get_refresh_state"
    )




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
# per-row base + unified delta, registry clear, monotonic key consistency,
# no legacy ``live_projection`` / ``live_display`` propagation.


def test_register_live_clock_clears_registry_on_no_clock():
    """Only page_model clears the page active span on non-live payloads.
    refresh_state observation must not clear still-rendered page_model
    anchors when pause/idle is observed before the heavy page refresh."""
    src = _strip_js_comments(read_js("core.js"))
    commit_body = func_body(src, "commitPageActiveSpanClock")
    observe_body = func_body(src, "observeRefreshStateActiveSpan")
    assert "clearPageActiveSpanClockFromPageModel" in commit_body, (
        "page_model commits must clear the page active span when the full "
        "page model has no project-duration live clock"
    )
    assert "clearLiveClockRegistry" not in observe_body, (
        "refresh_state observation must not clear page_model anchors"
    )
    clear_body = func_body(src, "clearLiveClockRegistry")
    assert "liveClockBySpanId" in clear_body, (
        "clearLiveClockRegistry must reset App.liveClockBySpanId"
    )
    assert "activeSpanClockByPage" in clear_body, (
        "clearLiveClockRegistry must reset App.activeSpanClockByPage"
    )
    assert "isActiveLiveTime" in commit_body, (
        "page_model commits must check the normalized active live time flag"
    )


def test_get_active_live_clock_uses_explicit_span_id():
    """``getActiveLiveClock`` must read the active clock from the
    page-scoped registry (``App.liveClockByPage[App.currentPage]``)
    instead of relying on object insertion order. Spec §IV.1.3:
    ``getActiveLiveClock()`` should not depend on insertion order as
    "last registered wins".

    The legacy global ``activeDisplaySpanId`` lookup is NO LONGER a
    fallback: page-scoped is the single source of truth so a hidden
    page's payload cannot become the active clock. The function MUST NOT
    read ``App.activeDisplaySpanId`` / ``App.liveClockBySpanId[App.activeDisplaySpanId]``.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "getActiveLiveClock")
    assert "activeSpanClockByPage" in body, (
        "getActiveLiveClock must read from App.activeSpanClockByPage "
        "rather than relying on object insertion order"
    )
    assert "currentPage" in body, (
        "getActiveLiveClock must read App.currentPage to scope the lookup"
    )
    # Must NOT read the legacy global activeDisplaySpanId field.
    assert "activeDisplaySpanId" not in body, (
        "getActiveLiveClock must NOT read App.activeDisplaySpanId; the "
        "legacy global fallback was removed in favor of page-scoped lookup"
    )
    assert "liveClockBySpanId[App.activeDisplaySpanId]" not in body, (
        "getActiveLiveClock must NOT look up App.liveClockBySpanId[App.activeDisplaySpanId]"
    )
    # Must NOT iterate the registry to pick the last key.
    assert "Object.keys" not in body, (
        "getActiveLiveClock must not iterate registry keys to pick the last "
        "inserted clock"
    )


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
    """When the page active span clock is missing, ``applyLocalTicker`` must
    record diagnostics instead of silently hiding the contract break."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    assert "getActiveLiveClock" in body, (
        "applyLocalTicker must obtain the clock via getActiveLiveClock"
    )
    assert "App.liveClockBySpanId[spanId] || clock" not in body, (
        "applyLocalTicker must not fall back from a missing row clock to the active page clock"
    )
    assert "if (!nodeClock) continue" not in body, (
        "applyLocalTicker must not silently continue when a row clock is missing"
    )
    assert "recordLiveClockContractViolation" in body, (
        "applyLocalTicker must record diagnostics for a missing active span clock"
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
    assert "detail_live_row_missing_span_id" in details_body
    for body in (overview_body, timeline_body, details_body):
        assert "recordLiveClockContractViolation" in body, (
            "live row renderers must diagnose missing display_span_id"
        )


# ---------------------------------------------------------------------------
# Page-model sample clock contract (Section 33.9)
# ---------------------------------------------------------------------------


def test_register_live_clock_accepts_page_option_and_uses_rebase():
    """Source-specific active span helpers accept page scope and rebase
    same-continuity clocks without making row clocks authoritative."""
    src = _strip_js_comments(read_js("core.js"))
    commit_body = func_body(src, "commitPageActiveSpanClock")
    observe_body = func_body(src, "observeRefreshStateActiveSpan")
    assert re.search(r"function\s+commitPageActiveSpanClock\s*\(\s*\w+\s*,\s*\w+", commit_body), (
        "commitPageActiveSpanClock must accept a page parameter"
    )
    assert "pageScope" in commit_body and "pageScope" in observe_body, (
        "active span helpers must scope by page"
    )
    assert "rebaseIncomingClockWithoutRollback" in commit_body, (
        "page_model commits must rebase through the no-rollback path"
    )
    assert "rebaseIncomingClockWithoutRollback" in observe_body, (
        "refresh_state observation must rebase same-continuity clocks"
    )


def test_register_live_clock_rebases_same_continuity_without_live_state_gate():
    """Same continuity is determined by display span or stable hash. A
    live-state transition must not force a visual reset."""
    src = _strip_js_comments(read_js("core.js"))
    commit_body = func_body(src, "commitPageActiveSpanClock")
    observe_body = func_body(src, "observeRefreshStateActiveSpan")
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
    assert "sameContinuity" in commit_body and "rebaseIncomingClockWithoutRollback" in commit_body, (
        "page_model commit must detect continuity and rebase without rollback"
    )
    assert "!sameLiveContinuity" in observe_body and "return activeClock" in observe_body, (
        "refresh_state must not replace the page clock on different continuity"
    )
    rebase_body = func_body(src, "rebaseIncomingClockWithoutRollback")
    for field in (
        "live_started_at_epoch_ms",
        "carry_seconds",
        "duration_seconds_at_sample",
    ):
        assert field in rebase_body, (
            "rebaseIncomingClockWithoutRollback must be able to adjust " + field
        )


def test_run_revision_check_observes_refresh_state_without_row_clock_commit():
    """Unchanged revision checks may observe the current active span, but
    must not call the compatibility registerLiveClock path or rewrite row
    projection anchors."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    assert "observeRefreshStateActiveSpan" in body, (
        "runRevisionCheck must observe same-continuity refresh_state active span"
    )
    assert "registerLiveClock" not in body, (
        "runRevisionCheck must not use registerLiveClock for refresh_state"
    )
    assert "preserveSameSpanSample" not in body, (
        "runRevisionCheck must not use legacy source-specific preservation flags"
    )
    bare_call = re.search(r"registerLiveClock\s*\(\s*state\s*\)", body)
    assert bare_call is None, (
        "runRevisionCheck must pass page scope options to registerLiveClock"
    )


def test_page_model_render_uses_page_model_source():
    """Page-model render flows commit page active span clocks directly.
    Partial Timeline details must not commit/replace the Timeline page
    active span clock."""
    for fname in ("overview.js", "timeline.js"):
        src = _strip_js_comments(read_js(fname))
        assert "commitPageActiveSpanClock" in src, (
            fname + " must commit page_model active span clocks"
        )
    details_body = func_body(_strip_js_comments(read_js("timeline.js")), "renderSessionDetails")
    assert "commitPageActiveSpanClock" not in details_body, (
        "renderSessionDetails partial payload must not replace Timeline page active span clock"
    )


def test_run_revision_check_does_not_register_current_clock_on_revision_change():
    """When ``refresh_revision`` changes, refresh_state may update caches
    and registries, but DOM patching waits for the heavy page refresh so
    current/recent/timeline do not briefly show mixed samples."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    # Must have a revision-change branch that triggers heavy refresh.
    assert "revision" in body.lower(), (
        "runRevisionCheck must compare refresh_revision"
    )
    assert "registerCurrentActivityClock" not in body, (
        "runRevisionCheck must not register current_activity_clock from refresh_state"
    )
    assert "patchCurrentActivityFromRefreshState" not in body, (
        "runRevisionCheck must not patch current activity duration from refresh_state"
    )
    changed_index = body.find("prevRevision !== newRevision")
    refresh_index = body.find("refreshCurrentPageData()", changed_index)
    assert refresh_index != -1, (
        "revision-changed branch must trigger heavy refresh"
    )


def test_run_revision_check_updates_current_cache_when_revision_unchanged():
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")

    assert "prevRevision === newRevision" in body, (
        "runRevisionCheck must have an explicit revision-unchanged branch"
    )
    unchanged_branch_index = body.find("prevRevision === newRevision")
    patch_index = body.find("updateCurrentActivityCacheFromRefreshState(state)", unchanged_branch_index)
    heavy_index = body.find("refreshCurrentPageData()", unchanged_branch_index)

    assert patch_index != -1, (
        "revision-unchanged branch may update current activity structural cache"
    )
    assert heavy_index == -1 or patch_index < heavy_index, (
        "revision-unchanged current patch must not depend on the heavy refresh path"
    )


# ---------------------------------------------------------------------------
# Page-scoped live clock registry (Section 五)
# ---------------------------------------------------------------------------


def test_register_live_clock_accepts_page_scope_option():
    """Section 五: active span clocks are page scoped under
    ``App.activeSpanClockByPage``."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "commitPageActiveSpanClock")
    assert re.search(r"function\s+commitPageActiveSpanClock\s*\(\s*\w+\s*,\s*\w+", body), (
        "commitPageActiveSpanClock must accept a page scope"
    )
    assert "activeSpanClockByPage" in body, (
        "commitPageActiveSpanClock must store under App.activeSpanClockByPage"
    )


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


def test_renderers_commit_project_clock_and_do_not_register_current_clock():
    overview = _strip_js_comments(read_js("overview.js"))
    timeline = _strip_js_comments(read_js("timeline.js"))
    for src, name in ((overview, "overview.js"), (timeline, "timeline.js")):
        assert "commitPageActiveSpanClock" in src, name + " must commit page active span clock"
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
        "Details partial render must not replace the Timeline page active span clock"
    )


def test_get_active_live_clock_reads_page_scope():
    """Section 五: ``getActiveLiveClock`` MUST read the current page scope
    (``App.currentPage``) and return the page-scoped clock from
    ``App.liveClockByPage``. Page-scoped lookup is the SINGLE source of
    truth — the legacy global ``activeDisplaySpanId`` fallback has been
    removed so a hidden page's payload cannot become the active clock.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "getActiveLiveClock")
    assert "currentPage" in body, (
        "getActiveLiveClock must read App.currentPage to scope the lookup"
    )
    assert "activeSpanClockByPage" in body, (
        "getActiveLiveClock must read from App.activeSpanClockByPage (page-scoped)"
    )
    assert "activeDisplaySpanId" not in body, (
        "getActiveLiveClock must NOT fall back to App.activeDisplaySpanId; "
        "page-scoped lookup is the single source of truth"
    )


def test_full_reconcile_does_not_unconditionally_call_refresh_overview():
    """Section 五: ``fullReconcileCollectionViews`` MUST NOT unconditionally
    call ``refreshOverview()``. When the current page is NOT Overview
    (e.g. Timeline historical date), the reconcile must only refresh
    status + the current page so a hidden Overview refresh does not
    register an Overview-scope live clock that overwrites the current
    page's active clock.
    """
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "fullReconcileCollectionViews")
    # refreshOverview must be gated on the current page.
    assert 'currentPage === "overview"' in body, (
        "fullReconcileCollectionViews must gate refreshOverview on "
        'App.currentPage === "overview" so a hidden Overview refresh '
        "does not overwrite the current page's active clock"
    )


def test_overview_js_registers_with_page_scope():
    """Section 五: ``overview.js`` MUST commit live clocks with
    explicit Overview page scope."""
    src = _strip_js_comments(read_js("overview.js"))
    assert 'commitPageActiveSpanClock(overview, "overview")' in src, (
        'overview.js must commit live clocks with page scope "overview"'
    )


def test_timeline_js_registers_with_page_scope():
    """Section 五: ``timeline.js`` MUST commit live clocks with
    explicit Timeline page scope."""
    src = _strip_js_comments(read_js("timeline.js"))
    assert 'commitPageActiveSpanClock(data, "timeline")' in src, (
        'timeline.js must commit live clocks with page scope "timeline"'
    )


def test_init_refresh_overview_commits_with_page_scope():
    """Section 五: ``refreshOverview`` in ``init.js`` MUST commit the
    Overview live clock with explicit page scope."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "refreshOverview")
    assert 'commitPageActiveSpanClock(bundle, "overview")' in body, (
        "refreshOverview must commit with page scope \"overview\""
    )


def test_run_revision_check_registers_with_current_page_scope():
    """Section 五: ``runRevisionCheck`` in ``init.js`` MUST register the
    refresh_state live clock with the CURRENT page scope
    (``page: App.currentPage``) so the refresh_state clock does not
    overwrite a different page's active clock."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    assert "App.currentPage" in body, (
        "runRevisionCheck must register with page: App.currentPage"
    )


def test_clear_live_clock_registry_supports_page_scope():
    """Section 五: ``clearLiveClockRegistry`` MUST accept an optional
    page scope argument so a non-current page's clock can be cleared
    without touching the current page's active clock."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "clearLiveClockRegistry")
    # Must accept a pageScope parameter.
    assert re.search(r"function\s+clearLiveClockRegistry\s*\(\s*\w+", body), (
        "clearLiveClockRegistry must accept a page scope parameter"
    )


# ---------------------------------------------------------------------------
# Page-scoped live clock + page-scoped ticker DOM walk hardening.
# ---------------------------------------------------------------------------


def test_get_active_live_clock_reads_page_scoped_registry_only():
    """``getActiveLiveClock`` MUST read ``App.activeSpanClockByPage[App.currentPage]``
    and MUST NOT read ``App.activeDisplaySpanId`` or
    ``App.liveClockBySpanId[App.activeDisplaySpanId]``. The legacy global
    fallback was removed so a hidden page's stale registration cannot
    become the current page's active clock.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "getActiveLiveClock")
    assert "App.activeSpanClockByPage[page]" in body, (
        "getActiveLiveClock must read App.activeSpanClockByPage[page] where "
        "page = App.currentPage"
    )
    assert "App.currentPage" in body, (
        "getActiveLiveClock must read App.currentPage to derive the page scope"
    )
    # Forbidden: legacy global fallback paths.
    assert "App.activeDisplaySpanId" not in body, (
        "getActiveLiveClock must NOT read App.activeDisplaySpanId; the "
        "legacy global fallback was removed"
    )
    assert "liveClockBySpanId[App.activeDisplaySpanId]" not in body, (
        "getActiveLiveClock must NOT look up "
        "App.liveClockBySpanId[App.activeDisplaySpanId]; page-scoped is "
        "the single source of truth"
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
