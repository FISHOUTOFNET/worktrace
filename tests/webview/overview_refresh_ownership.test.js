const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  let runtime = { liveRevision: "A", pageRevision: "page-A" };
  const elements = {
    "kpi-total": {},
    "current-activity": { disabled: false, onclick: null },
    "overview-project-bar": {
      hidden: false,
      innerHTML: "",
      setAttribute() {},
    },
    "recent-list": {
      innerHTML: "",
      querySelectorAll() { return []; },
    },
  };
  const document = {
    getElementById(id) { return elements[id] || null; },
  };
  const App = {
    currentPage: "overview",
    validateLiveClock() { return null; },
    clearLiveClockTarget() {},
    renderDurationProjected() {},
    renderCurrentActivityElement(target, activity) {
      if (target) target.renderedActivity = activity;
    },
    formatCompactHours() { return "0h"; },
    formatDuration() { return "00:00:00"; },
    formatProjectLabel(name) { return name || ""; },
    formatStartTimeOnly() { return ""; },
    escapeHtml(value) { return String(value == null ? "" : value); },
    requestCoordinator: {
      beginLatest() { return 1; },
      isCurrent() { return true; },
    },
    bridge: {
      getOverview() {
        return Promise.resolve({
          ok: true,
          overview: bundle("requested"),
          date: "2026-08-23",
          current_session: session("requested"),
          runtime: { schema_version: 2 },
        });
      },
    },
    handleResult(result) { return result; },
    acceptPagePayloadRuntime() { return true; },
    liveRuntimeStore: { get() { return runtime; } },
    showError() {},
  };
  const window = { WorkTraceApp: App, document };
  const context = {
    window,
    document,
    Object,
    String,
    Array,
    Number,
    Math,
    Date,
    parseInt,
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/overview.js"), "utf8"),
    context,
    { filename: "overview.js" }
  );
  return {
    App,
    elements,
    setRuntime(value) { runtime = value; },
  };
}

function session(marker) {
  return {
    marker,
    projection_instance_key: `session-${marker}`,
    start_time: "2026-08-23 09:00:00",
  };
}

function bundle(marker) {
  return {
    marker,
    today_total_seconds: 0,
    current_activity: { marker, active: true, status: "normal" },
    current_session: session(marker),
    project_distribution: { total_seconds: 0, segments: [] },
    recent: [],
  };
}

test("Overview authoritative snapshots are never suppressed", async () => {
  const { App } = harness();

  App.showOverview(bundle("first"));
  App.showOverview(bundle("second"));
  assert.equal(App.lastOverviewSnapshot.marker, "second");
  assert.equal(App.suppressNextOverviewCollectionRefresh, undefined);

  await App.overview.onRefreshRequested({ automatic: true });
  assert.equal(App.lastOverviewSnapshot.marker, "requested");
});

test("Overview heartbeat overlay does not mutate the authoritative snapshot", () => {
  const { App, elements, setRuntime } = harness();
  App.showOverview(bundle("A"));
  assert.equal(App.overviewCommittedRuntimeIdentity, "page-A");
  assert.equal(elements["current-activity"].disabled, false);
  assert.equal(typeof elements["current-activity"].onclick, "function");

  setRuntime({ liveRevision: "B", pageRevision: "page-B" });
  App.overview.updateCurrentActivity(
    { marker: "B", active: true, status: "normal" },
    { render: true }
  );

  assert.equal(App.lastOverviewSnapshot.current_activity.marker, "A");
  assert.equal(elements["current-activity"].renderedActivity.marker, "B");
  assert.equal(elements["current-activity"].disabled, true);
  assert.equal(elements["current-activity"].onclick, null);
});

test("Overview runtime refresh identity follows authoritative page revision", () => {
  const { App } = harness();
  assert.equal(App.overview.runtimeRefreshIdentity({ pageRevision: "page-a" }), "page-a");
  assert.equal(App.overview.runtimeRefreshIdentity({ pageRevision: "page-b" }), "page-b");
});
