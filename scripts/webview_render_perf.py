"""Windows WebView render performance harness.

Launches a real WebView2 window with a large projection dataset, injects
``performance.mark`` / ``performance.measure`` / ``requestAnimationFrame``
instrumentation via ``evaluate_js``, and collects cold/warm render timings
for Overview, Timeline, and detail.  Windows only; requires WebView2 Runtime.

Outputs a JSON artifact to ``--output`` so baseline-vs-HEAD comparison is
possible.  If WebView2 cannot start, records the failure reason and exits
non-zero — never fakes a successful measurement.  Does NOT modify shipped
frontend files; all instrumentation is injected at runtime via
``window.evaluate_js``.  The runtime is constructed exactly like
``worktrace.webview_main.main()`` with a temp data directory, so the bridge
serves real projection data from a real SQLite database.  Collector startup
is skipped (render measurement only reads persisted data; "not running" is
a valid UI state).

Completion contract
-------------------
Detail measurement waits for an observable completion condition compatible
across baseline and HEAD: (1) the bridge's detail Promise resolved, (2)
detail DOM has at least one ``.summary-item`` row, (3) DOM row count stable
across two consecutive animation frames, (4) no error element or bridge
error present.  HEAD-private internals
(``lastSessionActivitySummaryViewModel``, ``detailsInFlight``, header text)
are diagnostics-only, never completion gates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CI_DIR = _REPO_ROOT / "scripts" / "ci"
for path in (_REPO_ROOT, _CI_DIR):
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

# ---------------------------------------------------------------------------
# Target-root isolation (for baseline-vs-HEAD comparison)
# ---------------------------------------------------------------------------

_DRIVER_VERSION = "3.0"
_WEBVIEW_SCHEMA_VERSION = 2
_EXIT_INPUT_SCHEMA = 2
_EXIT_EXECUTION = 3

# Profile data sizes.  Smoke is for infrastructure validation; realistic is
# the ordinary PR gate; full is the stress-level performance gate.
# ``heavy_session_activity_count`` controls the explicit heavy session in the
# realistic fixture; 0 means no heavy session (used by full/stress).
_PROFILES: dict[str, dict[str, Any]] = {
    # Smoke uses 2 runs so cold/warm split yields at least one warm sample;
    # runs=1 would give zero warm samples and fail "incomplete" in comparison.
    "smoke": {
        "activity_count": 200,
        "runs": 2,
        "heavy_session_activity_count": 12,
    },
    "realistic": {
        "activity_count": 2000,
        "runs": 3,
        "heavy_session_activity_count": 80,
    },
    "full": {
        "activity_count": 20000,
        "runs": 3,
        "heavy_session_activity_count": 0,
    },
}

# Timeout profiles are "can it complete" execution guards, NOT performance
# gates: generous enough that a healthy UI never hits them, narrow enough to
# report a hung UI with a specific failure category.  Payload timeout waits
# for the bridge Promise to settle; DOM timeout waits for rows AFTER that.
_TIMEOUT_PROFILES: dict[str, dict[str, int]] = {
    "smoke": {
        "overview_payload_timeout_ms": 15000,
        "timeline_payload_timeout_ms": 30000,
        "detail_payload_timeout_ms": 30000,
        "detail_dom_timeout_ms": 10000,
    },
    "realistic": {
        "overview_payload_timeout_ms": 20000,
        "timeline_payload_timeout_ms": 45000,
        "detail_payload_timeout_ms": 45000,
        "detail_dom_timeout_ms": 10000,
    },
    "full": {
        "overview_payload_timeout_ms": 30000,
        "timeline_payload_timeout_ms": 60000,
        "detail_payload_timeout_ms": 60000,
        "detail_dom_timeout_ms": 10000,
    },
}

# Startup allowance (ms) for WebView2 initialization, frontend app ready,
# and pywebview bridge handshake.  Used to compute the Python outer timeout.
_STARTUP_ALLOWANCE_SECONDS = 30.0
# Cleanup margin (seconds) between the last run's budget expiry and the
# Python outer timeout — covers window.destroy() and result polling overhead.
_CLEANUP_MARGIN_SECONDS = 15.0


def _compute_outer_timeout(
    *,
    runs: int,
    profile_name: str,
) -> float:
    """Compute the Python outer timeout for waiting on ``window.__perfResults``.

    The timeout is derived from:
      * startup allowance (WebView2 init + frontend ready + bridge handshake),
      * run count,
      * per-run stage budgets (overview + timeline + detail payload + detail DOM),
      * cleanup margin (window.destroy + polling overhead).

    This replaces the historical fixed 180-second timeout which was unrelated
    to the actual stage budgets and could either cut off a legitimate slow
    run or hang forever on a dead UI.
    """
    timeouts = _TIMEOUT_PROFILES[profile_name]
    per_run_budget_ms = (
        timeouts["overview_payload_timeout_ms"]
        + timeouts["timeline_payload_timeout_ms"]
        + timeouts["detail_payload_timeout_ms"]
        + timeouts["detail_dom_timeout_ms"]
    )
    # Add 5s per run for non-budget overhead (marks, measures, sleep between runs).
    per_run_overhead_ms = 5000
    total_run_budget_seconds = (
        runs * (per_run_budget_ms + per_run_overhead_ms) / 1000.0
    )
    return (
        _STARTUP_ALLOWANCE_SECONDS
        + total_run_budget_seconds
        + _CLEANUP_MARGIN_SECONDS
    )


def _setup_target_path(target_root: Path) -> None:
    """Prepend ``target_root`` to ``sys.path`` so ``worktrace.*`` resolves
    to the target revision, not the HEAD workspace.
    """
    target_str = str(target_root)
    cleaned: list[str] = []
    for entry in sys.path:
        if entry == target_str:
            continue
        cleaned.append(entry)
    sys.path = [target_str] + cleaned


def _verify_module_at_target(module_name: str, target_root: Path) -> str:
    """Import ``module_name`` and verify its ``__file__`` is under target_root."""
    try:
        module = __import__(module_name, fromlist=["_"])
    except Exception as exc:
        print(
            f"driver_error: cannot import {module_name} from "
            f"{target_root}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)

    file_attr = getattr(module, "__file__", None)
    if not file_attr:
        print(
            f"driver_error: {module_name} has no __file__ attribute",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)

    resolved = str(Path(file_attr).resolve())
    target_resolved = str(target_root.resolve())
    if not resolved.startswith(target_resolved + os.sep) and resolved != target_resolved:
        print(
            f"driver_error: {module_name} loaded from {resolved}, "
            f"expected under {target_resolved}",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)
    return resolved


# ---------------------------------------------------------------------------
# Revision identity
# ---------------------------------------------------------------------------

def _read_actual_target_revision(target_root: Path) -> str:
    """Return the actual HEAD SHA of the target worktree.

    Runs ``git rev-parse HEAD`` inside ``target_root``.  This is the only
    value used for revision identity comparison — never ``GITHUB_SHA``,
    which can be a merge commit SHA in pull_request workflows.
    """
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(target_root),
            text=True,
            stderr=subprocess.STDOUT,
        )
        return output.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(
            f"driver_error: cannot read actual target revision from "
            f"{target_root}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)


def _verify_revision_identity(
    requested_revision: str,
    target_root: Path,
) -> str:
    """Verify ``requested_revision`` matches the actual target worktree SHA.

    Returns the actual SHA on success.  Raises ``SystemExit(2)`` on mismatch
    so the comparison layer never sees an artifact whose recorded revision
    was guessed instead of verified.
    """
    actual = _read_actual_target_revision(target_root)
    if actual != requested_revision:
        print(
            f"driver_error: requested_revision {requested_revision!r} != "
            f"actual_target_revision {actual!r} (target_root={target_root})",
            file=sys.stderr,
        )
        raise SystemExit(_EXIT_INPUT_SCHEMA)
    return actual


def _wv_fixture_hash(
    activity_count: int,
    *,
    profile: str = "full",
    heavy_session_activity_count: int = 0,
) -> str:
    """Compute a deterministic hash of the WebView benchmark fixture.

    The hash covers the same parameters as the product benchmark fixture
    (via ``benchmark_fixture.fixture_hash``) so cross-driver fixture
    consistency can be audited.  When ``heavy_session_activity_count > 0``
    (smoke and realistic profiles), the realistic-heavy-day spec is used
    so the hash matches the actual fixture built by
    ``_populate_dataset_self_contained``.
    """
    from scripts.ci.benchmark_fixture import (
        DEFAULT_CHUNK_SIZE,
        DEFAULT_DAY_START_SECONDS,
        DEFAULT_REPORT_DATE,
        DEFAULT_SPAN_SECONDS,
        BenchmarkFixtureSpec,
        build_realistic_heavy_day_spec,
        fixture_hash as _fixture_hash,
    )

    if heavy_session_activity_count > 0:
        spec = build_realistic_heavy_day_spec(
            activity_count=activity_count,
            heavy_session_activity_count=heavy_session_activity_count,
        )
    else:
        spec = BenchmarkFixtureSpec(
            report_date=DEFAULT_REPORT_DATE,
            activity_count=activity_count,
            day_start_seconds=DEFAULT_DAY_START_SECONDS,
            span_seconds=DEFAULT_SPAN_SECONDS,
            scenario="webview_render",
            seed=0,
            chunk_size=DEFAULT_CHUNK_SIZE,
            heavy_session_activity_count=heavy_session_activity_count,
        )
    return _fixture_hash(spec)


def _populate_dataset_self_contained(
    activity_count: int,
    *,
    profile: str = "full",
    heavy_session_activity_count: int = 0,
) -> dict[str, Any]:
    """Self-contained fixture builder using the shared benchmark_fixture module.

    Delegates to ``scripts.ci.benchmark_fixture`` so the WebView driver and
    the product benchmark driver share the exact same fixture construction
    code.  When ``heavy_session_activity_count > 0`` (smoke and realistic
    profiles), uses the realistic-heavy-day fixture builder so a
    deterministic heavy session is constructed and the marker is available
    for Timeline-based selection.
    """
    from scripts.ci.benchmark_fixture import (
        DEFAULT_CHUNK_SIZE,
        DEFAULT_DAY_START_SECONDS,
        DEFAULT_REPORT_DATE,
        DEFAULT_SPAN_SECONDS,
        BenchmarkFixtureSpec,
        build_activity_fixture,
        build_realistic_heavy_day_fixture,
        build_realistic_heavy_day_spec,
    )

    if heavy_session_activity_count > 0:
        spec = build_realistic_heavy_day_spec(
            activity_count=activity_count,
            heavy_session_activity_count=heavy_session_activity_count,
        )
        result = build_realistic_heavy_day_fixture(spec=spec)
    else:
        spec = BenchmarkFixtureSpec(
            report_date=DEFAULT_REPORT_DATE,
            activity_count=activity_count,
            day_start_seconds=DEFAULT_DAY_START_SECONDS,
            span_seconds=DEFAULT_SPAN_SECONDS,
            scenario="webview_render",
            seed=0,
            chunk_size=DEFAULT_CHUNK_SIZE,
            heavy_session_activity_count=heavy_session_activity_count,
        )
        result = build_activity_fixture(spec=spec)

    # Scenario isolation contracts — fail-closed on any violation.
    if result.preexisting_activity_count != 0:
        raise RuntimeError(
            f"webview fixture started with preexisting_activity_count="
            f"{result.preexisting_activity_count} (expected 0)"
        )
    if result.inserted_count != result.requested_count:
        raise RuntimeError(
            f"webview fixture inserted {result.inserted_count} activities "
            f"but requested {result.requested_count}"
        )

    return {
        "report_date": result.report_date,
        "activity_count": result.inserted_count,
        "activity_ids": result.activity_ids,
        "anchor_project_id": result.anchor_project_id,
        "other_project_id": result.other_project_id,
        "uncategorized_project_id": result.uncategorized_project_id,
        "fixture_audit": result.to_audit_dict(),
        "heavy_session_activity_count": heavy_session_activity_count,
        "heavy_session_marker": (
            result.heavy_session_marker if heavy_session_activity_count > 0 else ""
        ),
    }


def _check_webview2_available() -> str:
    """Return 'installed', 'missing', or 'unknown'."""
    try:
        from worktrace.webview_ui.runtime_check import detect_webview2_runtime
        return detect_webview2_runtime()
    except Exception as exc:
        return f"detection_error: {exc}"


def _build_paths(data_dir: Path):
    """Construct an :class:`AppPaths` pointing at a temp data directory."""
    from worktrace.config import AppPaths

    return AppPaths(
        base_dir=data_dir,
        data_dir=data_dir / "data",
        log_dir=data_dir / "logs",
        db_path=data_dir / "data" / "worktrace.db",
        log_path=data_dir / "logs" / "worktrace.log",
        export_dir=data_dir / "exports",
    )


# JS injected into WebView2 to measure the real frontend render path via the
# shipping bridge surface (getOverview / getTimeline / getTimelineSessionActivitySummary).
# Completion: detail waits for an external observable condition compatible across
# baseline and HEAD (Promise resolved, DOM rows present and stable, no error).
_MEASURE_JS = r"""
(function () {
    "use strict";
    if (typeof performance === "undefined" || !performance.mark) {
        window.__perfResults = {error: "performance API unavailable"};
        return;
    }
    window.__perfResults = null;

    function mark(name) { performance.mark(name); }
    function measure(name, start, end) {
        try { performance.measure(name, start, end); } catch (e) {}
        var entries = performance.getEntriesByName(name, "measure");
        return entries.length > 0 ? entries[entries.length - 1].duration : 0;
    }

    function onFrame() {
        return new Promise(function (resolve) {
            if (typeof requestAnimationFrame === "function") {
                requestAnimationFrame(function () {
                    requestAnimationFrame(resolve);
                });
            } else {
                setTimeout(resolve, 16);
            }
        });
    }

    function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

    function readDetailDomRows() {
        var dList = document.getElementById("timeline-details-list");
        return dList ? dList.querySelectorAll(".summary-item").length : 0;
    }

    function readDetailHeader() {
        var dHeader = document.getElementById("timeline-details-header");
        return dHeader ? dHeader.textContent.trim() : "";
    }

    function hasExplicitError(headerText) {
        if (!headerText) return null;
        if (headerText.indexOf("失败") !== -1) return "detail_load_failed";
        if (headerText.indexOf("error") !== -1
            || headerText.indexOf("Error") !== -1) return "detail_error_text";
        return null;
    }

    // Two-phase detail completion: payload first, then DOM stabilization.
    // Step 1 waits for the bridge Promise to settle (resolve, reject,
    // ok:false, or timeout).  Step 2 waits for DOM rows to appear and
    // stabilize across two frames AFTER the payload has resolved.
    //
    // Failure categories (replaces the old unified ``detail_timeout``):
    //   detail_payload_timeout  — payload deadline expired without settle
    //   detail_payload_error    — Promise reject, ok:false, or bridge error
    //   detail_dom_empty        — payload resolved but DOM never had rows
    //   detail_dom_unstable     — rows appeared but never stabilized
    //   detail_explicit_error   — page showed an explicit error state
    async function waitForDetailCompletion(
        payloadDeadline, domDeadline, getPayloadState
    ) {
        var payloadState = { resolved: false, error: null };
        var payloadElapsed = 0;
        var payloadSettled = false;
        var domRowsEverNonEmpty = false;
        var stableFrames = 0;
        var firstRowCount = 0;
        var lastDiag = {};
        var domTransitions = [];
        var headerTransitions = [];
        var maxTransitions = 50;

        // ---- Step 1: wait for payload to settle ----
        var payloadStart = Date.now();
        while (Date.now() < payloadDeadline) {
            try {
                payloadState = getPayloadState();
            } catch (e) {
                payloadState = { resolved: false, error: "bridge_exception:" + String(e) };
            }

            // Check for explicit page error (short-circuit).
            var headerText = readDetailHeader();
            var explicitError = hasExplicitError(headerText);
            if (explicitError) {
                return {
                    completed: false,
                    failureCategory: "detail_explicit_error",
                    explicitErrorKind: explicitError,
                    diagnostics: {
                        header_text: headerText,
                        dom_rows: readDetailDomRows(),
                        payload_resolved: false,
                        payload_elapsed_ms: Date.now() - payloadStart
                    },
                    payload_elapsed_ms: Date.now() - payloadStart,
                    dom_transitions: domTransitions,
                    header_transitions: headerTransitions
                };
            }

            if (payloadState.error) {
                // Promise rejected, ok:false, or bridge exception.
                return {
                    completed: false,
                    failureCategory: "detail_payload_error",
                    payloadError: payloadState.error,
                    diagnostics: {
                        header_text: headerText,
                        dom_rows: readDetailDomRows(),
                        payload_resolved: false,
                        payload_elapsed_ms: Date.now() - payloadStart
                    },
                    payload_elapsed_ms: Date.now() - payloadStart,
                    dom_transitions: domTransitions,
                    header_transitions: headerTransitions
                };
            }

            if (payloadState.resolved) {
                payloadSettled = true;
                payloadElapsed = Date.now() - payloadStart;
                break;
            }

            await sleep(10);
        }

        if (!payloadSettled) {
            return {
                completed: false,
                failureCategory: "detail_payload_timeout",
                diagnostics: {
                    header_text: readDetailHeader(),
                    dom_rows: readDetailDomRows(),
                    payload_resolved: false,
                    payload_elapsed_ms: Date.now() - payloadStart
                },
                payload_elapsed_ms: Date.now() - payloadStart,
                dom_transitions: domTransitions,
                header_transitions: headerTransitions
            };
        }

        // ---- Step 2: wait for DOM to be non-empty and stable ----
        var domStart = Date.now();
        var prevHeader = readDetailHeader();
        while (Date.now() < domDeadline) {
            var headerText = readDetailHeader();
            var domRows = readDetailDomRows();
            var explicitError = hasExplicitError(headerText);

            // Track header transitions (diagnostics only).
            if (headerText !== prevHeader && headerTransitions.length < maxTransitions) {
                headerTransitions.push({
                    at_ms: Date.now() - domStart,
                    text: headerText.substring(0, 100)
                });
                prevHeader = headerText;
            }

            // Track DOM row count transitions (diagnostics only).
            if (domRows !== firstRowCount && domTransitions.length < maxTransitions) {
                domTransitions.push({
                    at_ms: Date.now() - domStart,
                    count: domRows
                });
            }

            if (explicitError) {
                return {
                    completed: false,
                    failureCategory: "detail_explicit_error",
                    explicitErrorKind: explicitError,
                    diagnostics: {
                        header_text: headerText,
                        dom_rows: domRows,
                        payload_resolved: true,
                        payload_elapsed_ms: payloadElapsed
                    },
                    payload_elapsed_ms: payloadElapsed,
                    dom_elapsed_ms: Date.now() - domStart,
                    dom_transitions: domTransitions,
                    header_transitions: headerTransitions,
                    stable_frames: stableFrames
                };
            }

            if (domRows > 0) {
                domRowsEverNonEmpty = true;
                if (domRows === firstRowCount) {
                    stableFrames += 1;
                    if (stableFrames >= 2) {
                        return {
                            completed: true,
                            failureCategory: "",
                            diagnostics: {
                                header_text: headerText,
                                dom_rows: domRows,
                                payload_resolved: true,
                                payload_elapsed_ms: payloadElapsed,
                                details_in_flight: 0,
                                view_model_present: false
                            },
                            payload_elapsed_ms: payloadElapsed,
                            dom_elapsed_ms: Date.now() - domStart,
                            dom_transitions: domTransitions,
                            header_transitions: headerTransitions,
                            stable_frames: stableFrames
                        };
                    }
                } else {
                    firstRowCount = domRows;
                    stableFrames = 0;
                }
            }

            // Record diagnostic fields (HEAD-private, never gates).
            var vm = null;
            try {
                vm = window.WorkTraceApp.lastSessionActivitySummaryViewModel;
            } catch (e) { vm = null; }
            var inFlight = 0;
            try {
                inFlight = Object.keys(
                    window.WorkTraceApp.detailsInFlight || {}
                ).length;
            } catch (e) { inFlight = 0; }

            lastDiag = {
                header_text: headerText,
                dom_rows: domRows,
                view_model_present: vm !== null && vm !== undefined,
                details_in_flight: inFlight,
                payload_resolved: true,
                payload_elapsed_ms: payloadElapsed
            };

            await sleep(10);
        }

        // DOM deadline expired — distinguish empty vs unstable.
        var failureCat = domRowsEverNonEmpty
            ? "detail_dom_unstable"
            : "detail_dom_empty";
        return {
            completed: false,
            failureCategory: failureCat,
            diagnostics: lastDiag,
            payload_elapsed_ms: payloadElapsed,
            dom_elapsed_ms: Date.now() - domStart,
            dom_transitions: domTransitions,
            header_transitions: headerTransitions,
            stable_frames: stableFrames
        };
    }

    async function runOnce(label) {
        var App = window.WorkTraceApp;
        var results = { label: label, stages: {} };

        // Reset any prior timeline/detail selection so this run starts
        // clean.  Without this, on the SECOND and subsequent runs
        // App.selectedProjectionInstanceKey is still set from the prior
        // run, and App.showTimeline() auto-triggers loadSessionActivitySummary
        // through the UNWRAPPED bridge (before the detail-instrumentation
        // wrapper is installed).  That in-flight request then deduplicates
        // against the later explicit selectTimelineSession call, so the
        // wrapped bridge method is never invoked and detailPayloadMarked
        // never becomes true — causing a false detail_timeout.
        //
        // resetTimelineReportSelection is a public App method that clears
        // selectedProjectionInstanceKey, the detail view models, and the
        // detail DOM.  This does NOT modify product code; it uses an
        // existing public API to ensure each run's detail measurement
        // is triggered through the instrumented bridge path.
        if (typeof App.resetTimelineReportSelection === "function") {
            App.resetTimelineReportSelection();
        }

        // Overview cold render
        // Set the page context the navigation function would normally set
        // so runtime-envelope compatibility checks accept the payload.
        App.currentPage = "overview";
        mark(label + "_overview_start");
        var overviewBundle = await App.bridge.getOverview();
        mark(label + "_overview_payload");
        if (overviewBundle && overviewBundle.ok !== false) {
            App.showOverview(overviewBundle);
            mark(label + "_overview_rendered");
            await onFrame();
            mark(label + "_overview_first_frame");
            results.stages.overview_payload_ms = measure(
                label + "_overview_payload_ms",
                label + "_overview_start",
                label + "_overview_payload"
            );
            results.stages.overview_render_ms = measure(
                label + "_overview_render_ms",
                label + "_overview_payload",
                label + "_overview_first_frame"
            );
            results.stages.overview_total_ms = measure(
                label + "_overview_total_ms",
                label + "_overview_start",
                label + "_overview_first_frame"
            );
            results.overview_report_date = overviewBundle.report_date || "";
        } else {
            results.stages.overview_error = (overviewBundle && overviewBundle.error) || "unknown";
        }

        // Timeline render
        // Switch the page context to timeline so runtime-envelope
        // compatibility checks accept the timeline and detail payloads.
        App.currentPage = "timeline";
        // Prefer the overview's report_date; fall back to the injected
        // benchmark date (window.__perfReportDate) and finally today.
        var reportDate = results.overview_report_date
            || window.__perfReportDate
            || new Date().toISOString().slice(0, 10);
        mark(label + "_timeline_start");
        var timelineData = await App.bridge.getTimeline(reportDate);
        mark(label + "_timeline_data");
        if (timelineData && timelineData.ok !== false) {
            App.showTimeline(timelineData);
            mark(label + "_timeline_rendered");
            await onFrame();
            mark(label + "_timeline_first_frame");
            results.stages.timeline_payload_ms = measure(
                label + "_timeline_payload_ms",
                label + "_timeline_start",
                label + "_timeline_data"
            );
            results.stages.timeline_render_ms = measure(
                label + "_timeline_render_ms",
                label + "_timeline_data",
                label + "_timeline_first_frame"
            );
            results.stages.timeline_total_ms = measure(
                label + "_timeline_total_ms",
                label + "_timeline_start",
                label + "_timeline_first_frame"
            );
            results.timeline_entry_count = Array.isArray(timelineData.entries)
                ? timelineData.entries.length : 0;
        } else {
            results.stages.timeline_error = (timelineData && timelineData.error) || "unknown";
        }

        // Detail open via real user selection path.
        // Instead of selecting the first Timeline item, select the HEAVY
        // session via public payload fields so the Detail measurement
        // exercises the heavy-detail load path.  Selection priority:
        //   1. Deterministic marker — entry whose display_description
        //      contains the heavy session marker (e.g. "BenchHeavySession").
        //   2. Max event_count — entry with the highest activity count.
        //   3. Max duration_seconds — entry with the longest duration.
        // The selector never uses HEAD-private ViewModel fields and never
        // calls Detail APIs for all sessions (no pre-warm traversal).
        var heavyCfg = window.__perfHeavySessionConfig || {};
        var heavyMarker = heavyCfg.marker || "";
        var expectedHeavyCount = heavyCfg.expected_activity_count || 0;
        var minHeavyThreshold = heavyCfg.min_heavy_threshold || 0;

        var timelineEntries = (timelineData && Array.isArray(timelineData.entries))
            ? timelineData.entries : [];
        var selectedEntry = null;
        var selectorReason = "none";

        // Priority 1: deterministic marker in display_description.
        if (heavyMarker) {
            for (var ei = 0; ei < timelineEntries.length; ei++) {
                var desc = String(timelineEntries[ei].display_description || "");
                if (desc.indexOf(heavyMarker) !== -1) {
                    selectedEntry = timelineEntries[ei];
                    selectorReason = "marker";
                    break;
                }
            }
        }

        // Priority 2: max event_count.
        if (!selectedEntry) {
            var maxEventCount = -1;
            for (var ei2 = 0; ei2 < timelineEntries.length; ei2++) {
                var ec = parseInt(timelineEntries[ei2].event_count, 10) || 0;
                if (ec > maxEventCount) {
                    maxEventCount = ec;
                    selectedEntry = timelineEntries[ei2];
                    selectorReason = "event_count";
                }
            }
        }

        // Priority 3: max duration_seconds.
        if (!selectedEntry) {
            var maxDuration = -1;
            for (var ei3 = 0; ei3 < timelineEntries.length; ei3++) {
                var dur = parseInt(timelineEntries[ei3].duration_seconds, 10) || 0;
                if (dur > maxDuration) {
                    maxDuration = dur;
                    selectedEntry = timelineEntries[ei3];
                    selectorReason = "duration";
                }
            }
        }

        var detailKey = selectedEntry
            ? String(selectedEntry.projection_instance_key || "")
            : "";
        var selectedEventCount = selectedEntry
            ? (parseInt(selectedEntry.event_count, 10) || 0) : 0;
        var selectedDuration = selectedEntry
            ? (parseInt(selectedEntry.duration_seconds, 10) || 0) : 0;

        // Record selector metadata for artifact audit.
        results.selected_detail_key = detailKey;
        results.selected_detail_selector_reason = selectorReason;
        results.selected_detail_expected_activity_count = expectedHeavyCount;
        results.selected_detail_duration_seconds = selectedDuration;
        results.selected_detail_marker = heavyMarker;
        results.selected_detail_source_event_count = selectedEventCount;
        results.selected_detail_expected_count_source = (
            expectedHeavyCount > 0 ? "fixture_metadata" : "timeline_payload"
        );
        // Determine if the selected session qualifies as heavy.
        results.selected_detail_is_heavy = (
            selectedEventCount >= minHeavyThreshold
        );

        if (detailKey) {
            mark(label + "_detail_start");

            // Instrument the bridge to capture the payload state (resolved,
            // rejected, or ok:false) without modifying production semantics.
            // The bridge object is frozen, but App.bridge is reassignable,
            // so we swap in a shallow copy that wraps the detail method.
            var originalBridge = App.bridge;
            var wrappedBridge = {};
            var bridgeKeys = Object.keys(originalBridge);
            for (var bi = 0; bi < bridgeKeys.length; bi++) {
                wrappedBridge[bridgeKeys[bi]] = originalBridge[bridgeKeys[bi]];
            }
            var detailPayloadState = { resolved: false, error: null };
            wrappedBridge.getTimelineSessionActivitySummary = function () {
                var args = Array.prototype.slice.call(arguments);
                return originalBridge.getTimelineSessionActivitySummary
                    .apply(originalBridge, args)
                    .then(function (result) {
                        if (!detailPayloadState.resolved) {
                            mark(label + "_detail_payload");
                        }
                        if (result && result.ok === false) {
                            detailPayloadState.error =
                                "ok_false:" + (result.error || "unknown");
                        } else {
                            detailPayloadState.resolved = true;
                        }
                        return result;
                    })
                    .catch(function (err) {
                        detailPayloadState.error = "rejected:" + String(err);
                        throw err;
                    });
            };
            App.bridge = wrappedBridge;

            // Trigger real selection through the public entry point.
            try {
                App.selectTimelineSession(detailKey, App.currentSessions || []);
            } catch (selErr) {
                App.bridge = originalBridge;
                results.stages.detail_error = "select_exception:" + String(selErr);
            }

            if (!results.stages.detail_error) {
                // Two-phase completion: payload first, then DOM stabilization.
                // Timeouts come from window.__perfTimeoutConfig (injected by
                // Python based on the profile); they are execution guards,
                // NOT performance gates.
                var tcfg = window.__perfTimeoutConfig || {};
                var payloadTimeoutMs = tcfg.detail_payload_timeout_ms || 60000;
                var domTimeoutMs = tcfg.detail_dom_timeout_ms || 10000;
                var now = Date.now();
                var payloadDeadline = now + payloadTimeoutMs;
                var domDeadline = payloadDeadline + domTimeoutMs;

                var completionState = await waitForDetailCompletion(
                    payloadDeadline,
                    domDeadline,
                    function () { return detailPayloadState; }
                );

                // Restore the original bridge before measuring.
                App.bridge = originalBridge;

                if (completionState.completed) {
                    await onFrame();
                    mark(label + "_detail_first_frame");
                    results.stages.detail_payload_ms = measure(
                        label + "_detail_payload_ms",
                        label + "_detail_start",
                        label + "_detail_payload"
                    );
                    results.stages.detail_render_ms = measure(
                        label + "_detail_render_ms",
                        label + "_detail_payload",
                        label + "_detail_first_frame"
                    );
                    results.stages.detail_total_ms = measure(
                        label + "_detail_total_ms",
                        label + "_detail_start",
                        label + "_detail_first_frame"
                    );

                    // Diagnostic fields — recorded but never used as gates.
                    var dVm = null;
                    try {
                        dVm = window.WorkTraceApp.lastSessionActivitySummaryViewModel;
                    } catch (e) { dVm = null; }
                    results.detail_row_count = (dVm && dVm.summary_rows)
                        ? dVm.summary_rows.length : 0;
                    results.detail_dom_row_count = completionState.diagnostics.dom_rows || 0;
                    results.detail_header_text = completionState.diagnostics.header_text || "";
                    results.detail_view_model_present = completionState.diagnostics.view_model_present || false;
                    results.detail_in_flight = completionState.diagnostics.details_in_flight || 0;
                    results.detail_payload_resolved = detailPayloadState.resolved;
                    results.detail_payload_elapsed_ms = completionState.payload_elapsed_ms || 0;
                    results.detail_dom_elapsed_ms = completionState.dom_elapsed_ms || 0;
                    results.detail_dom_transitions = completionState.dom_transitions || [];
                    results.detail_header_transitions = completionState.header_transitions || [];
                    results.detail_stable_frames = completionState.stable_frames || 0;
                    results.detail_configured_payload_deadline_ms = payloadTimeoutMs;
                    results.detail_configured_dom_deadline_ms = domTimeoutMs;

                    // Workload validity fields.  ``detail_source_activity_count``
                    // is the event_count from the Timeline entry (public
                    // payload), proving the underlying session is heavy.
                    // ``detail_summary_row_count`` is the ViewModel row count
                    // (may aggregate multiple activities into one summary row).
                    results.detail_source_activity_count = selectedEventCount;
                    results.detail_summary_row_count = results.detail_row_count;

                    // Workload validity gates (distinct from payload/DOM
                    // completion gates).  These prove the measured Detail is
                    // the heavy session, not a lightweight one.
                    if (!results.selected_detail_is_heavy) {
                        results.stages.detail_error = "detail_not_heavy";
                    } else if (results.detail_source_activity_count
                               < minHeavyThreshold) {
                        results.stages.detail_error =
                            "detail_row_count_below_expected";
                    } else if (results.detail_dom_row_count > 0
                               && results.detail_row_count
                               !== results.detail_dom_row_count) {
                        results.stages.detail_error = "detail_row_count_mismatch";
                    }

                    // Realism assertion: ViewModel and DOM must have at
                    // least one row.
                    if (results.detail_row_count === 0
                        && !results.stages.detail_error) {
                        results.stages.detail_error = "detail_row_count_zero";
                    }
                    if (results.detail_dom_row_count === 0
                        && !results.stages.detail_error) {
                        results.stages.detail_error = "detail_dom_row_count_zero";
                    }
                } else {
                    results.stages.detail_error = completionState.failureCategory
                        || "detail_payload_timeout";
                    results.detail_header_text = completionState.diagnostics.header_text || "";
                    results.detail_dom_row_count = completionState.diagnostics.dom_rows || 0;
                    results.detail_view_model_present = completionState.diagnostics.view_model_present || false;
                    results.detail_in_flight = completionState.diagnostics.details_in_flight || 0;
                    results.detail_payload_resolved = detailPayloadState.resolved;
                    results.detail_payload_elapsed_ms = completionState.payload_elapsed_ms || 0;
                    results.detail_dom_elapsed_ms = completionState.dom_elapsed_ms || 0;
                    results.detail_dom_transitions = completionState.dom_transitions || [];
                    results.detail_header_transitions = completionState.header_transitions || [];
                    results.detail_stable_frames = completionState.stable_frames || 0;
                    results.detail_configured_payload_deadline_ms = payloadTimeoutMs;
                    results.detail_configured_dom_deadline_ms = domTimeoutMs;
                    if (completionState.payloadError) {
                        results.detail_payload_error = completionState.payloadError;
                    }
                    if (completionState.explicitErrorKind) {
                        results.detail_explicit_error_kind = completionState.explicitErrorKind;
                    }
                }
            }
        } else {
            results.stages.detail_error = "no_heavy_session_found";
        }

        // Warm-cache overview re-render
        App.currentPage = "overview";
        mark(label + "_warm_overview_start");
        var warmOverview = await App.bridge.getOverview();
        mark(label + "_warm_overview_payload");
        if (warmOverview && warmOverview.ok !== false) {
            App.showOverview(warmOverview);
            await onFrame();
            mark(label + "_warm_overview_first_frame");
            results.stages.warm_overview_total_ms = measure(
                label + "_warm_overview_total_ms",
                label + "_warm_overview_start",
                label + "_warm_overview_first_frame"
            );
        }

        return results;
    }

    async function main() {
        try {
            // Wait for the frontend app object and pywebview bridge to be ready.
            // The page's IIFE modules set window.WorkTraceApp on load; the
            // pywebview api object is injected separately.  Poll for both so
            // the measurement never races frontend initialization.
            var retries = 0;
            while (retries < 200) {
                if (window.WorkTraceApp
                    && window.WorkTraceApp.bridge
                    && window.pywebview
                    && window.pywebview.api) {
                    break;
                }
                await sleep(100);
                retries++;
            }
            if (!window.WorkTraceApp || !window.WorkTraceApp.bridge) {
                window.__perfResults = {error: "WorkTraceApp not ready after timeout"};
                return;
            }
            if (!window.pywebview || !window.pywebview.api) {
                window.__perfResults = {error: "pywebview bridge not ready after timeout"};
                return;
            }

            var allRuns = [];
            var runCount = window.__perfRunCount || 3;
            for (var run = 0; run < runCount; run++) {
                performance.clearMarks();
                performance.clearMeasures();
                var runResults = await runOnce("run" + run);
                allRuns.push(runResults);
                await sleep(200);
            }
            window.__perfResults = { runs: allRuns, status: "ok" };
        } catch (e) {
            window.__perfResults = { error: String(e), stack: e.stack || "" };
        }
    }

    main();
})();
"""


def _run_harness(
    activity_count: int,
    runs: int,
    *,
    target_root: Path | None = None,
    profile_name: str = "full",
    heavy_session_activity_count: int = 0,
) -> dict[str, Any]:
    """Launch WebView2, inject measurement JS, collect results.

    When ``target_root`` is specified, the harness uses the shared
    self-contained fixture builder (no ``tests.support`` dependency) and
    loads the frontend from the target root, enabling baseline-vs-HEAD
    comparison.

    ``profile_name`` selects the timeout profile (``smoke`` or ``full``)
    used both for the JS-side per-stage deadlines and the Python-side
    outer timeout.  The outer timeout is computed from the stage budgets
    via :func:`_compute_outer_timeout` so it is always consistent with
    the JS deadlines.

    ``heavy_session_activity_count`` controls the explicit heavy session
    in the realistic fixture.  When > 0, the harness injects a
    ``__perfHeavySessionConfig`` object so the JS selector can identify
    the heavy session via the public Timeline payload.
    """
    try:
        import webview
    except ImportError as exc:
        return {
            "status": "failed",
            "failure_reason": f"pywebview import failed: {exc}",
            "failure_category": "missing_dependency",
        }

    runtime_status = _check_webview2_available()
    if runtime_status == "missing":
        return {
            "status": "failed",
            "failure_reason": "WebView2 Runtime is missing",
            "failure_category": "missing_runtime",
            "runtime_detection": runtime_status,
        }

    from worktrace.config import ensure_directories
    from worktrace.runtime.app_runtime import AppRuntime
    from worktrace.runtime.application_services import build_application_services
    from worktrace.webview_ui.bridge import WebViewBridge

    # ignore_cleanup_errors=True: WebView2 and the SQLite pool may hold file
    # handles briefly after shutdown on Windows, which would otherwise mask
    # the real measurement result with a PermissionError during temp dir
    # removal.  The OS reclaims the temp directory later.
    with tempfile.TemporaryDirectory(
        prefix="webview_perf_",
        ignore_cleanup_errors=True,
    ) as tmpdir:
        data_dir = Path(tmpdir)
        paths = _build_paths(data_dir)
        ensure_directories(paths)

        runtime = AppRuntime(paths)
        if runtime.initialize() is False:
            return {
                "status": "failed",
                "failure_reason": (
                    "AppRuntime.initialize() failed (single-instance lock not "
                    "acquired — another WorkTrace instance may be running)"
                ),
                "failure_category": "runtime_init_error",
                "runtime_detection": runtime_status,
            }

        dataset_info: dict[str, Any] = {}
        try:
            try:
                # Both target_root and HEAD paths use the shared self-contained
                # fixture builder so baseline and HEAD use the exact same code,
                # without depending on test-only modules that may not exist in
                # the baseline worktree.
                dataset_info = _populate_dataset_self_contained(
                    activity_count,
                    profile=profile_name,
                    heavy_session_activity_count=heavy_session_activity_count,
                )
            except Exception as exc:
                return {
                    "status": "failed",
                    "failure_reason": f"dataset build failed: {exc}",
                    "failure_category": "dataset_build_error",
                    "runtime_detection": runtime_status,
                }

            services = build_application_services(runtime)
            bridge = WebViewBridge(services)

            if target_root is not None:
                index_path = target_root / "worktrace" / "webview_ui" / "index_fd_work_v5.html"
            else:
                index_path = _REPO_ROOT / "worktrace" / "webview_ui" / "index_fd_work_v5.html"

            results_holder: dict[str, Any] = {"results": None, "error": None}

            def on_loaded(window):
                """Inject measurement JS when the window finishes loading."""
                try:
                    # Tell the JS how many runs to execute and which report
                    # date to query (the benchmark dataset is inserted on a
                    # fixed date, not today).
                    report_date = str(dataset_info.get("report_date", ""))[:10]
                    # Inject the timeout config so JS-side per-stage deadlines
                    # match the Python outer budget.  These are "can it complete"
                    # execution guards, NOT performance gates — generous enough
                    # that a correctly-functioning UI never hits them.
                    timeout_cfg = _TIMEOUT_PROFILES[profile_name]
                    # Inject the heavy session config so the JS selector can
                    # identify the heavy session via the public Timeline
                    # payload.  The marker and expected count are benchmark-
                    # only metadata; they do not leak into production logic.
                    heavy_cfg = {
                        "expected_activity_count": heavy_session_activity_count,
                        "marker": (
                            dataset_info.get("heavy_session_marker") or ""
                        ),
                        "min_heavy_threshold": (
                            50 if heavy_session_activity_count >= 50
                            else max(1, heavy_session_activity_count // 2)
                        ),
                    }
                    window.evaluate_js(
                        f"window.__perfRunCount = {int(runs)};"
                        f" window.__perfReportDate = {json.dumps(report_date)};"
                        f" window.__perfTimeoutConfig = {json.dumps(timeout_cfg)};"
                        f" window.__perfHeavySessionConfig = {json.dumps(heavy_cfg)};"
                    )
                    # Inject the measurement script.
                    window.evaluate_js(_MEASURE_JS)

                    # Poll for results (the JS runs async).  The outer
                    # timeout is computed from the per-stage budgets so it
                    # is always consistent with the JS deadlines — never a
                    # fixed value unrelated to the actual stage budgets.
                    outer_timeout = _compute_outer_timeout(
                        runs=runs, profile_name=profile_name
                    )
                    deadline = time.monotonic() + outer_timeout
                    while time.monotonic() < deadline:
                        raw = window.evaluate_js("window.__perfResults")
                        if raw is not None and raw != "null":
                            results_holder["results"] = raw
                            break
                        time.sleep(0.5)

                    if results_holder["results"] is None:
                        results_holder["error"] = (
                            "timed out waiting for window.__perfResults"
                        )
                except Exception as exc:
                    # ObjectDisposedException after window.destroy() is a cleanup-stage
                    # side effect, not the primary failure.  Preserve any real measurement
                    # failure; only record the cleanup error as a diagnostic.
                    exc_name = type(exc).__name__
                    if "ObjectDisposed" in exc_name or "disposed" in str(exc).lower():
                        if results_holder["error"] is None:
                            results_holder["cleanup_diagnostic"] = str(exc)
                    else:
                        results_holder["error"] = f"evaluation failed: {exc}"
                finally:
                    try:
                        window.destroy()
                    except Exception:
                        pass

            try:
                window = webview.create_window(
                    title="WorkTrace Perf Harness",
                    url=str(index_path),
                    js_api=bridge.shipping_api,
                    width=1080,
                    height=720,
                    min_size=(800, 540),
                )
                window.events.loaded += on_loaded
                webview.start()
            except Exception as exc:
                return {
                    "status": "failed",
                    "failure_reason": f"webview.start failed: {exc}",
                    "failure_category": "webview_start_error",
                    "runtime_detection": runtime_status,
                }
        finally:
            try:
                runtime.shutdown()
            except Exception:
                pass

    if results_holder["error"]:
        return {
            "status": "failed",
            "failure_reason": results_holder["error"],
            "failure_category": "measurement_timeout",
            "runtime_detection": runtime_status,
        }

    raw_results = results_holder["results"]
    # evaluate_js returns a JSON string or a Python object depending on version.
    if isinstance(raw_results, str):
        try:
            parsed = json.loads(raw_results)
        except json.JSONDecodeError:
            return {
                "status": "failed",
                "failure_reason": f"unparseable JS results: {raw_results[:200]}",
                "failure_category": "parse_error",
            }
    else:
        parsed = raw_results

    if parsed.get("error"):
        return {
            "status": "failed",
            "failure_reason": f"JS error: {parsed['error']}",
            "failure_category": "js_error",
            "js_stack": parsed.get("stack", ""),
            "runtime_detection": runtime_status,
        }

    runs_data = parsed.get("runs", [])

    # Enforce realism assertions on every run.  A run with ``detail_error``
    # or missing detail payload means the real Detail render path did not
    # complete, so the harness must report failure — never mask it with
    # ``status: ok``.
    detail_failures: list[str] = []
    for run in runs_data:
        stages = run.get("stages", {}) if isinstance(run, dict) else {}
        detail_error = stages.get("detail_error")
        if detail_error:
            detail_failures.append(
                f"{run.get('label', '?')}: {detail_error}"
            )
        elif "detail_payload_ms" not in stages:
            detail_failures.append(
                f"{run.get('label', '?')}: detail_payload_ms missing"
            )

    if detail_failures:
        return {
            "status": "failed",
            "failure_reason": (
                "Detail render did not complete in one or more runs: "
                + "; ".join(detail_failures)
            ),
            "failure_category": "detail_render_failure",
            "runtime_detection": runtime_status,
            "dataset": {
                "activity_count": dataset_info.get("activity_count", activity_count),
                "report_date": dataset_info.get("report_date", ""),
            },
            "runs": runs_data,
        }

    return {
        "status": "ok",
        "runtime_detection": runtime_status,
        "dataset": {
            "activity_count": dataset_info.get("activity_count", activity_count),
            "report_date": dataset_info.get("report_date", ""),
            "fixture_audit": dataset_info.get("fixture_audit", {}),
            "heavy_session_activity_count": dataset_info.get(
                "heavy_session_activity_count", 0
            ),
            "heavy_session_marker": dataset_info.get("heavy_session_marker", ""),
        },
        "runs": runs_data,
    }


def _stage_medians(run: dict[str, Any]) -> dict[str, float]:
    """Return the numeric stages for a single run."""
    out: dict[str, float] = {}
    for name, value in run.get("stages", {}).items():
        if isinstance(value, (int, float)):
            out[name] = float(value)
    return out


def _median_over_runs(runs: list[dict[str, Any]]) -> dict[str, float]:
    """Compute per-stage medians across the supplied runs."""
    stages: dict[str, list[float]] = {}
    for run in runs:
        for name, value in _stage_medians(run).items():
            stages.setdefault(name, []).append(value)
    return {name: statistics.median(values) for name, values in stages.items() if values}


def _build_cold_warm_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Split runs into cold (run 0) and warm (runs 1..N) summaries.

    The first run inside a fresh WebView process pays cold-cache costs that
    subsequent runs do not, so reporting a single overall median would mask
    the cold-start behaviour.  We expose the cold run as-is and compute a
    median over the remaining warm runs.
    """
    if not runs:
        return {}

    cold_run = runs[0]
    warm_runs = runs[1:]

    cold = {
        "overview": {
            "payload_ms": cold_run.get("stages", {}).get("overview_payload_ms"),
            "render_ms": cold_run.get("stages", {}).get("overview_render_ms"),
            "total_ms": cold_run.get("stages", {}).get("overview_total_ms"),
        },
        "timeline": {
            "payload_ms": cold_run.get("stages", {}).get("timeline_payload_ms"),
            "render_ms": cold_run.get("stages", {}).get("timeline_render_ms"),
            "total_ms": cold_run.get("stages", {}).get("timeline_total_ms"),
        },
        "detail": {
            "payload_ms": cold_run.get("stages", {}).get("detail_payload_ms"),
            "render_ms": cold_run.get("stages", {}).get("detail_render_ms"),
            "total_ms": cold_run.get("stages", {}).get("detail_total_ms"),
            "row_count": cold_run.get("detail_row_count", 0),
            "dom_row_count": cold_run.get("detail_dom_row_count", 0),
            "header_text": cold_run.get("detail_header_text", ""),
            "view_model_present": cold_run.get("detail_view_model_present", False),
            "in_flight": cold_run.get("detail_in_flight", 0),
            "payload_resolved": cold_run.get("detail_payload_resolved", False),
            "selected_detail_key": cold_run.get("selected_detail_key", ""),
            "selected_detail_selector_reason": cold_run.get("selected_detail_selector_reason", ""),
            "selected_detail_is_heavy": cold_run.get("selected_detail_is_heavy", False),
            "selected_detail_source_event_count": cold_run.get("selected_detail_source_event_count", 0),
            "selected_detail_expected_activity_count": cold_run.get("selected_detail_expected_activity_count", 0),
            "source_activity_count": cold_run.get("detail_source_activity_count", 0),
            "summary_row_count": cold_run.get("detail_summary_row_count", 0),
        },
    }

    warm_median = _median_over_runs(warm_runs)
    warm = {
        "run_count": len(warm_runs),
        "median": {
            "overview": {
                "payload_ms": warm_median.get("overview_payload_ms"),
                "render_ms": warm_median.get("overview_render_ms"),
                "total_ms": warm_median.get("overview_total_ms"),
            },
            "timeline": {
                "payload_ms": warm_median.get("timeline_payload_ms"),
                "render_ms": warm_median.get("timeline_render_ms"),
                "total_ms": warm_median.get("timeline_total_ms"),
            },
            "detail": {
                "payload_ms": warm_median.get("detail_payload_ms"),
                "render_ms": warm_median.get("detail_render_ms"),
                "total_ms": warm_median.get("detail_total_ms"),
            },
        },
    }

    return {"cold": cold, "warm": warm}


