const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadModule(context, name) {
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", name), "utf8"),
    context,
    { filename: name }
  );
}

function formatDuration(value) {
  value = Math.max(0, Number(value) || 0);
  const h = String(Math.floor(value / 3600)).padStart(2, "0");
  const m = String(Math.floor(value % 3600 / 60)).padStart(2, "0");
  const s = String(Math.floor(value % 60)).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function createHarness() {
  let nowMs = 1_000_005_000;
  const timers = [];

  function row(key) {
    const cells = [
      { textContent: key },
      { textContent: "00:01:40" },
      { textContent: "1" },
      { textContent: "100%" },
    ];
    const bar = { style: { width: "100%" } };
    return {
      children: cells,
      getAttribute(name) { return name === "data-statistics-key" ? key : null; },
      querySelector(selector) { return selector === ".stats-share-bar i" ? bar : null; },
    };
  }

  const projectRow = row("P");
  const fileRow = row("F");
  const appRow = row("A");
  const pageRoot = { querySelectorAll() { return []; } };
  const elements = {
    "page-statistics": pageRoot,
    "stats-total": { textContent: "00:01:40" },
    "stats-by-project": { querySelectorAll() { return [projectRow]; } },
    "stats-by-file": { querySelectorAll() { return [fileRow]; } },
    "stats-by-app": { querySelectorAll() { return [appRow]; } },
    "statistics-results": { hidden: false },
    "stats-export-action-btn": { disabled: false },
    "statistics-project-filter": { value: "" },
    "statistics-loading": { hidden: true },
    "statistics-error": { hidden: true, textContent: "" },
  };

  const App = {
    currentPage: "statistics",
    heartbeatTimer: null,
    HEARTBEAT_INTERVAL_MS: 1000,
    statisticsLoaded: true,
    statisticsLoading: false,
    statisticsLiveTickerSuspended: false,
    statisticsLastLiveRenderKey: "",
    formatDuration,
    escapeHtml(value) { return String(value || ""); },
    localTodayStr() { return "2026-08-25"; },
    runtimeReportDateForPage() { return "2026-08-25"; },
    validateLiveClock(value) { return value && typeof value === "object" ? value : null; },
    computeClockDurationNow() { return 0; },
    recordLiveClockContractViolation() {},
    readLiveClockTarget() { return null; },
    liveTargetCompatibleWithRuntime() { return true; },
    clearLiveClockTarget() {},
    renderLiveDurationTarget() {},
    clearError() {},
    showError() {},
    showStatus() {},
    showGlobalAlert() {},
    clearGlobalAlert() {},
    extractBridgeError(_result, fallback) { return fallback; },
    handleResult(value) { return value; },
    requestCoordinator: {
      beginLatest() { return {}; },
      isCurrent() { return true; },
      bumpDataEpoch() {},
    },
    privacyNotice: {
      bindEvents() {},
      loadGate() { return Promise.resolve(false); },
    },
  };

  const document = {
    readyState: "loading",
    addEventListener() {},
    getElementById(id) { return elements[id] || null; },
    querySelectorAll() { return []; },
    querySelector() { return null; },
  };

  const FakeDate = class extends Date {
    static now() { return nowMs; }
  };

  const window = {
    WorkTraceApp: App,
    pywebview: { api: {} },
    addEventListener() {},
    removeEventListener() {},
    setTimeout(fn, delay) {
      timers.push({ fn, delay });
      return timers.length;
    },
    clearTimeout() {},
  };

  const context = {
    window,
    document,
    console,
    Promise,
    Date: FakeDate,
    Math,
    Number,
    String,
    Array,
    Object,
    JSON,
    parseInt,
    parseFloat,
    setInterval() { return {}; },
    clearInterval() {},
    setTimeout: window.setTimeout,
    clearTimeout: window.clearTimeout,
  };

  vm.createContext(context);
  loadModule(context, "statistics.js");
  loadModule(context, "statistics_live_projection.js");

  App.pageLifecycle = {
    names: Object.freeze(["statistics"]),
    capability(name) { return name === "statistics" ? App.statistics : null; },
    bindEvents() {},
    onPageLeft() {},
    resetGeneration() {},
  };

  loadModule(context, "init_fd_work_v5.js");
  loadModule(context, "ui_composition.js");

  App.statisticsAcceptedPayload = {
    filters: { dateFrom: "2026-08-25", dateTo: "2026-08-25", projectId: "" },
    summary: {
      snapshot_revision: "r1",
      total_duration_seconds: 100,
      by_project: [{ key: "P", display_name: "P", duration_seconds: 100, duration: "00:01:40", percentage: 100 }],
      by_file: [{ key: "F", display_name: "F", duration_seconds: 100, duration: "00:01:40", percentage: 100 }],
      by_app: [{ key: "A", display_name: "A", duration_seconds: 100, duration: "00:01:40", percentage: 100 }],
      by_status: [],
    },
    exportTicket: {
      revision: "r1",
      live_target: {
        enabled: true,
        ticking: true,
        sampled_at_epoch_ms: 1_000_000_000,
        elapsed_seconds_at_sample: 10,
        project_key: "P",
        file_key: "F",
        app_key: "A",
      },
    },
  };

  return {
    App,
    elements,
    timers,
    advance(ms) { nowMs += ms; },
    nowValue() { return nowMs; },
  };
}

test("shipping Statistics composition delegates freshness to the snapshot-owned target", () => {
  const h = createHarness();

  h.App.applyLocalTicker();
  assert.equal(h.App.statisticsLiveTickerSuspended, false);
  assert.equal(h.elements["stats-total"].textContent, "00:01:45");

  h.advance(6000);
  h.App.applyLocalTicker();

  assert.equal(h.App.statisticsLiveTickerSuspended, true);
  assert.equal(
    h.elements["stats-total"].textContent,
    "00:01:45",
    "expired target must freeze rather than extrapolate through the canonical runtime gate"
  );
  assert.ok(
    h.timers.some((timer) => timer.delay === 1500),
    "stale target must reuse the existing automatic page-refresh coordinator"
  );

  h.App.statisticsAcceptedPayload.exportTicket.live_target.sampled_at_epoch_ms = h.nowValue();
  h.App.resumeStatisticsLiveTicker();
  h.advance(1000);
  h.App.applyLocalTicker();

  assert.equal(h.App.statisticsLiveTickerSuspended, false);
  assert.equal(h.elements["stats-total"].textContent, "00:01:41");
});
