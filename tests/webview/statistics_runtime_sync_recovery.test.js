const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  let runtime = { collector: { live_eligible: true } };
  let loaded = true;
  const elements = {};
  const document = {
    getElementById(id) { return elements[id] || null; },
  };
  const App = {
    currentPage: "statistics",
    statisticsLiveTickerSuspended: false,
    statisticsAcceptedPayload: {
      summary: {
        snapshot_revision: "r1",
        total_duration_seconds: 10,
        by_project: [],
        by_file: [],
        by_app: [],
      },
      exportTicket: { revision: "r1", live_target: null },
      filters: { dateFrom: "2026-08-27", dateTo: "2026-08-27", projectId: "" },
    },
    formatDuration(value) { return String(value); },
    handleResult(result) { return result; },
    liveSampleFresh() { return true; },
    liveRuntimeStore: { get() { return runtime; } },
    statistics: {
      refreshPolicy: { deferred: true, preservePresentation: true },
      hasLoadedData() { return loaded; },
      refreshEvidence() { return App.statisticsAcceptedPayload; },
      applyLocalTick() { return null; },
      onRuntimeTransition() {},
      resetGeneration() { loaded = false; },
    },
  };
  const window = { WorkTraceApp: App, document };
  const context = {
    window,
    document,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    Promise,
    parseInt,
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/statistics_live_projection.js"),
      "utf8"
    ),
    context,
    { filename: "statistics_live_projection.js" }
  );
  return {
    App,
    setRuntime(value) { runtime = value; },
  };
}

function statisticsResult(runtimeSync) {
  return {
    summary: { total_duration_seconds: 10 },
    export_ticket: { revision: "r2", live_target: null },
    runtime_sync: runtimeSync,
  };
}

test("degraded Statistics success remains provisional and requests self-heal", () => {
  const { App } = harness();

  App.handleResult(statisticsResult({
    runtime_consistent: false,
    needs_full_refresh: true,
    collection_live_eligible: true,
  }));

  assert.equal(App.statisticsLiveProjection.runtimeSyncPending(), true);
  assert.equal(App.statistics.hasLoadedData(), false);
  assert.equal(App.statisticsLiveTickerSuspended, true);

  const tick = App.statistics.applyLocalTick();
  assert.equal(tick && tick.refreshRequired, true);
  assert.equal(tick && tick.reason, "statistics_runtime_sync_pending");

  App.handleResult(statisticsResult({
    runtime_consistent: true,
    needs_full_refresh: false,
    collection_live_eligible: true,
  }));
  assert.equal(App.statisticsLiveProjection.runtimeSyncPending(), false);
  assert.equal(App.statistics.hasLoadedData(), true);
});

test("collection liveness recovery rebases Statistics without report generation change", () => {
  const { App, setRuntime } = harness();

  App.handleResult(statisticsResult({
    runtime_consistent: true,
    needs_full_refresh: false,
    collection_live_eligible: false,
  }));
  App.statisticsLiveTickerSuspended = false;
  setRuntime({ collector: { live_eligible: true } });

  const tick = App.statistics.applyLocalTick();

  assert.equal(tick && tick.refreshRequired, true);
  assert.equal(tick && tick.reason, "statistics_runtime_liveness_changed");
  assert.equal(App.statisticsLiveTickerSuspended, true);
});
