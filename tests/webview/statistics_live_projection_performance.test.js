const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function trackedCell(text) {
  let value = text;
  let writes = 0;
  return {
    get textContent() { return value; },
    set textContent(next) { writes += 1; value = next; },
    writes() { return writes; },
    reset() { writes = 0; },
  };
}

function trackedStyle(width) {
  let value = width;
  let writes = 0;
  return {
    get width() { return value; },
    set width(next) { writes += 1; value = next; },
    writes() { return writes; },
    reset() { writes = 0; },
  };
}

function row(group, keyOverride) {
  const duration = trackedCell(group.duration);
  const percentage = trackedCell(`${group.percentage}%`);
  const style = trackedStyle(`${group.percentage}%`);
  const cells = [{}, duration, {}, percentage];
  return {
    children: cells,
    getAttribute(name) {
      return name === "data-statistics-key" ? (keyOverride || group.key) : null;
    },
    querySelector(selector) {
      return selector === ".stats-share-bar i" ? { style } : null;
    },
    duration,
    percentage,
    style,
  };
}

function formatDuration(value) {
  value = Math.max(0, Number(value) || 0);
  const h = String(Math.floor(value / 3600)).padStart(2, "0");
  const m = String(Math.floor(value % 3600 / 60)).padStart(2, "0");
  const s = String(Math.floor(value % 60)).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function loadModule(context, name) {
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", name), "utf8"),
    context,
    { filename: name }
  );
}

function harness(count = 1000, options = {}) {
  let nowMs = 1_000_005_000;
  const groups = Array.from({ length: count }, (_, index) => ({
    key: `K${index}`,
    display_name: `K${index}`,
    duration_seconds: 100,
    duration: "00:01:40",
    percentage: 0.1,
  }));
  const fileGroups = groups.map((group) => ({ ...group, key: `F${group.key}` }));
  const appGroups = groups.map((group) => ({ ...group, key: `A${group.key}` }));
  const projectRows = groups.map((group, index) => row(
    group,
    options.mismatchProjectIndex === index ? "stale-key" : null
  ));
  const fileRows = fileGroups.map((group) => row(group));
  const appRows = appGroups.map((group) => row(group));
  let projectQueries = 0;
  let fileQueries = 0;
  let appQueries = 0;
  const total = trackedCell("27:46:40");
  const elements = {
    "stats-total": total,
    "stats-by-project": {
      querySelectorAll() { projectQueries += 1; return projectRows; },
    },
    "stats-by-file": {
      querySelectorAll() { fileQueries += 1; return fileRows; },
    },
    "stats-by-app": {
      querySelectorAll() { appQueries += 1; return appRows; },
    },
  };
  const App = {
    currentPage: "statistics",
    statisticsLiveTickerSuspended: false,
    statisticsLastLiveRenderKey: "",
    formatDuration,
    escapeHtml(value) { return String(value || ""); },
  };
  const FakeDate = class extends Date {
    static now() { return nowMs; }
  };
  const document = {
    getElementById(id) { return elements[id] || null; },
  };
  const window = {
    document,
    setTimeout,
    clearTimeout,
    WorkTraceApp: App,
  };
  const context = {
    window,
    document,
    Date: FakeDate,
    Math,
    Number,
    String,
    Array,
    Object,
    JSON,
    Promise,
    parseInt,
    parseFloat,
  };
  vm.createContext(context);
  loadModule(context, "statistics.js");
  loadModule(context, "statistics_live_projection.js");
  App.statisticsAcceptedPayload = {
    filters: { dateFrom: "2026-08-25", dateTo: "2026-08-25", projectId: "" },
    summary: {
      snapshot_revision: "r1",
      total_duration_seconds: 100000,
      by_project: groups,
      by_file: fileGroups,
      by_app: appGroups,
      by_status: [],
    },
    exportTicket: {
      revision: "r1",
      live_target: {
        enabled: true,
        ticking: true,
        sampled_at_epoch_ms: 1_000_000_000,
        elapsed_seconds_at_sample: 10,
        project_key: "K0",
        file_key: "FK0",
        app_key: "AK0",
      },
    },
  };
  return {
    App,
    total,
    projectRows,
    fileRows,
    appRows,
    queries() { return [projectQueries, fileQueries, appQueries]; },
    advance(ms) { nowMs += ms; },
  };
}

function resetWrites(harnessValue) {
  harnessValue.total.reset();
  [harnessValue.projectRows, harnessValue.fileRows, harnessValue.appRows]
    .forEach((rows) => rows.forEach((item) => {
      item.duration.reset();
      item.percentage.reset();
      item.style.reset();
    }));
}

test("Statistics live tick caches row discovery and skips unchanged DOM writes", () => {
  const h = harness();
  assert.equal(h.App.statistics.refreshPolicy.deferred, false);

  h.App.statistics.applyLocalTick();
  assert.deepEqual(h.queries(), [1, 1, 1]);
  assert.equal(h.total.writes(), 1);
  assert.equal(h.projectRows[0].duration.writes(), 1);
  assert.equal(h.fileRows[0].duration.writes(), 1);
  assert.equal(h.appRows[0].duration.writes(), 1);
  assert.equal(h.projectRows[999].duration.writes(), 0);
  assert.equal(h.projectRows[999].percentage.writes(), 0);
  assert.equal(h.projectRows[999].style.writes(), 0);

  resetWrites(h);
  h.advance(1000);
  h.App.statistics.applyLocalTick();

  assert.deepEqual(h.queries(), [1, 1, 1], "subsequent ticks reuse cached row references");
  assert.equal(h.total.writes(), 1);
  assert.equal(h.projectRows[0].duration.writes(), 1);
  assert.equal(h.fileRows[0].duration.writes(), 1);
  assert.equal(h.appRows[0].duration.writes(), 1);
  assert.equal(h.projectRows[999].duration.writes(), 0);
  assert.equal(h.projectRows[999].percentage.writes(), 0);
  assert.equal(h.projectRows[999].style.writes(), 0);
});

test("Statistics structure transition freezes old live target without deferred refresh policy", () => {
  const h = harness(2);
  h.App.statistics.onRuntimeTransition({
    source: "refresh-state",
    reportStructureChanged: true,
  });

  assert.equal(h.App.statisticsLiveTickerSuspended, true);
  assert.equal(h.App.statistics.refreshPolicy.deferred, false);
  assert.equal(h.App.statistics.refreshPolicy.preservePresentation, true);
});

test("Statistics live row mismatch keeps authoritative self-heal path", () => {
  const h = harness(2, { mismatchProjectIndex: 0 });
  const result = h.App.statistics.applyLocalTick();

  assert.deepEqual(result, {
    refreshRequired: true,
    reason: "statistics_live_projection_mismatch",
  });
  assert.deepEqual(h.queries(), [1, 1, 1]);
});