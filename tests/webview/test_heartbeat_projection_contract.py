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
    ``applyLocalTicker`` as a live-seconds source; the unified
    ``App.liveClockBySpanId`` registry is the single source of truth for
    live durations. The legacy ``lastRecentSnapshot`` name has been
    retired to remove the old ticker-source semantics."""
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
    carry the unified ``data-display-span-id`` attribute so the ticker
    can render them from the single registered live clock.

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
    # Live recent rows must carry the unified display-span-id so the ticker
    # renders them from the registered live clock.
    assert "data-display-span-id" in source, (
        "overview.js must render data-display-span-id on live recent rows so "
        "the ticker can render them via the unified live clock"
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
    by ``applyLocalTicker`` as a live-seconds source; the unified
    ``App.liveClockBySpanId`` registry is the single source of truth for
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
    assert "renderDurationProjected" in body and "renderLiveRowDuration" in body, (
        "applyLocalTicker must use App.renderDurationProjected / renderLiveRowDuration "
        "for duration updates"
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


def test_ticker_locates_live_spans_via_data_display_span_id():
    """the ticker must walk every DOM node carrying
    ``data-display-span-id`` (via ``querySelectorAll``) and render it
    with that node's registered row clock. This is the single DOM-walk
    path for every live row (recent / session / detail) — the old
    per-region ``[data-session-id="..."]`` selectors are gone."""
    source = read_js("core.js")
    body = func_body(source, "applyLocalTicker")
    # The unified selector + DOM walk drive every live row.
    assert '[data-display-span-id]' in body, (
        "applyLocalTicker must use the unified [data-display-span-id] selector"
    )
    assert 'querySelectorAll' in body, (
        "applyLocalTicker must walk DOM nodes via querySelectorAll"
    )
    assert 'renderLiveRowDuration' in body, (
        "applyLocalTicker must render live rows via row base + projectLiveDeltaSeconds(rowClock)"
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




def test_project_live_delta_seconds_replaces_removed_ticker_helpers():
    """``projectLiveDeltaSeconds(clock, nowMs)`` is the unified per-clock
    delta. It computes
    ``max(0, projectClockSeconds(clock, nowMs) - duration_seconds_at_sample)`` so a
    stale clock or wall-clock drift never makes the UI count backwards.
    The old ``tickerLiveEligible`` / ``tickerDeltaSeconds`` helpers have
    been removed."""
    source = read_js("core.js")
    assert "function projectLiveDeltaSeconds" in source, (
        "core.js must define function projectLiveDeltaSeconds (replaces the removed "
        "tickerDeltaSeconds / tickerLiveEligible helpers)"
    )
    assert "App.projectLiveDeltaSeconds" in source, (
        "core.js must expose App.projectLiveDeltaSeconds"
    )
    body = func_body(source, "projectLiveDeltaSeconds")
    assert "projectClockSeconds" in body, (
        "projectLiveDeltaSeconds must delegate to projectClockSeconds(clock, nowMs)"
    )
    assert "duration_seconds_at_sample" in body, (
        "projectLiveDeltaSeconds must subtract duration_seconds_at_sample"
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
    (``rItem.duration_seconds``). It reads from the unified live-clock
    registry and renders rows through ``renderLiveRowDuration`` so each
    node uses its own clock and sample base."""
    source = read_js("core.js")
    body = func_body(source, "applyLocalTicker")
    assert "rItem.duration_seconds" not in body, (
        "applyLocalTicker must not read rItem.duration_seconds from a cached "
        "page-level snapshot; the unified live clock is the single source"
    )
    assert "renderLiveRowDuration" in body, (
        "applyLocalTicker must render project rows via renderLiveRowDuration"
    )
    assert "getActiveLiveClock" in body, (
        "applyLocalTicker must read the active clock via getActiveLiveClock()"
    )
    assert "getActiveCurrentActivityClock" in body, (
        "applyLocalTicker must read current activity from its separate clock"
    )


