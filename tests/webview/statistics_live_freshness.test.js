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
  const listeners = {};
  let runtime = null;
  const document = {
    addEventListener(name, handler) { listeners[name] = handler; },
    getElementById() { return null; },
  };
  const window = {
    document,
    setTimeout,
    WorkTraceApp: {
      formatDuration,
      applyLocalTicker() {},
      refreshAll() { return Promise.resolve("base"); },
      acceptRefreshStateRuntime(state) {
        if (state && state.runtime) runtime = state.runtime;
        return true;
      },
      acceptPagePayloadRuntime(payload) {
        if (payload && payload.runtime) runtime = payload.runtime;
        return true;
      },
      liveRuntimeStore: { get() { return runtime; } },
    },
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
    App: window.WorkTraceApp,
    listeners,
    setRuntime(value) { runtime = value; },
  };
}

function runtimeState(structureRevision, liveRevision = "live-1") {
  return {
    structureRevision,
    liveRevision,
    generations: {
      classification_catalog: 1,
      settings: 1,
    },
  };
}

test("statistics live math adds only post-sample delta and recomputes every share", () => {
  const { App } = harness();
  const base = {
    total_duration_seconds: 100,
    total_duration: "00:01:40",
    project_duration_seconds: 80,
    project_duration: "00:01:20",
    classified_duration_seconds: 80,
    uncategorized_duration_seconds: 20,
    excluded_duration_seconds: 0,
    by_project: [
      { key: "A", display_name: "A", duration_seconds: 80, duration: "00:01:20", percentage: 80 },
      { key: "未归类", display_name: "未归类", duration_seconds: 20, duration: "00:00:20", percentage: 20 },
    ],
    by_file: [
      { key: "file:brief.docx", display_name: "brief.docx", duration_seconds: 80, duration: "00:01:20", percentage: 80 },
      { key: "file:notes.md", display_name: "notes.md", duration_seconds: 20, duration: "00:00:20", percentage: 20 },
    ],
    by_app: [
      { key: "Word", display_name: "Word", duration_seconds: 80, duration: "00:01:20", percentage: 80 },
      { key: "Edge", display_name: "Edge", duration_seconds: 20, duration: "00:00:20", percentage: 20 },
    ],
    by_status: [{ key: "normal", display_name: "正常", duration_seconds: 100, duration: "00:01:40", percentage: 100 }],
    export_preview: { included_duration_seconds: 100, included_duration: "00:01:40" },
    live_target: {
      enabled: true,
      ticking: true,
      sampled_at_epoch_ms: 100000,
      elapsed_seconds_at_sample: 30,
      project_key: "A",
      file_key: "file:brief.docx",
      app_key: "Word",
      status_key: "normal",
      contributes_project_duration: true,
      is_uncategorized: false,
      is_excluded_status: false,
    },
  };

  const live = App.statisticsLiveSummaryAtNow(base, 110000);
  assert.equal(live.total_duration_seconds, 110);
  assert.equal(live.project_duration_seconds, 90);
  assert.equal(live.by_project.find((row) => row.key === "A").duration_seconds, 90);
  assert.equal(live.by_project.find((row) => row.key === "未归类").duration_seconds, 20);
  assert.equal(live.by_file.find((row) => row.key === "file:brief.docx").duration_seconds, 90);
  assert.equal(live.by_file.find((row) => row.key === "file:notes.md").duration_seconds, 20);
  assert.equal(live.by_app.find((row) => row.key === "Word").duration_seconds, 90);
  assert.equal(live.by_status[0].duration_seconds, 110);
  assert.equal(live.by_project.find((row) => row.key === "A").percentage, 81.8);
  assert.equal(live.by_file.find((row) => row.key === "file:brief.docx").percentage, 81.8);
  assert.equal(live.by_project.find((row) => row.key === "未归类").percentage, 18.2);
  assert.equal(live.export_preview.included_duration_seconds, 110);
  assert.equal(base.total_duration_seconds, 100);
  assert.equal(base.by_project[0].duration_seconds, 80);
  assert.equal(base.by_file[0].duration_seconds, 80);
});

