const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  let token = 0;
  let nextTimerId = 1;
  const timers = [];
  const app = {
    currentPage: "overview",
    heartbeatTimer: null,
    shellVisible: true,
    localTodayStr() { return "2026-08-22"; },
    runtimeReportDateForPage(page, date) {
      return page === "timeline" ? String(date || app.timelineDate || "2026-08-22") : "2026-08-22";
    },
    handleResult(result, onError) {
      if (!result || result.ok === false) {
        return typeof onError === "function" ? onError("failed") : null;
      }
      return result;
    },
    requestCoordinator: {
      beginLatest() { token += 1; return token; },
      isCurrent() { return true; },
      bumpDataEpoch() { token += 1; },
    },
    showStatus() {},
    showError() {},
    clearError() {},
    showGlobalAlert() {},
    clearGlobalAlert() {},
    validateLiveClock() { return null; },
    recordLiveClockContractViolation() {},
    readLiveClockTarget() { return null; },
    clearLiveClockTarget() {},
    liveTargetCompatibleWithRuntime() { return true; },
    renderLiveDurationTarget() {},
    renderCurrentActivityElement() {},
    computeClockDurationNow() { return 0; },
  };

  const document = {
    readyState: "loading",
    addEventListener() {},
    getElementById(id) {
      if (id === "statistics-project-filter") return { value: "" };
      return null;
    },
    querySelectorAll() { return []; },
  };

  const context = {
    Promise,
    Error,
    String,
    Number,
    Boolean,
    Array,
    Object,
    Math,
    Date,
    JSON,
    parseInt,
    document,
    setInterval() { return 1; },
    clearInterval() {},
  };
  context.window = context;
  context.WorkTraceApp = app;
  context.pywebview = {
    api: {
      get_refresh_state() { return Promise.resolve(null); },
      get_status() {
        return Promise.resolve({ ok: true, status: "running", paused: false, display: "记录中" });
      },
    },
  };
  context.addEventListener = function () {};
  context.removeEventListener = function () {};
  context.setTimeout = function (fn, ms) {
    const timer = { id: nextTimerId++, fn, ms, cancelled: false };
    timers.push(timer);
    return timer.id;
  };
  context.clearTimeout = function (id) {
    const timer = timers.find((item) => item.id === id);
    if (timer) timer.cancelled = true;
  };

  const lifecycleSource = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/page_lifecycle.js"),
    "utf8"
  );
  vm.runInNewContext(lifecycleSource, context, { filename: "page_lifecycle.js" });
  const source = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/init_fd_work_v5.js"),
    "utf8"
  );
  vm.runInNewContext(source, context, { filename: "init_fd_work_v5.js" });
  app.rules = Object.assign({}, app.rules, {
    onRefreshRequested() {
      return typeof app.loadProjectRules === "function"
        ? app.loadProjectRules()
        : Promise.resolve(null);
    },
  });
  return { app, timers };
}

function pendingTimer(timers) {
  return timers.find((timer) => !timer.cancelled);
}

test("resolved stale page data does not clear a dirty refresh", async () => {
  const { app } = harness();
  app.currentPage = "rules";
  app.rulesLoaded = true;
  app.lastProjectRulesData = { version: 1 };
  app.loadProjectRules = () => Promise.resolve(null);

  await app.refreshActivePage(null, { navigation: true }, "rules");
  assert.equal(app.pageNeedsRefresh("rules"), true);

  app.loadProjectRules = () => {
    app.lastProjectRulesData = { version: 2 };
    return Promise.resolve({ ok: true });
  };
  await app.refreshActivePage(null, { navigation: true }, "rules");
  assert.equal(app.pageNeedsRefresh("rules"), false);
});

test("an older refresh epoch cannot overwrite a newer dirty epoch", async () => {
  const { app } = harness();
  app.currentPage = "rules";
  app.rulesLoaded = true;
  app.lastProjectRulesData = { version: 1 };
  let release;
  app.loadProjectRules = () => new Promise((resolve) => { release = resolve; });

  const pending = app.refreshActivePage(null, { navigation: true }, "rules");
  app.resetClientGeneration("test_replacement");
  app.rulesLoaded = true;
  app.lastProjectRulesData = { version: 2 };
  release({ ok: true });
  await pending;

  assert.equal(app.pageNeedsRefresh("rules"), true);
});

test("generation reset releases Rules and Settings loading state", () => {
  const { app } = harness();
  app.rulesLoading = true;
  app.settingsLoading = true;
  app.setRulesLoading = (loading) => { app.rulesLoading = !!loading; };
  app.setSettingsLoading = (loading) => { app.settingsLoading = !!loading; };

  app.resetClientGeneration("test_replacement");

  assert.equal(app.rulesLoading, false);
  assert.equal(app.settingsLoading, false);
});

test("failed automatic Statistics refresh retries and recovers without a new generation", async () => {
  const { app, timers } = harness();
  app.currentPage = "statistics";
  app.statisticsLoaded = true;
  app.statisticsSelection = { allTime: true, dateFrom: "", dateTo: "" };
  app.statisticsAcceptedPayload = { revision: "old" };
  app.statisticsLiveTickerSuspended = true;
  let attempts = 0;
  app.loadStatisticsExportSummary = () => {
    attempts += 1;
    if (attempts === 1) return Promise.reject(new Error("transient failure"));
    app.statisticsAcceptedPayload = { revision: "new" };
    app.statisticsLiveTickerSuspended = false;
    return Promise.resolve({ ok: true });
  };

  await app.refreshCurrentPageData(null, { automatic: true, preservePresentation: true });
  assert.equal(app.pageNeedsRefresh("statistics"), true);
  const retry = pendingTimer(timers);
  assert.ok(retry);
  assert.equal(retry.ms, 5000);

  retry.fn();
  if (app.activePageRefreshPromise) await app.activePageRefreshPromise;

  assert.equal(attempts, 2);
  assert.equal(app.pageNeedsRefresh("statistics"), false);
  assert.equal(app.statisticsLiveTickerSuspended, false);
});

test("a Statistics retry is scoped to the selection that scheduled it", async () => {
  const { app, timers } = harness();
  app.currentPage = "statistics";
  app.statisticsLoaded = true;
  app.statisticsSelection = { allTime: true, dateFrom: "", dateTo: "" };
  app.statisticsAcceptedPayload = { revision: "old" };
  let attempts = 0;
  app.loadStatisticsExportSummary = () => {
    attempts += 1;
    return Promise.reject(new Error("transient failure"));
  };

  await app.refreshCurrentPageData(null, { automatic: true, preservePresentation: true });
  const retry = pendingTimer(timers);
  assert.ok(retry);

  app.statisticsSelection = {
    allTime: false,
    dateFrom: "2026-08-01",
    dateTo: "2026-08-21",
  };
  retry.fn();
  await Promise.resolve();

  assert.equal(attempts, 1);
});