def _extract_webview_metrics(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Extract the 4 gated WebView metrics from raw runs.

    Metrics:
      * ``cold_timeline_seconds`` — cold run (run 0) timeline total.
      * ``warm_timeline_seconds`` — median of warm runs (1..N) timeline total.
      * ``detail_payload_seconds`` — median of all runs' detail payload.
      * ``detail_total_seconds`` — median of all runs' detail total.

    Each metric has ``samples_seconds`` and ``median_seconds``.
    """
    if not runs:
        raise ValueError("no runs to extract metrics from")

    cold_run = runs[0]
    warm_runs = runs[1:]

    def _stage_ms(run: dict[str, Any], name: str) -> float | None:
        val = run.get("stages", {}).get(name)
        if isinstance(val, (int, float)):
            return float(val) / 1000.0
        return None

    # cold_timeline_seconds: single sample from the cold run.
    cold_timeline = _stage_ms(cold_run, "timeline_total_ms")
    cold_timeline_samples = [cold_timeline] if cold_timeline is not None else []

    # warm_timeline_seconds: samples from warm runs.
    warm_timeline_samples = [
        s for s in (_stage_ms(r, "timeline_total_ms") for r in warm_runs)
        if s is not None
    ]

    # detail_payload_seconds and detail_total_seconds: all runs.
    detail_payload_samples = [
        s for s in (_stage_ms(r, "detail_payload_ms") for r in runs)
        if s is not None
    ]
    detail_total_samples = [
        s for s in (_stage_ms(r, "detail_total_ms") for r in runs)
        if s is not None
    ]

    def _metric(samples: list[float]) -> dict[str, Any]:
        return {
            "samples_seconds": [round(s, 6) for s in samples],
            "median_seconds": round(statistics.median(samples), 6) if samples else 0.0,
        }

    return {
        "cold_timeline_seconds": _metric(cold_timeline_samples),
        "warm_timeline_seconds": _metric(warm_timeline_samples),
        "detail_payload_seconds": _metric(detail_payload_samples),
        "detail_total_seconds": _metric(detail_total_samples),
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to ``path`` atomically via temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _runner_metadata() -> dict[str, Any]:
    """Collect honest runner metadata from the GitHub Actions environment.

    Only reports ``execution_environment = "local"`` when not running on
    GitHub Actions.  On GitHub Actions, exposes the real runner env vars
    so the artifact cannot mislabel a hosted runner as "local".
    """
    on_github = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    if not on_github:
        return {"execution_environment": "local"}

    return {
        "execution_environment": "github_actions",
        "github_sha": os.environ.get("GITHUB_SHA") or None,
        "github_run_id": os.environ.get("GITHUB_RUN_ID") or None,
        "runner_os": os.environ.get("RUNNER_OS") or None,
        "runner_arch": os.environ.get("RUNNER_ARCH") or None,
        "runner_image": os.environ.get("ImageOS") or None,
        "runner_image_version": os.environ.get("ImageVersion") or None,
    }


def _resolve_requested_revision(args: argparse.Namespace) -> str:
    """Resolve the requested revision SHA for the artifact.

    When ``--target-root`` is set, the requested revision must be supplied
    via ``--revision`` and is verified against the actual target worktree
    HEAD.  When ``--target-root`` is not set (local smoke), the current
    workspace HEAD is used as a diagnostic-only value.
    """
    if args.target_root is not None:
        if not args.revision:
            print(
                "driver_error: --revision is required when --target-root is set",
                file=sys.stderr,
            )
            raise SystemExit(_EXIT_INPUT_SCHEMA)
        return args.revision
    # Local smoke: record the workspace HEAD as a diagnostic.  Comparison
    # is only meaningful when --target-root is set, so this value is not
    # used for cross-revision identity checks.
    return _get_git_sha()


def _get_git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_REPO_ROOT),
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="WebView2 render performance harness"
    )
    parser.add_argument(
        "--activity-count",
        type=int,
        default=None,
        help=(
            "Override the activity count for the chosen profile.  When "
            "provided, takes precedence over --profile's activity count."
        ),
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=None,
        help=(
            "Override the run count for the chosen profile.  When provided, "
            "takes precedence over --profile's run count."
        ),
    )
    parser.add_argument(
        "--profile",
        choices=("smoke", "realistic", "full"),
        default="full",
        help=(
            "smoke: small data sizes for infrastructure validation. "
            "realistic: ordinary PR gate data sizes. "
            "full: stress-level data sizes for the performance gate (default)."
        ),
    )
    parser.add_argument(
        "--target-root",
        type=Path,
        default=None,
        help=(
            "Path to the target revision's worktree root for baseline-vs-HEAD "
            "comparison.  When set, the harness isolates imports to the target "
            "root and uses the shared self-contained fixture builder."
        ),
    )
    parser.add_argument(
        "--revision",
        default=None,
        help=(
            "Git SHA of the target revision (recorded in output for audit). "
            "Required when --target-root is set."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Path to write the structured JSON result artifact.  When set, "
            "the output uses the comparable schema (schema_version, "
            "driver_version, metrics) for baseline-vs-HEAD comparison."
        ),
    )
    args = parser.parse_args()

    profile_cfg = _PROFILES[args.profile]
    activity_count = (
        args.activity_count if args.activity_count is not None
        else profile_cfg["activity_count"]
    )
    runs = (
        args.runs if args.runs is not None
        else profile_cfg["runs"]
    )
    heavy_session_activity_count = profile_cfg.get("heavy_session_activity_count", 0)

    target_root: Path | None = None
    actual_revision: str | None = None
    requested_revision = _resolve_requested_revision(args)
    if args.target_root is not None:
        target_root = args.target_root.resolve()
        if not target_root.is_dir():
            print(
                f"driver_error: --target-root does not exist: {target_root}",
                file=sys.stderr,
            )
            return _EXIT_INPUT_SCHEMA
        # Set up target-root isolation so worktrace.* imports resolve to the
        # target revision, not the HEAD workspace.
        _setup_target_path(target_root)
        _verify_module_at_target(
            "worktrace.services.report_projection_snapshot_service", target_root
        )
        actual_revision = _verify_revision_identity(
            requested_revision, target_root
        )
        print(f"verified: target root isolated to {target_root}")
        print(f"verified: actual target revision = {actual_revision}")

    result = _run_harness(
        activity_count,
        runs,
        target_root=target_root,
        profile_name=args.profile,
        heavy_session_activity_count=heavy_session_activity_count,
    )

    runner_meta = _runner_metadata()
    runs_data = result.get("runs", []) if result["status"] == "ok" else result.get("runs", [])

    # ---- Structured output (for baseline-vs-HEAD comparison) ----
    if args.output is not None:
        payload: dict[str, Any] = {
            "schema_version": _WEBVIEW_SCHEMA_VERSION,
            "driver_version": _DRIVER_VERSION,
            "requested_revision": requested_revision,
            "actual_target_revision": actual_revision,
            "github_workflow_sha": os.environ.get("GITHUB_SHA"),
            "target_root": str(target_root) if target_root else "",
            "fixture_hash": _wv_fixture_hash(
                activity_count,
                profile=args.profile,
                heavy_session_activity_count=heavy_session_activity_count,
            ),
            "python_version": sys.version,
            "platform": platform.platform(),
            "runner_metadata": runner_meta,
            "webview2_runtime": result.get("runtime_detection", "unknown"),
            "activity_count": activity_count,
            "runs_requested": runs,
            "profile": args.profile,
            "status": result["status"],
        }

        # Include fixture audit so the comparison layer can verify scenario
        # isolation (preexisting_activity_count == 0, etc.).
        dataset = result.get("dataset", {})
        if isinstance(dataset, dict) and "fixture_audit" in dataset:
            payload["fixture_audit"] = dataset["fixture_audit"]
            payload["preexisting_activity_count"] = (
                dataset.get("fixture_audit", {}).get(
                    "preexisting_activity_count", 0
                )
            )
            payload["heavy_session_activity_count"] = (
                dataset.get("heavy_session_activity_count", 0)
            )
            payload["heavy_session_marker"] = (
                dataset.get("heavy_session_marker", "")
            )

        if result["status"] == "ok" and runs_data:
            payload["metrics"] = _extract_webview_metrics(runs_data)
            payload["raw_runs"] = runs_data
            payload["cold_warm"] = _build_cold_warm_summary(runs_data)
        else:
            payload["failure_reason"] = result.get("failure_reason", "")
            payload["failure_category"] = result.get("failure_category", "")
            if "js_stack" in result:
                payload["js_stack"] = result["js_stack"]
            if runs_data:
                payload["raw_runs"] = runs_data
                payload["cold_warm"] = _build_cold_warm_summary(runs_data)
            # No metrics key — comparison layer treats missing metrics as
            # a fail-closed input/schema error.

        _atomic_write_json(args.output, payload)
        print(f"\nstructured result written to {args.output}")

    # ---- Legacy summary (always written to test-results/) ----
    summary: dict[str, Any] = {
        "commit_sha": _get_git_sha(),
        "platform": platform.platform(),
        "python_version": sys.version,
        "runner_metadata": runner_meta,
        "webview2_runtime": result.get("runtime_detection", "unknown"),
        "activity_count": activity_count,
        "runs_requested": runs,
        "profile": args.profile,
        "status": result["status"],
    }

    if result["status"] == "ok":
        summary["dataset"] = result.get("dataset", {})
        summary["raw_runs"] = runs_data
        summary["cold_warm"] = _build_cold_warm_summary(runs_data)
        summary["summary"] = _median_over_runs(runs_data)
    else:
        summary["failure_reason"] = result.get("failure_reason", "")
        summary["failure_category"] = result.get("failure_category", "")
        if "js_stack" in result:
            summary["js_stack"] = result["js_stack"]
        if runs_data:
            summary["dataset"] = result.get("dataset", {})
            summary["raw_runs"] = runs_data
            summary["cold_warm"] = _build_cold_warm_summary(runs_data)
            summary["summary"] = _median_over_runs(runs_data)

    out_dir = _REPO_ROOT / "test-results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "webview-render-perf.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if result["status"] != "ok":
        print(f"\nWebView render validation FAILED: {result.get('failure_reason', '')}")
        return 1

    print("\nWebView render validation succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
