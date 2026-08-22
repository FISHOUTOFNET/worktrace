const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function formatDuration(value) {
  value = Math.max(0, Number(value) || 0);
  const h = String(Math.floor(value / 3600)).padStart(2, "0");
  const m = String(Math.floor(value % 3600 / 60)).padStart(2, "0");
  const s = String(Math.floor(value % 60)).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function harness() {
  const elements = {};
  const document = {
    getElementById(id) { return elements[id] || null; },
    querySelectorAll() { return []; },
  };
  const App = {
    currentPage: "statistics",
    formatDuration,
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
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/statistics.js"), "utf8"),
    context,
    { filename: "statistics.js" }
  );
  return { App, elements };
}

function row(key) {
  const cells = [{}, { textContent: "00:00:10" }, {}, { textContent: "50%" }];
  const bar = { style: { width: "50%" } };
  return {
    children: cells,
    getAttribute(name) { return name === "data-statistics-key" ? key : null; },
    querySelector(selector) { return selector === ".stats-share-bar i" ? bar : null; },
  };
}

test("Statistics local projection mismatch requests authoritative refresh", () => {
  const { App, elements } = harness();
  elements["stats-total"] = { textContent: "00:00:20" };
  elements["stats-by-project"] = { querySelectorAll() { return [row("stale-key")]; } };
  elements["stats-by-file"] = { querySelectorAll() { return []; } };
  elements["stats-by-app"] = { querySelectorAll() { return []; } };

  App.statisticsAcceptedPayload = {
    filters: { dateFrom: "2026-08-22", dateTo: "2026-08-22", projectId: "" },
    summary: {
      snapshot_revision: "r1",
      total_duration_seconds: 20,
      total_duration: "00:00:20",
      by_project: [
        { key: "current-key", duration_seconds: 10, duration: "00:00:10", percentage: 50 },
      ],
      by_file: [],
      by_app: [],
      by_status: [],
    },
    exportTicket: {
      revision: "r1",
      live_target: {
        enabled: true,
        ticking: true,
        sampled_at_epoch_ms: Date.now() - 5000,
        elapsed_seconds_at_sample: 0,
        project_key: "current-key",
      },
    },
  };

  const result = App.statistics.applyLocalTick();

  assert.equal(result && result.refreshRequired, true);
  assert.equal(result && result.reason, "statistics_live_projection_mismatch");
  assert.equal(App.statisticsLastLiveRenderKey || "", "");
});

test("Statistics owns activity-boundary ticker suspension", () => {
  const { App } = harness();
  App.statisticsLiveTickerSuspended = false;

  App.statistics.onRuntimeTransition({
    source: "refresh-state",
    reportStructureChanged: true,
  });

  assert.equal(App.statisticsLiveTickerSuspended, true);
});

test("composition forwards Statistics transition facts without touching ticker internals", () => {
  const composition = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/ui_composition.js"),
    "utf8"
  );

  assert.match(composition, /App\.statistics\.onRuntimeTransition/);
  assert.doesNotMatch(composition, /suspendStatisticsLiveTicker/);
});