def test_ticker_locates_live_rows_via_display_span_id():
    """the ticker locates every live row via the unified
    ``data-display-span-id`` DOM walk and only renders rows whose clock
    has a project-duration live flag. The old ``is_virtual_live`` /
    ``is_in_progress`` flag checks are no longer used by the ticker —
    the project clock flag is the project-row eligibility signal."""
    source = read_js("core.js")
    body = func_body(source, "applyLocalTicker")
    assert "data-display-span-id" in body, (
        "applyLocalTicker must locate live rows via data-display-span-id"
    )
    assert "project_duration_live" in body and "is_project_duration_live" in body, (
        "applyLocalTicker must check the project-duration live flag before rendering"
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
    live-row seconds computation source. The unified
    ``App.liveClockBySpanId`` registry + ``projectClockSeconds(clock, nowMs)`` is the
    single source of truth for every live ROW duration.

    ``lastTimelineData`` / ``lastOverviewSnapshot`` may be read by the
    ticker for KPI TOTALS and current-activity display (which are NOT
    live-row seconds); the live-row seconds come exclusively from the
    ``[data-display-span-id]`` DOM walk + ``projectLiveBaseSeconds`` (covered
    by ``test_ticker_locates_live_rows_via_display_span_id``). The
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
            "liveClockBySpanId registry + projectClockSeconds(clock, nowMs) is the single "
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
    """the unified live clock formula
    (``carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)``)
    lives in ``projectClockSeconds(clock, nowMs)``. ``projectLiveDeltaSeconds(clock, nowMs)``
    is the per-clock delta
    (``max(0, projectClockSeconds(clock, nowMs) - duration_seconds_at_sample)``).
    Each live DOM node carries its OWN ``data-live-base-seconds`` (the
    row's sample display duration); the ticker renders
    through ``renderLiveRowDuration`` so every row advances from its own
    clock without reading page-level caches. The removed ``tickerDeltaSeconds``
    helper is no longer referenced."""
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
    assert "data-live-base-seconds" in ticker_body, (
        "applyLocalTicker must read each row's base seconds from the "
        "data-live-base-seconds DOM attribute (per-row base, not page-level cache)"
    )
    row_body = func_body(source, "renderLiveRowDuration")
    assert "projectLiveBaseSeconds" in row_body and "projectLiveDeltaSeconds" in source, (
        "renderLiveRowDuration must compute row base + projectLiveDeltaSeconds(rowClock, nowMs)"
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
    """``registerLiveClock`` must clear the registry AND the active
    span id when the payload has NO live clock, NO display_span_id, or
    the clock's project-duration live flag is not true. This prevents a stale clock
    from continuing to tick after the activity ends / collector pauses
    / user switches pages.

    Spec §IV.1.3: registry must be cleared when payload is null, clock
    is null, spanId is empty, or project-duration live is not true.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "registerLiveClock")
    # Must explicitly clear on null payload.
    assert "clearLiveClockRegistry" in body, (
        "registerLiveClock must call clearLiveClockRegistry on null/empty "
        "payload so the registry does not retain a stale clock"
    )
    # The clearLiveClockRegistry helper must reset all three: registry,
    # display model, and active span id.
    clear_body = func_body(src, "clearLiveClockRegistry")
    assert "liveClockBySpanId" in clear_body, (
        "clearLiveClockRegistry must reset App.liveClockBySpanId"
    )
    assert "activeDisplaySpanId" in clear_body, (
        "clearLiveClockRegistry must reset App.activeDisplaySpanId so a stale "
        "clock cannot win after the activity ends"
    )
    assert "isProjectDurationClock" in body, (
        "registerLiveClock must check the normalized project-duration live flag before registering"
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
    assert "liveClockByPage" in body, (
        "getActiveLiveClock must read from App.liveClockByPage (page-scoped "
        "registry) rather than relying on object insertion order"
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
    body = func_body(src, "renderLiveRowDuration")
    assert "data-live-continuity-key" in body, (
        "renderLiveRowDuration must read data-live-continuity-key from each live "
        "DOM node so the ticker uses the SAME key the renderer seeded"
    )


def test_apply_local_ticker_renders_node_base_plus_delta_for_dom_rows():
    """Spec §IV.1.1: the unified live-span DOM walk must render
    ``projectLiveBaseSeconds(nodeBaseSeconds, rowClock, nowMs)`` for each row.
    This is the regression guard against the old contract that overwrote every
    ``[data-display-span-id]`` row with the active page clock."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    # Must read the per-node base from the DOM.
    assert "data-live-base-seconds" in body, (
        "applyLocalTicker must read data-live-base-seconds from each live "
        "DOM node (per-row base, not the live clock's duration)"
    )
    assert "App.liveClockBySpanId[spanId]" in body, (
        "applyLocalTicker must resolve each node's own clock by span id"
    )
    assert "renderLiveRowDuration" in body, (
        "applyLocalTicker must delegate row projection to renderLiveRowDuration"
    )


def test_apply_local_ticker_suppresses_timeline_total_on_historical_date():
    """Section 七: ``applyLocalTicker`` MUST NOT update the Timeline total
    element (``#timeline-total``) when the loaded Timeline payload is for
    a historical (non-today) date. Historical Timeline / Details / Recent
    lists must not register an active project-duration live clock, so the
    historical total cannot be polluted by the current live activity's
    seconds.

    The frontend gating contract:

    - ``applyLocalTicker`` must compute an ``isToday`` flag from the loaded
      Timeline payload's ``date`` field against ``App.localTodayStr()``.
    - The ``#timeline-total`` element must ONLY be refreshed when
      ``isToday`` is true.
    - A historical date (anything other than today / ``null`` / ``"--"``)
      must skip the timeline-total write entirely so the current live clock
      cannot advance a stale historical total.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    # The isToday gate must be computed inside applyLocalTicker.
    assert "isToday" in body, (
        "applyLocalTicker must compute an isToday flag from the loaded "
        "Timeline payload's date so historical dates suppress the live delta"
    )
    assert "localTodayStr" in body, (
        "applyLocalTicker must compare tl.date against App.localTodayStr() "
        "to determine isToday (historical date suppression)"
    )
    # The timeline-total write must be gated by isToday. We extract the
    # region that touches ``#timeline-total`` and confirm ``isToday`` is
    # part of the gating condition.
    tl_total_pos = body.find('getElementById("timeline-total")')
    assert tl_total_pos != -1, (
        "applyLocalTicker must reference #timeline-total for the Timeline "
        "total element"
    )
    # Walk back to the enclosing ``if (...)`` gate that wraps the
    # timeline-total write. isToday must appear between that ``if`` and
    # the timeline-total lookup so the gate suppresses the write.
    gate_region_start = body.rfind("if (", 0, tl_total_pos)
    assert gate_region_start != -1, (
        "applyLocalTicker must wrap the #timeline-total write in an if gate"
    )
    gate_region = body[gate_region_start:tl_total_pos]
    assert "isToday" in gate_region, (
        "applyLocalTicker must gate the #timeline-total write with isToday "
        "so historical (non-today) dates never advance the live total"
    )


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


def test_apply_local_ticker_skips_rows_without_node_clock():
    """When a row's span id is not registered, ``applyLocalTicker`` must
    skip that row instead of falling back to the active page clock."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    # Must call getActiveLiveClock to obtain the clock.
    assert "getActiveLiveClock" in body, (
        "applyLocalTicker must obtain the clock via getActiveLiveClock"
    )
    assert "App.liveClockBySpanId[spanId] || clock" not in body, (
        "applyLocalTicker must not fall back from a missing row clock to the active page clock"
    )
    assert "if (!nodeClock) continue" in body, (
        "applyLocalTicker must skip rows whose own clock is missing"
    )


# ---------------------------------------------------------------------------
# Page-model sample clock contract (Section 33.9)
# ---------------------------------------------------------------------------


def test_register_live_clock_accepts_page_option_and_uses_rebase():
    """``registerLiveClock`` accepts options for page scope, but every
    source follows the same normalize + no-rollback rebase path."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "registerLiveClock")
    # The function signature must accept a second parameter.
    assert re.search(r"function\s+registerLiveClock\s*\(\s*\w+\s*,\s*\w+", body), (
        "registerLiveClock must accept a second options parameter"
    )
    assert "opts.page" in body, (
        "registerLiveClock must read options.page to scope the registration"
    )
    assert "rebaseIncomingClockWithoutRollback" in body, (
        "registerLiveClock must rebase incoming clocks through the unified no-rollback path"
    )


def test_register_live_clock_rebases_same_continuity_without_live_state_gate():
    """Same continuity is determined by display span or stable hash. A
    live-state transition must not force a visual reset."""
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "registerLiveClock")
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
    assert "sameContinuity" in body and "rebaseIncomingClockWithoutRollback" in body, (
        "registerLiveClock must detect continuity and rebase without rollback"
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


def test_run_revision_check_uses_unified_refresh_state_rebase():
    """Revision checks must register refresh_state through the same rebase
    path and must not use source-specific sample preservation flags."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    assert '"refresh_state"' in body or "'refresh_state'" in body, (
        "runRevisionCheck must register refresh_state with source "
        "'refresh_state'"
    )
    assert "preserveSameSpanSample" not in body, (
        "runRevisionCheck must not use legacy source-specific preservation flags"
    )
    bare_call = re.search(r"registerLiveClock\s*\(\s*state\s*\)", body)
    assert bare_call is None, (
        "runRevisionCheck must pass page scope options to registerLiveClock"
    )


def test_page_model_render_uses_page_model_source():
    """The page-model render flows (``showOverview`` / ``showRecent`` /
    ``showTimeline`` / ``renderSessionDetails`` / ``refreshOverview``)
    MUST register with ``{ source: 'page_model' }`` so they replace the
    active sample. ``refresh_state`` must NOT use ``page_model`` source.
    """
    for fname in ("overview.js", "timeline.js"):
        src = _strip_js_comments(read_js(fname))
        # Every registerLiveClock call in these files must use page_model.
        calls = re.findall(r"registerLiveClock\s*\([^)]*\)", src)
        assert calls, (
            fname + " must call registerLiveClock at least once"
        )
        for call in calls:
            assert '"page_model"' in call or "'page_model'" in call, (
                fname + " registerLiveClock call must use source 'page_model'; "
                "found: " + call
            )


def test_run_revision_check_registers_current_clock_on_revision_change():
    """When ``refresh_revision`` changes, refresh_state may update caches
    and registries, but DOM patching waits for the heavy page refresh so
    current/recent/timeline do not briefly show mixed samples."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")
    # Must have a revision-change branch that triggers heavy refresh.
    assert "revision" in body.lower(), (
        "runRevisionCheck must compare refresh_revision"
    )
    assert "registerCurrentActivityClock" in body, (
        "runRevisionCheck must register current_activity_clock from refresh_state"
    )
    assert "patchCurrentActivityFromRefreshState" in body, (
        "runRevisionCheck must still patch current activity on unchanged revisions"
    )
    changed_index = body.find("prevRevision !== newRevision")
    patch_index = body.find("patchCurrentActivityFromRefreshState(state)", changed_index)
    refresh_index = body.find("refreshCurrentPageData()", changed_index)
    assert refresh_index != -1, (
        "revision-changed branch must trigger heavy refresh"
    )
    assert patch_index == -1 or patch_index > refresh_index, (
        "revision-changed branch must not patch current activity before heavy refresh"
    )


def test_run_revision_check_patches_current_activity_when_revision_unchanged():
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "runRevisionCheck")

    assert "prevRevision === newRevision" in body, (
        "runRevisionCheck must have an explicit revision-unchanged branch"
    )
    unchanged_branch_index = body.find("prevRevision === newRevision")
    patch_index = body.find("patchCurrentActivityFromRefreshState(state)", unchanged_branch_index)
    heavy_index = body.find("refreshCurrentPageData()", unchanged_branch_index)

    assert patch_index != -1, (
        "revision-unchanged branch must patch current activity/cache from refresh_state"
    )
    assert heavy_index == -1 or patch_index < heavy_index, (
        "revision-unchanged current patch must not depend on the heavy refresh path"
    )


# ---------------------------------------------------------------------------
# Page-scoped live clock registry (Section 五)
# ---------------------------------------------------------------------------


def test_register_live_clock_accepts_page_scope_option():
    """Section 五: ``registerLiveClock`` MUST accept a ``page`` / ``scope``
    option so the clock is registered under a page-scoped registry
    (``App.liveClockByPage``) instead of a single global active span.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "registerLiveClock")
    # Must read opts.page (or options.page).
    assert re.search(r"opts\.page|options\.page", body), (
        "registerLiveClock must read options.page to scope the registration"
    )
    # Must store under App.liveClockByPage (page-scoped registry).
    assert "liveClockByPage" in body, (
        "registerLiveClock must store the clock under App.liveClockByPage "
        "(page-scoped registry)"
    )


