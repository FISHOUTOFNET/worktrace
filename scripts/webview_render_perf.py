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

        // Detail open (if timeline has sessions)
        if (timelineData && timelineData.entries && timelineData.entries.length > 0) {
            var firstSession = timelineData.entries[0];
            var key = firstSession.projection_instance_key || "";
            var rev = firstSession.projection_revision || "";
            if (key && rev) {
                mark(label + "_detail_start");
                var detail = await App.bridge.getTimelineSessionActivitySummary(
                    key, reportDate, rev, ""
                );
                mark(label + "_detail_payload");
                if (detail && detail.ok !== false) {
                    await onFrame();
                    mark(label + "_detail_first_frame");
                    results.stages.detail_total_ms = measure(
                        label + "_detail_total_ms",
                        label + "_detail_start",
                        label + "_detail_first_frame"
                    );
                    results.detail_row_count = detail.summary_rows
                        ? detail.summary_rows.length : 0;
                } else {
                    results.stages.detail_error = (detail && detail.error) || "unknown";
                }
            }
        }

        // Warm-cache overview re-render
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

    return {
        "status": "ok",
        "runtime_detection": runtime_status,
        "dataset": {
            "activity_count": dataset_info.get("activity_count", activity_count),
            "report_date": dataset_info.get("report_date", ""),
        },
        "runs": parsed.get("runs", []),
    }


def _summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute medians across runs for each stage."""
    if not runs:
        return {}

    stages: dict[str, list[float]] = {}
    for run in runs:
        run_stages = run.get("stages", {})
        for name, value in run_stages.items():
            if isinstance(value, (int, float)):
                stages.setdefault(name, []).append(float(value))

    medians = {}
    for name, values in stages.items():
        if values:
            medians[name] = statistics.median(values)

    return {
        "run_count": len(runs),
        "median_ms": medians,
        "timeline_entry_count": runs[0].get("timeline_entry_count", 0),
        "detail_row_count": runs[0].get("detail_row_count", 0),
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

    summary: dict[str, Any] = {
        "commit_sha": _get_git_sha(),
        "platform": platform.platform(),
        "python_version": sys.version,
        "runner_image": os.environ.get("RUNNER_IMAGE", "local"),
        "webview2_runtime": result.get("runtime_detection", "unknown"),
        "activity_count": args.activity_count,
        "runs_requested": args.runs,
        "status": result["status"],
    }

    if result["status"] == "ok":
        runs = result.get("runs", [])
        summary["dataset"] = result.get("dataset", {})
        summary["raw_runs"] = runs
        summary["summary"] = _summarize(runs)
    else:
        summary["failure_reason"] = result.get("failure_reason", "")
        summary["failure_category"] = result.get("failure_category", "")
        if "js_stack" in result:
            summary["js_stack"] = result["js_stack"]

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
