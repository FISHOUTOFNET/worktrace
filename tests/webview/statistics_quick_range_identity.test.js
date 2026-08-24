const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness(initialDate) {
  let now = initialDate.slice();
  class MutableDate extends Date {
    constructor(...args) {
      if (args.length === 0) super(...now);
      else super(...args);
    }
    static setLocal(...args) { now = args; }
  }

  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      const attrs = new Map();
      const listeners = new Map();
      elements.set(id, {
        id,
        hidden: false,
        disabled: false,
        value: "",
        textContent: "",
        innerHTML: "",
        className: "",
        tabIndex: 0,
        style: {},
        addEventListener(name, handler) {
          if (!listeners.has(name)) listeners.set(name, []);
          listeners.get(name).push(handler);
        },
        setAttribute(name, value) { attrs.set(name, String(value)); },
        getAttribute(name) { return attrs.has(name) ? attrs.get(name) : null; },
        focus() {},
      });
    }
    return elements.get(id);
  }

  const document = { getElementById: element };
  const appWindow = {
    WorkTraceApp: {},
    setTimeout,
    clearTimeout,
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
    JSON,
    Date: MutableDate,
    parseInt,
    window: appWindow,
    document,
  };
  vm.createContext(context);

  const App = appWindow.WorkTraceApp;
  let requestNumber = 0;
  Object.assign(App, {
    statisticsLoaded: false,
    statisticsLoading: false,
    statisticsExportSaving: false,
    statisticsAcceptedPayload: null,
    statisticsSnapshotRevision: "",
    statisticsLoadPromise: null,
    requestCoordinator: {
      beginLatest() { requestNumber += 1; return requestNumber; },
      isCurrent(token) { return token === requestNumber; },
    },
    handleResult(result) { return result && result.ok !== false ? result : null; },
    escapeHtml(value) { return String(value); },
    formatDuration() { return "00:00:00"; },
  });
  App.bridge = {
    getStatisticsExportSummary() { return Promise.resolve(null); },
    exportStatisticsCsv() { return Promise.resolve({ ok: true }); },
  };

  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/statistics.js"), "utf8"),
    context,
    { filename: "statistics.js" }
  );

  function pressed(type) {
    return element(`statistics-${type}-btn`).getAttribute("aria-pressed");
  }
  function assertOnlyPressed(type) {
    for (const candidate of ["today", "week", "month", "all"]) {
      assert.equal(pressed(candidate), candidate === type ? "true" : "false");
    }
  }
  function assertNonePressed() {
    for (const candidate of ["today", "week", "month", "all"]) {
      assert.equal(pressed(candidate), "false");
    }
  }

  return { App, MutableDate, element, assertOnlyPressed, assertNonePressed };
}

test("Monday keeps Today and This Week mutually exclusive", async () => {
  const { App, assertOnlyPressed } = harness([2026, 7, 24, 12, 0, 0]);
  App.initStatisticsDefaults();
  assertOnlyPressed("week");

  await App.applyStatisticsQuickRange("today");
  assertOnlyPressed("today");

  await App.applyStatisticsQuickRange("week");
  assertOnlyPressed("week");
});

test("month-start Monday never lights overlapping presets together", async () => {
  const { App, assertOnlyPressed } = harness([2026, 5, 1, 12, 0, 0]);
  App.initStatisticsDefaults();
  assertOnlyPressed("week");

  await App.applyStatisticsQuickRange("month");
  assertOnlyPressed("month");

  await App.applyStatisticsQuickRange("today");
  assertOnlyPressed("today");
});

test("manual range equal to a shortcut remains custom", async () => {
  const { App, element, assertNonePressed } = harness([2026, 7, 28, 12, 0, 0]);
  App.initStatisticsDefaults();
  await App.applyStatisticsQuickRange("today");

  element("statistics-date-from").value = "2026-08-24";
  element("statistics-date-to").value = "2026-08-28";
  App.handleStatisticsDraftDateChange();
  await App.applyStatisticsDraftSelection();

  assert.deepEqual(JSON.parse(JSON.stringify(App.statisticsSelection)), {
    allTime: false,
    dateFrom: "2026-08-24",
    dateTo: "2026-08-28",
  });
  assertNonePressed();
});

test("dynamic shortcut rebases across local midnight", async () => {
  const { App, MutableDate, assertOnlyPressed } = harness([2026, 7, 24, 23, 59, 0]);
  App.initStatisticsDefaults();
  await App.applyStatisticsQuickRange("today");
  assertOnlyPressed("today");

  MutableDate.setLocal(2026, 7, 25, 0, 1, 0);
  App.statisticsLoaded = true;
  await App.statistics.onRefreshRequested({});

  assert.deepEqual(JSON.parse(JSON.stringify(App.statisticsSelection)), {
    allTime: false,
    dateFrom: "2026-08-25",
    dateTo: "2026-08-25",
  });
  assertOnlyPressed("today");
});

test("custom range stays fixed across local midnight", async () => {
  const { App, MutableDate, element, assertNonePressed } = harness([2026, 7, 24, 23, 59, 0]);
  App.initStatisticsDefaults();
  element("statistics-date-from").value = "2026-08-01";
  element("statistics-date-to").value = "2026-08-24";
  App.handleStatisticsDraftDateChange();
  await App.applyStatisticsDraftSelection();
  assertNonePressed();

  MutableDate.setLocal(2026, 7, 25, 0, 1, 0);
  App.statisticsLoaded = true;
  await App.statistics.onRefreshRequested({});

  assert.deepEqual(JSON.parse(JSON.stringify(App.statisticsSelection)), {
    allTime: false,
    dateFrom: "2026-08-01",
    dateTo: "2026-08-24",
  });
  assertNonePressed();
});