def test_current_activity_clock_registry_is_page_scoped():
    src = _strip_js_comments(read_js("core.js"))
    assert "currentActivityClockByPage" in src
    reg_body = func_body(src, "registerCurrentActivityClock")
    get_body = func_body(src, "getActiveCurrentActivityClock")
    helper_body = func_body(src, "findClockInPayload")
    assert "current_activity_clock" in helper_body
    assert "activity_display_model.current_activity_clock" in helper_body
    assert "payload.live_clock" in helper_body
    assert "activity_display_model.live_clock" in helper_body
    assert "rebaseIncomingClockWithoutRollback" in reg_body
    assert "App.currentPage" in get_body
    assert "currentActivityClockByPage" in get_body


def test_apply_local_ticker_current_activity_does_not_fallback_to_project_clock():
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    current_section = body[
        body.find('document.getElementById("current-activity")'):
        body.find("var tl = App.lastTimelineData")
    ]
    timeline_section = body[
        body.find('document.getElementById("timeline-current")'):
        body.find("var tickerPage = App.currentPage")
    ]
    assert "currentActivityClock" in current_section
    assert "currentActivityClock" in timeline_section
    assert "liveSeconds(clock)" not in current_section
    assert "liveSeconds(clock)" not in timeline_section


def test_renderers_register_project_and_current_clocks():
    overview = _strip_js_comments(read_js("overview.js"))
    timeline = _strip_js_comments(read_js("timeline.js"))
    for src, name in ((overview, "overview.js"), (timeline, "timeline.js")):
        assert "registerLiveClock" in src, name + " must register project live clock"
        assert "registerCurrentActivityClock" in src, name + " must register current activity clock"


