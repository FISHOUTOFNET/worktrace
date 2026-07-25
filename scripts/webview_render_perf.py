"""Windows WebView render performance harness.

Launches a real WebView2 window with a large projection dataset, injects
``performance.mark`` / ``performance.measure`` /
``requestAnimationFrame`` instrumentation via ``evaluate_js``, and
collects cold/warm render timings for Overview, Timeline, and detail.

Usage (Windows only, requires WebView2 Runtime)::

    python scripts/webview_render_perf.py --activity-count 20000 --runs 3

Outputs a JSON artifact to ``test-results/webview-render-perf.json``.

If WebView2 cannot start (missing runtime, headless CI, no desktop
session), the harness records the actual failure reason and exits with a
non-zero code — it never fakes a successful measurement.

This harness does NOT modify shipped frontend files.  All performance
instrumentation is injected at runtime via ``window.evaluate_js`` so
static contract tests are unaffected.

The runtime is constructed exactly like ``worktrace.webview_main.main()``
using a temp data directory, so the bridge serves real projection data
from a real SQLite database.  Collector startup is intentionally skipped
because render measurement only reads persisted data; the collector
status reports "not running" which is a valid state for the UI.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


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


def _populate_dataset(activity_count: int) -> dict[str, Any]:
    """Insert ``activity_count`` synthetic activities into the configured DB.

    Must be called after ``AppRuntime.initialize()`` so the global DB path
    is set and the schema is applied.
    """
    from tests.support import projection_benchmark

    return projection_benchmark.build_benchmark_dataset(
        activity_count=activity_count,
    )


# JS injected into WebView2 to run the full measurement sequence using real
# performance.mark/measure and requestAnimationFrame.  Calls the same shipping
# bridge surface (getOverview / getTimeline / getTimelineSessionActivitySummary)
# as the real UI, so this measures the real frontend render path, not Python.
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

    async function runOnce(label) {
        var App = window.WorkTraceApp;
        var results = { label: label, stages: {} };

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
        // After Timeline render, find the first .timeline-item in the DOM,
        // read its projection_instance_key, and trigger selection through
        // the public App.selectTimelineSession entry point.  This exercises
        // the real detail load + DOM render path, not just the bridge API.
        var firstItem = document.querySelector(
            "#timeline-sessions-list .timeline-item"
        );
        var detailKey = firstItem
            ? (firstItem.getAttribute("data-projection-instance-key") || "")
            : "";
        if (detailKey) {
            mark(label + "_detail_start");

            // Instrument the bridge to capture the payload-arrival moment
            // without modifying production business semantics.  The bridge
            // object is frozen, but App.bridge is reassignable, so we swap
            // in a shallow copy that wraps the detail method.
            var originalBridge = App.bridge;
            var wrappedBridge = {};
            var bridgeKeys = Object.keys(originalBridge);
            for (var bi = 0; bi < bridgeKeys.length; bi++) {
                wrappedBridge[bridgeKeys[bi]] = originalBridge[bridgeKeys[bi]];
            }
            var detailPayloadMarked = false;
            wrappedBridge.getTimelineSessionActivitySummary = function () {
                var args = Array.prototype.slice.call(arguments);
                return originalBridge.getTimelineSessionActivitySummary
                    .apply(originalBridge, args)
                    .then(function (result) {
                        if (!detailPayloadMarked) {
                            mark(label + "_detail_payload");
                            detailPayloadMarked = true;
                        }
                        return result;
                    });
            };
            App.bridge = wrappedBridge;

            // Reset the view-model so we can detect the fresh render.
            App.lastSessionActivitySummaryViewModel = null;

            // Trigger real selection through the public entry point.
            try {
                App.selectTimelineSession(detailKey, App.currentSessions || []);
            } catch (selErr) {
                App.bridge = originalBridge;
                results.stages.detail_error = "select_exception:" + String(selErr);
            }

            if (!results.stages.detail_error) {
                // Wait for real completion: view-model updated, header not
                // loading, DOM has .summary-item rows, no in-flight request.
                var detailDeadline = Date.now() + 15000;
                var detailCompleted = false;
                var detailFailureCat = "";
                var detailHeader = "";
                var detailDomRows = 0;

                while (Date.now() < detailDeadline) {
                    var dHeader = document.getElementById("timeline-details-header");
                    detailHeader = dHeader ? dHeader.textContent.trim() : "";
                    var dList = document.getElementById("timeline-details-list");
                    detailDomRows = dList
                        ? dList.querySelectorAll(".summary-item").length : 0;
                    var dVm = App.lastSessionActivitySummaryViewModel;
                    var dInFlight = Object.keys(App.detailsInFlight || {}).length;

                    if (dVm !== null
                        && detailHeader === "活动详情"
                        && detailDomRows > 0
                        && dInFlight === 0) {
                        detailCompleted = true;
                        break;
                    }
                    if (detailHeader.indexOf("失败") !== -1) {
                        detailFailureCat = "detail_load_failed";
                        break;
                    }
                    await sleep(10);
                }

                // Restore the original bridge before measuring.
                App.bridge = originalBridge;

                if (detailCompleted) {
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
                    var dVm2 = App.lastSessionActivitySummaryViewModel;
                    results.detail_row_count = (dVm2 && dVm2.summary_rows)
                        ? dVm2.summary_rows.length : 0;
                    results.detail_dom_row_count = detailDomRows;
                    results.detail_header_text = detailHeader;

                    // Realism assertions.
                    if (results.detail_row_count === 0) {
                        results.stages.detail_error = "detail_row_count_zero";
                    } else if (results.detail_dom_row_count === 0) {
                        results.stages.detail_error = "detail_dom_row_count_zero";
                    } else if (results.detail_dom_row_count
                               !== results.detail_row_count) {
                        results.stages.detail_error = "detail_row_count_mismatch";
                    }
                } else {
                    results.stages.detail_error = detailFailureCat
                        || "detail_timeout";
                    results.detail_header_text = detailHeader;
                    results.detail_dom_row_count = detailDomRows;
                }
            }
        } else {
            results.stages.detail_error = "no_timeline_item_key";
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


def _run_harness(activity_count: int, runs: int) -> dict[str, Any]:
    """Launch WebView2, inject measurement JS, collect results."""
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
                dataset_info = _populate_dataset(activity_count)
            except Exception as exc:
                return {
                    "status": "failed",
                    "failure_reason": f"dataset build failed: {exc}",
                    "failure_category": "dataset_build_error",
                    "runtime_detection": runtime_status,
                }

            services = build_application_services(runtime)
            bridge = WebViewBridge(services)

            index_path = _REPO_ROOT / "worktrace" / "webview_ui" / "index.html"

            results_holder: dict[str, Any] = {"results": None, "error": None}

            def on_loaded(window):
                """Inject measurement JS when the window finishes loading."""
                try:
                    # Tell the JS how many runs to execute and which report
                    # date to query (the benchmark dataset is inserted on a
                    # fixed date, not today).
                    report_date = str(dataset_info.get("report_date", ""))[:10]
                    window.evaluate_js(
                        f"window.__perfRunCount = {int(runs)};"
                        f" window.__perfReportDate = {json.dumps(report_date)};"
                    )
                    # Inject the measurement script.
                    window.evaluate_js(_MEASURE_JS)

                    # Poll for results (the JS runs async).
                    deadline = time.monotonic() + 180.0
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

    runs = parsed.get("runs", [])

    # Enforce realism assertions on every run.  A run with ``detail_error``
    # or missing detail payload means the real Detail render path did not
    # complete, so the harness must report failure — never mask it with
    # ``status: ok``.
    detail_failures: list[str] = []
    for run in runs:
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
            "runs": runs,
        }

    return {
        "status": "ok",
        "runtime_detection": runtime_status,
        "dataset": {
            "activity_count": dataset_info.get("activity_count", activity_count),
            "report_date": dataset_info.get("report_date", ""),
        },
        "runs": runs,
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


def _get_git_sha() -> str:
    try:
        import subprocess
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
    parser.add_argument("--activity-count", type=int, default=20000)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    result = _run_harness(args.activity_count, args.runs)

    runner_meta = _runner_metadata()
    summary: dict[str, Any] = {
        "commit_sha": _get_git_sha(),
        "platform": platform.platform(),
        "python_version": sys.version,
        "runner_metadata": runner_meta,
        "webview2_runtime": result.get("runtime_detection", "unknown"),
        "activity_count": args.activity_count,
        "runs_requested": args.runs,
        "status": result["status"],
    }

    if result["status"] == "ok":
        runs = result.get("runs", [])
        summary["dataset"] = result.get("dataset", {})
        summary["raw_runs"] = runs
        summary["cold_warm"] = _build_cold_warm_summary(runs)
        summary["summary"] = _median_over_runs(runs)
    else:
        summary["failure_reason"] = result.get("failure_reason", "")
        summary["failure_category"] = result.get("failure_category", "")
        if "js_stack" in result:
            summary["js_stack"] = result["js_stack"]
        # Preserve raw runs, dataset, and cold/warm summary even on failure
        # so the artifact has full diagnostic data for the failure cause.
        runs = result.get("runs", [])
        if runs:
            summary["dataset"] = result.get("dataset", {})
            summary["raw_runs"] = runs
            summary["cold_warm"] = _build_cold_warm_summary(runs)
            summary["summary"] = _median_over_runs(runs)

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
