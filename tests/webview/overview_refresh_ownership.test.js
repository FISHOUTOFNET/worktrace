const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  const elements = {
    "kpi-total": {},
    "current-activity": {},
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
    renderCurrentActivityElement() {},
    formatCompactHours() { return "0h"; },
    formatDuration() { return "00:00:00"; },
    formatProjectLabel(name) { return name || ""; },
    formatStartTimeOnly() { return ""; },
    escapeHtml(value) { return String(value == null ? "" : value); },
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
  return { App };
}

function bundle(marker) {
  return {
    marker,
    today_total_seconds: 0,
    current_activity: {},
    project_distribution: { total_seconds: 0, segments: [] },
    recent: [],
  };
}

test("Overview consumes live-only collection suppression once", () => {
  const { App } = harness();
  App.overview.onRuntimeTransition({ source: "refresh-state", liveChanged: true });

  App.showOverview(bundle("suppressed"));
  assert.equal(App.lastOverviewSnapshot, undefined);
  assert.equal(App.suppressNextOverviewCollectionRefresh, false);

  App.showOverview(bundle("accepted"));
  assert.equal(App.lastOverviewSnapshot.marker, "accepted");
});

test("Overview structural and manual refreshes bypass live suppression", () => {
  const { App } = harness();
  App.overview.onRuntimeTransition({ source: "refresh-state", liveChanged: true });
  App.overview.onRuntimeTransition({
    source: "refresh-state",
    structureChanged: true,
    liveChanged: true,
  });
  App.showOverview(bundle("structural"));
  assert.equal(App.lastOverviewSnapshot.marker, "structural");

  App.overview.onRuntimeTransition({ source: "refresh-state", liveChanged: true });
  App.overview.onRefreshRequested({ automatic: false });
  App.showOverview(bundle("manual"));
  assert.equal(App.lastOverviewSnapshot.marker, "manual");
});

