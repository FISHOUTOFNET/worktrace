const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function runtimeState(revision) {
  return {
    ok: true,
    runtime: {
      schema_version: 2,
      surface: "overview",
      scope_report_date: "2026-08-22",
      live_report_date: "2026-08-22",
      snapshot: { revision, id: `sample-${revision}` },
      revisions: { structure: "structure-a", page: `page-${revision}` },
      collector: { live_eligible: false, status: "running", paused: false, display: "记录中" },
      clock: {
        is_live: false,
        duration_semantic: "static_closed",
        display_span_id: `span-${revision}`,
        stable_live_key_hash: `key-${revision}`,
      },
      current_activity: { active: true, activity_id: revision, status: "normal" },
      generations: {
        report_structure: 1,
        classification_catalog: 1,
        settings: 1,
        privacy_catalog: 1,
      },
      database_replacement_epoch: 0,
      runtime_consistent: true,
      needs_full_refresh: false,
    },
  };
}

function harness() {
  let token = 0;
  let nextTimerId = 1;
  let refreshState = null;
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
    validateLiveClock(clock) {
      return clock && typeof clock === "object" ? clock : null;
    },
    recordLiveClockContractViolation() {},
    readLiveClockTarget() { return null; },
    clearLiveClockTarget() {},
    liveTargetCompatibleWithRuntime() { return true; },
    renderLiveDurationTarget() {},
    renderCurrentActivityElement() {},
    computeClockDurationNow() { return 0; },
  };
  app.overview = {
    refreshPolicy: { entryGenerations: ["report_structure"], automaticGenerations: ["report_structure"], deferred: true },
    hasLoadedData: () => !!app.lastOverviewSnapshot,
    refreshEvidence: () => app.lastOverviewSnapshot || null,
    runtimeRefreshIdentity: (runtime) => String(runtime && runtime.liveRevision || ""),
    onRefreshRequested: () => Promise.resolve(null),
    resetGeneration() {},
  };
  app.timeline = {
    refreshPolicy: { entryGenerations: ["report_structure"], automaticGenerations: ["report_structure"], deferred: true },
    hasLoadedData: () => app.timelineLoaded === true,
    refreshEvidence: () => app.lastTimelineData || null,
    reportDate: () => app.timelineDate || null,
    runtimeRefreshIdentity: (runtime) => String(runtime && runtime.liveRevision || ""),
    onRefreshRequested: () => Promise.resolve(null),
    resetGeneration() {},
  };
  app.statistics = {
    refreshPolicy: { entryGenerations: ["report_structure"], automaticGenerations: ["report_structure"], deferred: true, preservePresentation: true },
    hasLoadedData: () => app.statisticsLoaded === true,
    refreshEvidence: () => app.statisticsAcceptedPayload || null,
    automaticRefreshAllowed: () => true,
    runtimeRefreshIdentity: (runtime) => String(runtime && runtime.liveRevision || ""),
    refreshScopeKey: () => {
      const selection = app.statisticsSelection || {};
      return `statistics|${selection.allTime === true ? "all" : "range"}|${selection.dateFrom || ""}|${selection.dateTo || ""}`;
    },
    onRefreshRequested: (options) => app.loadStatisticsExportSummary(options),
    resetGeneration() {
      app.statisticsLoaded = false;
      app.statisticsAcceptedPayload = null;
    },
  };
  app.rules = {
    refreshPolicy: { entryGenerations: ["classification_catalog", "privacy_catalog", "report_structure"], automaticGenerations: ["classification_catalog", "privacy_catalog"], deferred: false },
    hasLoadedData: () => app.rulesLoaded === true,
    refreshEvidence: () => app.lastProjectRulesData || null,
    onPageEntered: () => app.loadProjectRules(),
    onRefreshRequested: () => app.loadProjectRules(),
    resetGeneration() {
      if (typeof app.setRulesLoading === "function") app.setRulesLoading(false);
    },
  };
  app.settings = {
    refreshPolicy: { entryGenerations: ["settings", "privacy_catalog"], automaticGenerations: ["settings", "privacy_catalog"], deferred: false },
    hasLoadedData: () => app.settingsLoaded === true,
    refreshEvidence: () => app.lastSettingsStatus || null,
    onRefreshRequested: () => Promise.resolve(null),
    resetGeneration() {
      if (typeof app.setSettingsLoading === "function") app.setSettingsLoading(false);
    },
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
      get_refresh_state() { return Promise.resolve(refreshState); },
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
  return {
    app,
    timers,
    setRefreshState(value) { refreshState = value; },
  };
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

test("runtime identity changes dirty a fresh deferred page before scheduling recovery", async () => {
  const { app, timers, setRefreshState } = harness();
  app.acceptRefreshStateRuntime(runtimeState("A"));
  app.lastOverviewSnapshot = { version: 1 };
  app.overview.onRefreshRequested = () => {
    app.lastOverviewSnapshot = { version: 2 };
    return Promise.resolve({ ok: true });
  };
  await app.refreshActivePage(null, { navigation: true }, "overview");
  assert.equal(app.pageNeedsRefresh("overview"), false);

  setRefreshState(runtimeState("B"));
  await app.runRevisionCheck();

  assert.equal(app.pageNeedsRefresh("overview"), true);
  const deferred = pendingTimer(timers);
  assert.ok(deferred);
  assert.equal(deferred.ms, 1500);
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
