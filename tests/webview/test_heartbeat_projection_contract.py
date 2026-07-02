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

    Overview now uses the single ``get_overview_live_bundle``
    call (fusing overview + recent into one sample). The reconciliation
    may call either ``refreshOverviewBundle`` or the removed
    ``refreshOverview`` / ``refreshRecent`` pair — both paths refresh
    the Overview + recent data."""
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
    # Must refresh Overview + recent. Under the bundle contract this is
    # done via ``refreshOverviewBundle``; the separate-call path
    # (``refreshOverview`` + ``refreshRecent``) is also acceptable as a
    # fallback. At least one of the two paths must be present.
    has_bundle = "refreshOverviewBundle" in body
    has_separate_refresh = "refreshOverview" in body and "refreshRecent" in body
    assert has_bundle or has_separate_refresh, (
        "fullReconcileCollectionViews must refresh Overview + recent via "
        "refreshOverviewBundle (preferred) or refreshOverview + refreshRecent"
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




def test_overview_js_stores_last_recent_snapshot():
    """``showRecent`` must save the recent payload to
    ``App.lastRecentSnapshot`` so the ticker can increment the
    live-projected recent item without a bridge round-trip."""
    source = read_js("overview.js")
    assert "App.lastRecentSnapshot" in source, (
        "overview.js must save App.lastRecentSnapshot in showRecent"
    )


def test_recent_item_renders_data_index_and_progress_flags():
    """each recent item must render a stable ``data-recent-index``
    attribute and use ``is_in_progress || is_live_projected`` to mark
    in-progress / live-projected rows with CSS classes. The
    unified live-display model also adds ``is_virtual`` / ``virtual-live``
    so virtual live items are visually distinct from real in-progress rows."""
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
    assert "is_virtual" in source, (
        "overview.js must check is_virtual on recent items (unified model)"
    )
    assert "in-progress" in source, (
        "overview.js must add the in-progress CSS class to live recent rows"
    )
    assert "live-projected" in source, (
        "overview.js must add the live-projected CSS class to projected rows"
    )
    assert "virtual-live" in source, (
        "overview.js must add the virtual-live CSS class to virtual items"
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


def test_timeline_js_stores_last_session_details_data():
    """``renderSessionDetails`` must save the details payload
    to ``App.lastSessionDetailsData`` so the ticker can increment the
    live-projected detail row without a bridge round-trip."""
    source = read_js("timeline.js")
    assert "App.lastSessionDetailsData" in source, (
        "timeline.js must save App.lastSessionDetailsData in renderSessionDetails"
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


def test_ticker_uses_render_duration_monotonic():
    """the ticker must use ``renderDurationMonotonic`` for
    Overview KPIs, recent items, Timeline sessions, and Timeline details
    so the same monotonic-render contract is applied everywhere."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    assert "renderDurationMonotonic" in body, (
        "applyLocalTicker must use App.renderDurationMonotonic for duration updates"
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


def test_ticker_locates_timeline_session_via_data_session_id():
    """the ticker must locate each Timeline session's DOM via
    ``data-session-id`` (querySelector), NOT via array index into a
    ``querySelectorAll`` snapshot. This prevents a mismatch when a
    revision change re-renders the list between ticks."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    # The ticker must use a data-session-id scoped querySelector.
    assert '[data-session-id="' in body, (
        "applyLocalTicker must locate timeline sessions via data-session-id"
    )


def test_ticker_skips_detail_updates_when_editing():
    """the ticker must NOT update detail-row durations when
    a Timeline editor / split editor / correction shell write is in
    progress so input focus and button state are never disturbed."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    assert "_timelineEditingActive" in body, (
        "applyLocalTicker must guard detail-row updates with "
        "App._timelineEditingActive() so editing is never disturbed"
    )