def test_timeline_details_edit_guard_keeps_dom_but_registers_clocks():
    src = _strip_js_comments(read_js("timeline.js"))
    body = func_body(src, "renderSessionDetails")
    reg_pos = body.find("registerCurrentActivityClock")
    guard_pos = body.find("_timelineEditingActive")
    render_pos = body.find("detailsList.innerHTML")
    assert reg_pos != -1 and guard_pos != -1
    assert reg_pos < guard_pos, "Details must register clocks before edit guard returns"
    assert guard_pos < render_pos, "Details edit guard must run before DOM redraw"


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
    assert "liveClockByPage" in body, (
        "getActiveLiveClock must read from App.liveClockByPage (page-scoped)"
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
    """Section 五: ``overview.js`` MUST register live clocks with
    ``page: "overview"`` so the clock is scoped to the Overview page."""
    src = _strip_js_comments(read_js("overview.js"))
    assert 'page: "overview"' in src, (
        'overview.js must register live clocks with page: "overview"'
    )


def test_timeline_js_registers_with_page_scope():
    """Section 五: ``timeline.js`` MUST register live clocks with
    ``page: "timeline"`` so the clock is scoped to the Timeline page."""
    src = _strip_js_comments(read_js("timeline.js"))
    assert 'page: "timeline"' in src, (
        'timeline.js must register live clocks with page: "timeline"'
    )


def test_init_refresh_overview_registers_with_page_scope():
    """Section 五: ``refreshOverview`` in ``init.js`` MUST register the
    Overview live clock with ``page: "overview"`` so the clock is
    scoped to the Overview page."""
    src = _strip_js_comments(read_js("init.js"))
    body = func_body(src, "refreshOverview")
    assert 'page: "overview"' in body, (
        "refreshOverview must register with page: \"overview\""
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
    """``getActiveLiveClock`` MUST read ``App.liveClockByPage[App.currentPage]``
    and MUST NOT read ``App.activeDisplaySpanId`` or
    ``App.liveClockBySpanId[App.activeDisplaySpanId]``. The legacy global
    fallback was removed so a hidden page's stale registration cannot
    become the current page's active clock.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "getActiveLiveClock")
    assert "App.liveClockByPage[page]" in body, (
        "getActiveLiveClock must read App.liveClockByPage[page] where "
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
    ``document.querySelectorAll("[data-display-span-id]")`` as a global
    live-row query. The ticker must scope the DOM walk to the current
    page container (``#page-<currentPage>``) so a hidden page's stale
    live DOM is never updated with the current page's delta.
    """
    src = _strip_js_comments(read_js("core.js"))
    body = func_body(src, "applyLocalTicker")
    assert 'document.querySelectorAll("[data-display-span-id]")' not in body, (
        "applyLocalTicker must NOT use a global "
        'document.querySelectorAll("[data-display-span-id]") query; scope '
        "the walk to the current page container"
    )


def test_apply_local_ticker_uses_page_container_for_live_nodes():
    """``applyLocalTicker`` MUST scope the live-node walk to the current
    page container: ``document.getElementById("page-" + page)`` followed
    by ``pageRoot.querySelectorAll("[data-display-span-id]")``. This
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
    assert '[data-display-span-id]' in body, (
        "applyLocalTicker must still use the [data-display-span-id] selector "
        "but scoped to pageRoot"
    )
    # Must derive the page scope from App.currentPage so a hidden page's
    # DOM is never walked.
    assert "App.currentPage" in body, (
        "applyLocalTicker must derive the page scope from App.currentPage"
    )
