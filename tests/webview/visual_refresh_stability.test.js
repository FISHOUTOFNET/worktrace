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

function runtime({ structure = "s1", live = "l1", classification = 1, settings = 1 } = {}) {
  return {
    structureRevision: structure,
    liveRevision: live,
    generations: {
      report_structure: 1,
      classification_catalog: classification,
      settings,
    },
    collector: {},
  };
}

function row(duration, percentage) {
  const cells = [
    { textContent: "name" },
    { textContent: duration },
    { textContent: "1" },
    { textContent: percentage },
  ];
  const bar = { style: { width: "0%" } };
  return {
    children: cells,
    querySelector(selector) { return selector === ".stats-share-bar i" ? bar : null; },
    bar,
  };
}

function harness(initialRuntime) {
  let runtimeState = initialRuntime || runtime();
  const listeners = {};
  const elements = {};
  const document = {
    addEventListener(name, handler) { listeners[name] = handler; },
    getElementById(id) { return elements[id] || null; },
  };
  let baseTimelineRefreshes = 0;
  let baseOverviewRenders = 0;
  let baseStatusRenders = 0;
  let rulesRequests = 0;
  let statisticsRequests = 0;
  let tokenId = 0;
  const currentTokens = new Map();
  const requestCoordinator = {
    beginLatest(surface, key) {
      const token = { surface, key, id: ++tokenId };
      currentTokens.set(surface, token);
      return token;
    },
    isCurrent(token) { return currentTokens.get(token.surface) === token; },
  };
  const App = {
    formatDuration,
    currentPage: "overview",
    rulesLoaded: true,
    statisticsLoaded: true,
    statisticsLoading: false,
    settingsLoaded: true,
    requestCoordinator,
    bridge: {
      getProjectRules() {
        rulesRequests += 1;
        return Promise.resolve({ ok: true, projects: [] });
      },
      getStatisticsExportSummary() {
        statisticsRequests += 1;
        return Promise.resolve({
          ok: true,
          summary: {
            total_duration_seconds: 10,
            total_duration: "00:00:10",
            by_project: [],
            by_app: [],
          },
          export_ticket: { revision: "r1" },
        });
      },
    },
    handleResult(value) { return value && value.ok === false ? null : value; },
    applyLocalTicker() {},
    refreshAll() { return Promise.resolve("base"); },
    refreshTimeline() { baseTimelineRefreshes += 1; return Promise.resolve("timeline"); },
    showOverview() { baseOverviewRenders += 1; },
    showStatus() { baseStatusRenders += 1; },
    showProjectRules() {},
    showStatistics() {},
    selectedStatisticsFilters() {
      return { dateFrom: "2026-08-13", dateTo: "2026-08-13", projectId: "" };
    },
    liveRuntimeStore: { get() { return runtimeState; } },
    acceptRefreshStateRuntime(state) {
      runtimeState = state.nextRuntime;
      return true;
    },
  };
  const window = {
    document,
    setTimeout,
    WorkTraceApp: App,
  };
  const context = {
    window,
    document,
    Promise,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    JSON,
    parseInt,
    parseFloat,
    setTimeout,
    clearTimeout,
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/ui_composition.js"), "utf8"),
    context,
    { filename: "ui_composition.js" }
  );
  return {
    App,
    elements,
    listeners,
    counters: {
      timeline: () => baseTimelineRefreshes,
      overview: () => baseOverviewRenders,
      status: () => baseStatusRenders,
      rules: () => rulesRequests,
      statistics: () => statisticsRequests,
    },
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

test("Rules ignores live-only runtime changes but refreshes on classification generation", async () => {
  const { App, counters } = harness(runtime());
  App.currentPage = "rules";

  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ live: "l2" }) });
  await flush();
  assert.equal(counters.rules(), 0);

  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ live: "l3", classification: 2 }) });
  await flush();
  assert.equal(counters.rules(), 1);
});

test("Timeline consumes one live-only collection refresh but preserves structural refreshes", async () => {
  const { App, counters } = harness(runtime());
  App.currentPage = "timeline";
  App._timelineEditingActive = () => false;

  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ live: "l2" }) });
  await App.refreshTimeline();
  assert.equal(counters.timeline(), 0);
  assert.equal(App.suppressNextTimelineCollectionRefresh, false);

  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ structure: "s2", live: "l3" }) });
  await App.refreshTimeline();
  assert.equal(counters.timeline(), 1);
});

test("Overview live-only reconciliation does not rebuild the collection surface", () => {
  const { App, counters } = harness(runtime());
  App.currentPage = "overview";

  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ live: "l2" }) });
  App.showOverview({});
  assert.equal(counters.overview(), 0);

  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ structure: "s2", live: "l3" }) });
  App.showOverview({});
  assert.equal(counters.overview(), 1);
});

test("Statistics local ticker patches numeric cells without calling full renderer", () => {
  const { App, elements } = harness(runtime());
  App.currentPage = "statistics";
  let fullRenders = 0;
  App.showStatistics = () => { fullRenders += 1; };

  const projectRow = row("00:00:10", "50%");
  const appRow = row("00:00:10", "50%");
  elements["stats-total"] = { textContent: "00:00:20" };
  elements["stats-by-project"] = { querySelectorAll() { return [projectRow]; } };
  elements["stats-by-app"] = { querySelectorAll() { return [appRow]; } };

  const sampledAt = Date.now() - 5000;
  App.statisticsAcceptedPayload = {
    filters: { dateFrom: "2026-08-13", dateTo: "2026-08-13", projectId: "" },
    summary: {
      snapshot_revision: "r1",
      total_duration_seconds: 20,
      total_duration: "00:00:20",
      by_project: [{ key: "P", duration_seconds: 10, duration: "00:00:10", percentage: 50 }],
      by_app: [{ key: "A", duration_seconds: 10, duration: "00:00:10", percentage: 50 }],
      by_status: [],
    },
    exportTicket: {
      revision: "r1",
      live_target: {
        enabled: true,
        ticking: true,
        sampled_at_epoch_ms: sampledAt,
        elapsed_seconds_at_sample: 0,
        project_key: "P",
        app_key: "A",
        status_key: "",
        contributes_project_duration: false,
      },
    },
  };

  App.applyStatisticsLocalTicker();
  assert.equal(fullRenders, 0);
  assert.notEqual(elements["stats-total"].textContent, "00:00:20");
  assert.notEqual(projectRow.children[1].textContent, "00:00:10");
  assert.notEqual(appRow.children[1].textContent, "00:00:10");
});

test("unchanged collector status is render-no-op", () => {
  const { App, counters } = harness(runtime());
  const value = { status: "running", paused: false, display: "记录中" };
  App.showStatus(value);
  App.showStatus(value);
  assert.equal(counters.status(), 1);
});

test("periodic visible reconcile is disabled by composition policy", () => {
  const { App } = harness(runtime());
  assert.equal(App.RECONCILE_INTERVAL_MS, Number.MAX_SAFE_INTEGER);
});