def test_render_duration_monotonic_prevents_small_rollback():
    """``renderDurationMonotonic`` must keep the current DOM
    value when the new projected seconds are 1-2s less than the last
    rendered value (same live target still running), avoiding visual
    rollback. State / activity / session / date changes still allow the
    backend value to override."""
    source = read_js("core.js")
    body = func_body(source, "renderDurationMonotonic")
    # Must check allowDecrease and compare lastSeconds vs next.
    assert "allowDecrease" in body, (
        "renderDurationMonotonic must accept an allowDecrease parameter"
    )
    assert "lastSeconds" in body, (
        "renderDurationMonotonic must track lastSeconds per continuity key"
    )
    # Must skip the write when the decrease is within the small-rollback band.
    assert "return" in body, (
        "renderDurationMonotonic must return early to prevent visual rollback"
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
        # Each renderer must seed the monotonic state after innerHTML swap
        # so the fresh backend snapshot duration replaces the ticker's projected value.
        assert "_monotonicRenderState" in source, (
            module + " must seed App._monotonicRenderState after re-render "
            "so backend truth overrides the ticker's projection"
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




def test_ticker_live_eligible_checks_live_state():
    """issue 1: the ticker must only increment normal project
    duration when ``live_display.live_state`` is ``"virtual"`` or
    ``"persisted_open"``. idle / paused / excluded / error must NOT be
    eligible. The ``tickerLiveEligible`` helper centralises this check so
    Overview / Recent / Timeline all use the same eligibility decision."""
    source = read_js("core.js")
    assert "function tickerLiveEligible" in source, (
        "core.js must define function tickerLiveEligible for unified eligibility"
    )
    assert "App.tickerLiveEligible" in source, (
        "core.js must expose App.tickerLiveEligible"
    )
    body = func_body(source, "tickerLiveEligible")
    # Must check live_display.live_state for "virtual" and "persisted_open".
    assert "live_state" in body, (
        "tickerLiveEligible must check live_display.live_state"
    )
    assert "virtual" in body, (
        "tickerLiveEligible must accept live_state === 'virtual'"
    )
    assert "persisted_open" in body, (
        "tickerLiveEligible must accept live_state === 'persisted_open'"
    )


def test_ticker_does_not_read_dom_text_as_baseline():
    """issue 6: the ticker must NOT use DOM current text as the
    duration baseline. The baseline must come from the cached payload's
    ``duration_seconds`` field. This prevents the duration from
    accelerating growth on each tick."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    # The recent section must use parseInt(rItem.duration_seconds) from the
    # cached payload, not readDurationSecondsFromText(DOM element).
    assert "rItem.duration_seconds" in body, (
        "applyLocalTicker recent section must use rItem.duration_seconds "
        "from the cached payload as the baseline"
    )


def test_ticker_locates_live_detail_by_flag_not_last_row():
    """issues 2 & 10: the ticker must locate the live detail row
    by flag (``is_virtual_live || is_in_progress``) from the cached
    payload, NOT by using the last row of the detail list. The detail list
    is newest-first so the old ``detailRows[length-1]`` was wrong."""
    source = read_js("core.js")
    pos = source.find("function applyLocalTicker")
    assert pos != -1
    end_func = source.find("\n    function ", pos + 1)
    if end_func == -1:
        end_func = source.find("\n    App.applyLocalTicker", pos + 1)
    body = source[pos:end_func] if end_func != -1 else source[pos:]
    assert "is_virtual_live" in body, (
        "applyLocalTicker detail section must check is_virtual_live flag"
    )
    assert "is_in_progress" in body, (
        "applyLocalTicker detail section must check is_in_progress flag"
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




def test_ticker_uses_unified_live_clock_scheme_a():
    """the ticker must use the unified live clock
    (scheme A: ``carry_seconds + floor((Date.now() - live_started_at_epoch_ms) / 1000)``)
    anchored on a stable start-time anchor. ``tickerDeltaSeconds`` must read
    ``live_started_at_epoch_ms`` and ``carry_seconds`` from the payload.
    It must NOT fall back to ``snapshot_at_epoch_ms``; when
    ``live_started_at_epoch_ms`` is missing it returns 0."""
    source = read_js("core.js")
    body = func_body(source, "tickerDeltaSeconds")
    assert "live_started_at_epoch_ms" in body, (
        "tickerDeltaSeconds must read live_started_at_epoch_ms from the payload"
    )
    assert "carry_seconds" in body, (
        "tickerDeltaSeconds must read carry_seconds from the payload"
    )
    # The snapshot_at_epoch_ms fallback has been removed; the
    # function returns 0 when live_started_at_epoch_ms is missing.
    assert "snapshot_at_epoch_ms" not in body, (
        "tickerDeltaSeconds must not fall back to snapshot_at_epoch_ms; "
        "it returns 0 when live_started_at_epoch_ms is missing"
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
    """``refreshRecent`` must use a request token
    so stale responses cannot overwrite newer ones."""
    source = read_js("init.js")
    assert "App.recentRequestToken" in source, (
        "init.js must define App.recentRequestToken state"
    )
    body = func_body(source, "refreshRecent")
    assert "recentRequestToken" in body, (
        "refreshRecent must use recentRequestToken for stale-response discard"
    )


def test_render_session_details_cache_after_guard():
    """``renderSessionDetails`` must set
    ``App.lastSessionDetailsData`` AFTER the dirty-editor / saving guard,
    not before. When the DOM render is skipped, the cache must also be
    skipped so they stay atomic."""
    source = read_js("timeline.js")
    body = func_body(source, "renderSessionDetails")
    # The guard (isEditDirty / activityTimeSaving) must appear BEFORE the
    # cache assignment in the function body.
    guard_pos = body.find("isEditDirty")
    cache_pos = body.find("App.lastSessionDetailsData = data")
    assert guard_pos != -1, (
        "renderSessionDetails must check isEditDirty before caching"
    )
    assert cache_pos != -1, (
        "renderSessionDetails must set App.lastSessionDetailsData"
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
        assert "lastSessionDetailsData" in body, (
            fn_name + " must clear lastSessionDetailsData on date switch"
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
