const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { loadSettingsModules } = require("./settings_test_helpers");

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

function row(duration, percentage, key) {
  const cells = [
    { textContent: "name" },
    { textContent: duration },
    { textContent: "1" },
    { textContent: percentage },
  ];
  const bar = { style: { width: "0%" } };
  return {
    children: cells,
    getAttribute(name) { return name === "data-statistics-key" ? key : null; },
    querySelector(selector) { return selector === ".stats-share-bar i" ? bar : null; },
    bar,
  };
}

function navTarget(page, document) {
  return {
    getAttribute(name) { return name === "data-page" ? page : null; },
    parentNode: document,
  };
}

function harness(initialRuntime) {
  let runtimeState = initialRuntime || runtime();
  const listeners = {};
  const elements = {};
  let visibleSettingsLoads = 0;
  elements["settings-loading"] = {
    _hidden: true,
    get hidden() { return this._hidden; },
    set hidden(value) {
      this._hidden = !!value;
      if (value === false) visibleSettingsLoads += 1;
    },
  };
  const document = {
    activeElement: null,
    addEventListener(name, handler) { listeners[name] = handler; },
    getElementById(id) { return elements[id] || null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  let baseTimelineRefreshes = 0;
  let baseOverviewRenders = 0;
  const overviewTransitions = [];
  let baseStatusRenders = 0;
  let rulesRequests = 0;
  let statisticsRequests = 0;
  let settingsRequests = 0;
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
    rulesLoading: false,
    statisticsLoaded: true,
    statisticsLoading: false,
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
      getSettingsPrivacyStatus() {
        settingsRequests += 1;
        return Promise.resolve({ ok: true, status: { collector_running: true } });
      },
    },
    handleResult(value) { return value && value.ok === false ? null : value; },
    applyLocalTicker() {},
    refreshAll() { return Promise.resolve("base"); },
    refreshTimeline() { baseTimelineRefreshes += 1; return Promise.resolve("timeline"); },
    loadProjectRules() { return Promise.resolve(null); },
    loadStatisticsExportSummary() { return Promise.resolve(null); },
    overview: {
      onRuntimeTransition(change) { overviewTransitions.push(change); },
    },
    showOverview() { baseOverviewRenders += 1; },
    showStatus() { baseStatusRenders += 1; },
    showProjectRules() {},
    showStatistics() {},
    renderSettingsStatus() {},
    showRulesError() {},
    clearRulesError() {},
    showStatisticsError() {},
    clearStatisticsError() {},
    showSettingsError() {},
    clearSettingsError() {},
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
    clearTimeout,
    addEventListener() {},
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
  ["rules.js"].forEach((name) => {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", name), "utf8"),
      context,
      { filename: name }
    );
  });
  loadSettingsModules(context);
  ["timeline.js", "statistics.js"].forEach((name) => {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", name), "utf8"),
      context,
      { filename: name }
    );
  });
  App.loadTimelineReport = () => {
    baseTimelineRefreshes += 1;
    return Promise.resolve("timeline");
  };
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/ui_composition.js"), "utf8"),
    context,
    { filename: "ui_composition.js" }
  );
  return {
    App,
    document,
    elements,
    listeners,
    counters: {
      timeline: () => baseTimelineRefreshes,
      overview: () => baseOverviewRenders,
      overviewTransitions: () => overviewTransitions.slice(),
      status: () => baseStatusRenders,
      rules: () => rulesRequests,
      statistics: () => statisticsRequests,
      settings: () => settingsRequests,
      visibleSettings: () => visibleSettingsLoads,
    },
  };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

async function flushTimers() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await flush();
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
  assert.equal(App.rulesRefreshPending, false);
});

test("Rules re-entry is a no-op until classification generation changes", async () => {
  const { App, counters } = harness(runtime());
  App.currentPage = "rules";

  await App.rules.onPageEntered();
  assert.equal(counters.rules(), 0);

  App.currentPage = "overview";
  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ classification: 2 }) });
  await flush();
  assert.equal(counters.rules(), 0);
  assert.equal(App.rulesRefreshPending, true);

  App.currentPage = "rules";
  await App.rules.onPageEntered();
  assert.equal(counters.rules(), 1);
  assert.equal(App.rulesRefreshPending, false);
});

