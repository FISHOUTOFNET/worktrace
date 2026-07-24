const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

function harness() {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) {
      elements.set(id, {
        id,
        hidden: false,
        disabled: false,
        value: "",
        textContent: "",
        innerHTML: "",
        className: "",
        dataset: {},
        addEventListener() {},
      });
    }
    return elements.get(id);
  }

  const context = {
    Promise,
    Error,
    String,
    Number,
    Array,
    Date,
    Math,
    setImmediate,
    window: { WorkTraceApp: {} },
    document: {
      getElementById: element,
    },
  };
  vm.createContext(context);

  const App = context.window.WorkTraceApp;
  let requestNumber = 0;
  Object.assign(App, {
    statisticsLoaded: false,
    statisticsLoading: false,
    statisticsExportSaving: false,
    statisticsAcceptedPayload: null,
    statisticsSnapshotRevision: "",
    statisticsLoadPromise: null,
    requestCoordinator: {
      beginLatest() { requestNumber += 1; return { requestNumber }; },
      isCurrent() { return true; },
    },
    handleResult(result, onError) {
      if (!result || result.ok === false) {
        onError((result && result.message) || "操作失败");
        return null;
      }
      return result;
    },
    safeText(value, fallback) {
      return value === undefined || value === null ? fallback : String(value);
    },
    escapeHtml(value) { return String(value); },
    localTodayStr() { return "2026-07-17"; },
    shiftDate(value) { return value; },
  });
  App.bridge = {
    getStatisticsExportSummary: () => Promise.resolve({
      ok: true,
      summary: {
        date_from: "2026-07-01",
        date_to: "2026-07-17",
        total_duration: "01:00:00",
        activity_count: 4,
        project_count: 2,
        app_count: 2,
        by_project: [],
        by_app: [],
        by_status: [],
        export_preview: { included_activity_count: 4, included_duration: "01:00:00", available_formats: ["CSV"] },
      },
      export_ticket: {
        date_from: "2026-07-01",
        date_to: "2026-07-17",
        revision: "revision-1",
      },
    }),
    exportStatisticsCsv: () => Promise.resolve({
      ok: true,
      filename: "worktrace.csv",
      activity_count: 4,
      duration: "01:00:00",
    }),
  };

  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/statistics.js"), "utf8"),
    context,
    { filename: "statistics.js" }
  );

  element("statistics-date-from").value = "2026-07-01";
  element("statistics-date-to").value = "2026-07-17";
  return { App, element };
}

test("accepted statistics payload is the sole export ticket", async () => {
  const { App } = harness();

  await App.loadStatisticsExportSummary();

  assert.deepEqual(
    JSON.parse(JSON.stringify(App.statisticsAcceptedPayload.exportTicket)),
    {
      date_from: "2026-07-01",
      date_to: "2026-07-17",
      revision: "revision-1",
    }
  );
  assert.equal(App.statisticsSnapshotRevision, "revision-1");
  assert.equal(App.statisticsLoaded, true);
  assert.equal(App.statisticsLoading, false);
});

test("export passes only the accepted date range and revision", async () => {
  const { App } = harness();
  const calls = [];
  App.statisticsAcceptedPayload = {
    exportTicket: { date_from: "2026-07-01", date_to: "2026-07-17", revision: "revision-1", project_id: "7" },
  };
  App.bridge.exportStatisticsCsv = (...args) => {
    calls.push(args);
    return Promise.resolve({ ok: true, filename: "worktrace.csv", activity_count: 4, duration: "01:00:00" });
  };

  App.exportStatisticsCsv();
  await flush();
  await flush();

  assert.deepEqual(calls, [["2026-07-01", "2026-07-17", "revision-1", "7"]]);
  assert.equal(App.statisticsExportSaving, false);
});

test("loading blocks export without discarding the accepted snapshot", () => {
  const { App } = harness();
  let calls = 0;
  const accepted = {
    exportTicket: { date_from: "2026-07-01", date_to: "2026-07-17", revision: "revision-1" },
  };
  App.statisticsAcceptedPayload = accepted;
  App.statisticsLoading = true;
  App.bridge.exportStatisticsCsv = () => {
    calls += 1;
    return Promise.resolve({ ok: true });
  };

  App.exportStatisticsCsv();

  assert.equal(calls, 0);
  assert.equal(App.statisticsAcceptedPayload, accepted);
});

test("in-flight export guard suppresses duplicate clicks", async () => {
  const { App } = harness();
  const pending = deferred();
  let calls = 0;
  App.statisticsAcceptedPayload = {
    exportTicket: { date_from: "2026-07-01", date_to: "2026-07-17", revision: "revision-1" },
  };
  App.bridge.exportStatisticsCsv = () => {
    calls += 1;
    return pending.promise;
  };

  App.exportStatisticsCsv();
  App.exportStatisticsCsv();
  assert.equal(calls, 1);
  assert.equal(App.statisticsExportSaving, true);

  pending.resolve({ ok: true, filename: "worktrace.csv", activity_count: 4, duration: "01:00:00" });
  await flush();
  await flush();
  assert.equal(App.statisticsExportSaving, false);
});

test("changing the selected range invalidates the previous export ticket", () => {
  const { App } = harness();
  App.statisticsLoaded = true;
  App.statisticsAcceptedPayload = {
    exportTicket: { date_from: "2026-07-01", date_to: "2026-07-17", revision: "revision-1" },
  };
  App.statisticsSnapshotRevision = "revision-1";

  App.invalidateStatisticsSelection();

  assert.equal(App.statisticsLoaded, false);
  assert.equal(App.statisticsAcceptedPayload, null);
  assert.equal(App.statisticsSnapshotRevision, "");
});
