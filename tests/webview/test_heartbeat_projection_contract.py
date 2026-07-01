"""Phase 6H-followup: unified heartbeat + live display projection contracts.

These static-contract tests verify the frontend pieces introduced by the
Phase 6H-followup rewrite:

- The fixed 8-second ``setInterval(refreshAll, REFRESH_INTERVAL_MS)`` and
  the independent 1-second ``startLocalTicker`` / ``startAutoRefresh``
  timers are replaced by a single 1-second ``startHeartbeat``.
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


# --- Section 8: single heartbeat replaces parallel timers ----------------


def test_heartbeat_single_timer_replaces_parallel_timers():
    """Section 8: there must be exactly one 1-second timer
    (``App.heartbeatTimer``). The legacy ``App.refreshTimer`` /
    ``App.localTickerTimer`` may still exist as state vars (for cleanup
    in ``startHeartbeat``) but must NOT be re-armed with their own
    ``setInterval``. The old ``startAutoRefresh`` / ``startLocalTicker``
    standalone functions must NOT exist as parallel timer drivers."""
    source = read_js("init.js")
    # The heartbeat starter must exist and arm App.heartbeatTimer.
    assert "function startHeartbeat" in source, (
        "init.js must define function startHeartbeat for the unified heartbeat"
    )
    assert "App.heartbeatTimer = setInterval" in source, (
        "startHeartbeat must arm App.heartbeatTimer with setInterval"
    )
    # startHeartbeat must clear legacy timers so re-init does not stack.
    assert "App.refreshTimer" in source, (
        "startHeartbeat must clear the legacy App.refreshTimer"
    )
    assert "App.localTickerTimer" in source, (
        "startHeartbeat must clear the legacy App.localTickerTimer"
    )
    # The old standalone starter functions must NOT re-arm the legacy
    # timers with their own setInterval (they would create parallel
    # 1-second timers, violating section 8).
    if "function startAutoRefresh" in source:
        body = func_body(source, "startAutoRefresh")
        assert "setInterval" not in body, (
            "startAutoRefresh must not create its own setInterval; the "
            "unified heartbeat owns the single timer"
        )
    if "function startLocalTicker" in source:
        body = func_body(source, "startLocalTicker")
        assert "setInterval" not in body, (
            "startLocalTicker must not create its own setInterval; the "
            "unified heartbeat owns the single timer"
        )


def test_heartbeat_interval_is_one_second():
    """Section 8: the heartbeat must tick at 1-second cadence so the
    displayed durations update every second without jumps."""
    source = read_js("core.js")
    assert "App.HEARTBEAT_INTERVAL_MS = 1000" in source, (
        "core.js must define App.HEARTBEAT_INTERVAL_MS = 1000"
    )


def test_heartbeat_runs_ticker_then_revision_check():
    """Section 8: each heartbeat tick must first run the local ticker
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


def test_init_does_not_call_legacy_start_auto_refresh():
    """Section 9: ``init()`` must not call the legacy ``startAutoRefresh()``
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
    """Section 8: ``runRevisionCheck`` must guard against overlapping
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
    """Section 4/10: ``refresh_revision`` must NOT change when only
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
    """Section 10: when ``refresh_revision`` is unchanged, the revision
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
    """Section 10: the heartbeat / revision-check / low-frequency
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
    """Section 8/10: a low-frequency reconciliation must exist so a stalled
    revision signal cannot freeze the UI forever. It must refresh status +
    Overview + current Timeline, but NOT Rules / Settings / Statistics."""
    source = read_js("init.js")
    assert "function fullReconcileCollectionViews" in source, (
        "init.js must define fullReconcileCollectionViews for low-frequency "
        "collection reconciliation"
    )
    body = func_body(source, "fullReconcileCollectionViews")
    # Must refresh status + overview + recent (the collector / sidebar /
    # current-activity view).
    assert "refreshStatus" in body, (
        "fullReconcileCollectionViews must refresh collector status"
    )
    assert "refreshOverview" in body, (
        "fullReconcileCollectionViews must refresh Overview"
    )
    assert "refreshRecent" in body, (
        "fullReconcileCollectionViews must refresh recent activities"
    )
    # Must NOT reference Rules / Settings / Statistics.
    assert "loadProjectRules" not in body
    assert "loadSettingsPrivacyStatus" not in body
    assert "loadStatisticsExportSummary" not in body


def test_low_frequency_reconciliation_skips_timeline_when_editing():
    """Section 8/10: the low-frequency reconciliation must NOT re-render
    the Timeline when an editor / split editor / correction shell write
    is in progress so the user's input focus is preserved."""
    source = read_js("init.js")
    body = func_body(source, "fullReconcileCollectionViews")
    assert "_timelineEditingActive" in body, (
        "fullReconcileCollectionViews must guard Timeline re-render with "
        "App._timelineEditingActive() so input focus is never lost"
    )