test("Settings re-entry refreshes status in the background without visible loading", async () => {
  const { App, counters } = harness(runtime());
  App.currentPage = "settings";

  await App.settings.onPageEntered();
  assert.equal(counters.settings(), 1);
  assert.equal(counters.visibleSettings(), 1, "first entry owns one visible loading state");
  assert.equal(App.settings.refreshPending(), false);

  App.currentPage = "overview";
  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ settings: 2 }) });
  await flush();
  assert.equal(counters.settings(), 1);
  assert.equal(App.settings.refreshPending(), true);

  App.currentPage = "settings";
  await App.settings.onPageEntered();
  assert.equal(counters.settings(), 2);
  assert.equal(counters.visibleSettings(), 1, "loaded re-entry stays background-only");
  assert.equal(App.settings.refreshPending(), false);
});

test("Settings generation refresh while visible is background-only", async () => {
  const { App, counters } = harness(runtime());
  App.currentPage = "settings";

  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ settings: 2 }) });
  await flush();

  assert.equal(counters.settings(), 1);
  assert.equal(counters.visibleSettings(), 0);
  assert.equal(App.settings.refreshPending(), false);
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

test("Overview runtime reconciliation is dispatched as transition facts", () => {
  const { App, counters } = harness(runtime());
  App.currentPage = "overview";

  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ live: "l2" }) });
  App.acceptRefreshStateRuntime({ nextRuntime: runtime({ structure: "s2", live: "l3" }) });

  assert.equal(counters.overview(), 0);
  assert.deepEqual(
    counters.overviewTransitions().map((change) => [change.structureChanged, change.liveChanged]),
    [[false, true], [true, true]]
  );
});

test("Statistics local ticker patches numeric cells without calling full renderer", () => {
  const { App, elements } = harness(runtime());
  App.currentPage = "statistics";
  let fullRenders = 0;
  App.showStatistics = () => { fullRenders += 1; };

  const projectRow = row("00:00:10", "50%", "P");
  const appRow = row("00:00:10", "50%", "A");
  elements["stats-total"] = { textContent: "00:00:20" };
  elements["stats-by-project"] = { querySelectorAll() { return [projectRow]; } };
  elements["stats-by-file"] = { querySelectorAll() { return []; } };
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

test("Statistics local ticker is a no-op when the accepted row shape no longer matches", () => {
  const { App, elements } = harness(runtime());
  App.currentPage = "statistics";
  let fullRenders = 0;
  App.showStatistics = () => { fullRenders += 1; };

  const mismatchedRow = row("00:00:10", "50%", "stale-key");
  elements["stats-total"] = { textContent: "00:00:20" };
  elements["stats-by-project"] = { querySelectorAll() { return [mismatchedRow]; } };
  elements["stats-by-file"] = { querySelectorAll() { return []; } };
  elements["stats-by-app"] = { querySelectorAll() { return []; } };
  App.statisticsAcceptedPayload = {
    filters: { dateFrom: "2026-08-13", dateTo: "2026-08-13", projectId: "" },
    summary: {
      snapshot_revision: "r1",
      total_duration_seconds: 20,
      total_duration: "00:00:20",
      by_project: [{ key: "current-key", duration_seconds: 10, duration: "00:00:10", percentage: 50 }],
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

  App.applyStatisticsLocalTicker();

  assert.equal(fullRenders, 0);
  assert.equal(elements["stats-total"].textContent, "00:00:20");
  assert.equal(mismatchedRow.children[1].textContent, "00:00:10");
  assert.equal(App.statisticsLastLiveRenderKey || "", "");
});

test("unchanged collector status is render-no-op", () => {
  const { App, counters } = harness(runtime());
  const value = { status: "running", paused: false, display: "记录中" };
  App.showStatus(value);
  App.showStatus(value);
  assert.equal(counters.status(), 1);
});

test("periodic visible reconcile state is retired", () => {
  const { App } = harness(runtime());
  assert.equal(App.RECONCILE_INTERVAL_MS, undefined);
  assert.equal(App.lastReconcileAtEpochMs, undefined);
  assert.equal(App.reconcileInFlight, undefined);
});