test("manual refresh is routed to the active composed page", async () => {
  const { App } = harness();
  let rules = 0;
  let statistics = 0;
  let settings = 0;
  App.loadProjectRules = () => { rules += 1; return Promise.resolve(); };
  App.loadStatisticsExportSummary = () => { statistics += 1; return Promise.resolve(); };
  App.loadSettingsPrivacyStatus = () => { settings += 1; return Promise.resolve(); };

  App.currentPage = "rules";
  await App.refreshAll();
  App.currentPage = "statistics";
  await App.refreshAll();
  App.currentPage = "settings";
  await App.refreshAll();

  assert.deepEqual([rules, statistics, settings], [1, 1, 1]);
});

test("loaded settings refresh in the background on every page entry", async () => {
  const { App, listeners } = harness();
  let requests = 0;
  App.currentPage = "settings";
  App.settingsLoaded = true;
  App.settingsLoading = false;
  App.settingsRefreshPending = false;
  App.settingsRequestToken = 0;
  App.bridge = {
    getSettingsPrivacyStatus() {
      requests += 1;
      return Promise.resolve({ status: { collector_running: true } });
    },
  };
  App.handleResult = (result) => result;
  App.renderSettingsStatus = () => {};
  App.clearSettingsError = () => {};
  App.loadSettingsPrivacyStatus = () => Promise.resolve();

  const target = {
    parentNode: null,
    getAttribute(name) { return name === "data-page" ? "settings" : null; },
  };
  listeners.click({ type: "click", target });
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert.equal(requests, 1);
  assert.equal(App.settingsRefreshPending, false);
});

test("timeline structural refresh is held while editing and drains when clean", async () => {
  const { App } = harness();
  let editing = true;
  let refreshes = 0;
  App.currentPage = "timeline";
  App.timelineStructuralRefreshPending = true;
  App._timelineEditingActive = () => editing;
  App.refreshTimeline = () => { refreshes += 1; return Promise.resolve(); };

  assert.equal(await App.drainTimelineStructuralRefresh(), false);
  assert.equal(refreshes, 0);
  editing = false;
  assert.equal(await App.drainTimelineStructuralRefresh(), true);
  assert.equal(refreshes, 1);
  assert.equal(App.timelineStructuralRefreshPending, false);
});

test("page payload structure changes invalidate project last-used presentation", () => {
  const { App, setRuntime } = harness();
  setRuntime(runtimeState("structure-1"));
  App.currentPage = "timeline";
  App.rulesRefreshPending = false;

  App.acceptPagePayloadRuntime({ runtime: runtimeState("structure-2") });

  assert.equal(App.rulesRefreshPending, true);
  assert.equal(App.timelineStructuralRefreshPending, undefined);
});

test("statistics local ticker never marks an unfetched runtime revision as accepted", () => {
  const { App, setRuntime } = harness();
  setRuntime(runtimeState("structure-2"));
  App.currentPage = "statistics";
  App.statisticsAcceptedRefreshIdentity = "structure-1|live-1";
  App.statisticsAcceptedPayload = {
    summary: {
      snapshot_revision: "snapshot-1",
      total_duration_seconds: 10,
      by_project: [],
      by_file: [],
      by_app: [],
      by_status: [],
    },
    exportTicket: { revision: "snapshot-1" },
    filters: { dateFrom: "2026-08-16", dateTo: "2026-08-16", projectId: "" },
  };

  App.applyStatisticsLocalTicker();

  assert.equal(App.statisticsAcceptedRefreshIdentity, "structure-1|live-1");
});

test("background statistics refresh records the runtime identity captured at request start", async () => {
  const { App, setRuntime } = harness();
  setRuntime(runtimeState("structure-1"));
  let resolveRequest;
  const response = new Promise((resolve) => { resolveRequest = resolve; });
  App.bridge = { getStatisticsExportSummary() { return response; } };
  App.selectedStatisticsFilters = () => ({
    dateFrom: "2026-08-16",
    dateTo: "2026-08-16",
    projectId: "",
  });
  App.requestCoordinator = {
    beginLatest() { return { id: 1 }; },
    isCurrent() { return true; },
  };
  App.handleResult = (result) => result;
  App.showStatistics = () => {};
  App.clearStatisticsError = () => {};

  const pending = App.backgroundStatisticsRefresh();
  setRuntime(runtimeState("structure-2"));
  resolveRequest({
    summary: { total_duration_seconds: 20, by_project: [], by_file: [], by_app: [], by_status: [] },
    export_ticket: { revision: "snapshot-2" },
  });
  await pending;

  assert.equal(App.statisticsAcceptedRefreshIdentity, "structure-1|live-1");
});