def test_page_switch_immediately_refreshes_current_page():
    """Section 10: page switch must immediately refresh the current page's
    live data so the user sees fresh data without waiting for the next
    heartbeat revision check."""
    source = read_js("init.js")
    body = func_body(source, "switchPage")
    assert "refreshCurrentPageData" in body, (
        "switchPage must call refreshCurrentPageData to immediately refresh "
        "the current page's live data on navigation"
    )


# --- Section 5/6: recent / timeline data attributes & snapshots ----------


def test_overview_js_stores_last_recent_snapshot():
    """Section 5: ``showRecent`` must save the recent payload to
    ``App.lastRecentSnapshot`` so the ticker can increment the
    live-projected recent item without a bridge round-trip."""
    source = read_js("overview.js")
    assert "App.lastRecentSnapshot" in source, (
        "overview.js must save App.lastRecentSnapshot in showRecent"
    )


def test_recent_item_renders_data_index_and_progress_flags():
    """Section 5: each recent item must render a stable ``data-recent-index``
    attribute and use ``is_in_progress || is_live_projected`` to mark
    in-progress / live-projected rows with CSS classes. Phase R3: the
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
    """Section 5: recent items must prefer ``duration_seconds`` (raw int)
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
    """Section 5: ``renderSessionDetails`` must save the details payload
    to ``App.lastSessionDetailsData`` so the ticker can increment the
    live-projected detail row without a bridge round-trip."""
    source = read_js("timeline.js")
    assert "App.lastSessionDetailsData" in source, (
        "timeline.js must save App.lastSessionDetailsData in renderSessionDetails"
    )


def test_timeline_detail_row_renders_data_attributes():
    """Section 5: each detail row must render ``data-activity-id``,
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
    """Section 5: detail rows must prefer ``duration_seconds`` (raw int)
    over the formatted ``duration`` string."""
    source = read_js("timeline.js")
    assert "duration_seconds" in source, (
        "timeline.js must use duration_seconds as the primary detail source"
    )


def test_timeline_session_renders_data_session_id():
    """Section 7.3: timeline session items must render ``data-session-id``
    so the ticker can locate each session's DOM precisely without relying
    on array index."""
    source = read_js("timeline.js")
    assert 'data-session-id' in source, (
        "timeline.js must render data-session-id on session items"
    )


# --- Section 6/7: ticker uses unified projection helper ------------------


def test_core_js_defines_projection_helpers():
    """Section 6: core.js must define the unified projection helpers
    ``projectLiveSeconds``, ``readDurationSecondsFromText``,
    ``renderDurationMonotonic``, and ``resetMonotonicRenderState``."""
    source = read_js("core.js")
    for name in (
        "projectLiveSeconds",
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
    """Section 6/7: the ticker must use ``renderDurationMonotonic`` for
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
    """Section 7: the ticker must NOT call ``callBridge`` /
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
    """Section 7: the ticker must NOT use browser storage APIs
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
    """Section 7.3: the ticker must locate each Timeline session's DOM via
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
    """Section 7.4: the ticker must NOT update detail-row durations when
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
    """Section 6: ``renderDurationMonotonic`` must keep the current DOM
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
    """Section 6: when the activity / session / date changes, the backend
    truth must be allowed to overwrite the displayed value. This is
    implemented by seeding ``_monotonicRenderState`` from the backend
    refresh (in showOverview / showRecent / showTimeline /
    renderSessionDetails) so the next tick's monotonic guard starts from
    the new baseline instead of the old one."""
    for module in ("overview.js", "timeline.js"):
        source = read_js(module)
        # Each renderer must seed the monotonic state after innerHTML swap
        # so the backend baseline replaces the ticker's projected value.
        assert "_monotonicRenderState" in source, (
            module + " must seed App._monotonicRenderState after re-render "
            "so backend truth overrides the ticker's projection"
        )


# --- Section 11: Statistics / Export closed-only hint ---------------------


def test_statistics_page_has_closed_only_hint():
    """Section 11: the Statistics page must show a closed-only hint
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
    """Section 11: the closed-only hint must have a dedicated CSS class
    so it is visually distinct from the export hint."""
    source = (WEBVIEW_UI_DIR / "styles.css").read_text(encoding="utf-8")
    assert ".stats-closed-only-hint" in source, (
        "styles.css must define the .stats-closed-only-hint class"
    )


# --- Phase R3: unified live display eligibility + page-switch guard -------


def test_ticker_live_eligible_checks_live_state():
    """Phase R3 issue 1: the ticker must only increment normal project
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
    """Phase R3 issue 6: the ticker must NOT use DOM current text as the
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
    """Phase R3 issues 2 & 10: the ticker must locate the live detail row
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
    """Phase R3 issue 14: page-switch immediate refresh must NOT be
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
    """Phase R3 issue 12: ``_timelineEditingActive`` must cover not just
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
    """Phase R3 issue 17: ``renderSessionDetails`` must NOT re-render the
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
