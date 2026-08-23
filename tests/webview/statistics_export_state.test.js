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

class FixedDate extends Date {
  constructor(...args) {
    if (args.length === 0) super(2026, 6, 17, 12, 0, 0);
    else super(...args);
  }
}

function summaryResult(dateFrom, dateTo, projectId = "", revision = "revision-1") {
  const resolvedFrom = dateFrom || "1970-01-01";
  const resolvedTo = dateTo || "2026-07-17";
  return {
    ok: true,
    summary: {
      date_from: resolvedFrom,
      date_to: resolvedTo,
      total_duration: "01:00:00",
      session_count: 4,
      project_count: 2,
      app_count: 2,
      by_project: [{
        key: "project:client", display_name: "Client", duration: "01:00:00",
        record_count: 3, activity_count: 4, percentage: 100,
      }],
      by_file: [
        { key: "file:client", display_name: "client.docx", duration: "00:50:00", record_count: 3, activity_count: 4, percentage: 83.3 },
        { key: "file:excluded", display_name: "已排除", duration: "00:10:00", record_count: 1, activity_count: 1, percentage: 16.7 },
      ],
      by_app: [{ key: "Word", display_name: "Word", duration: "01:00:00", record_count: 3, activity_count: 4, percentage: 100 }],
      by_status: [],
      export_preview: { session_count: 4, included_duration: "01:00:00" },
    },
    export_ticket: {
      date_from: resolvedFrom,
      date_to: resolvedTo,
      revision,
      project_id: projectId,
    },
  };
}

function harness() {
  const elements = new Map();
  const timers = new Map();
  const statisticsCalls = [];
  let nextTimer = 0;
  let latestRequest = 0;
  let activeElement = null;

  function element(id) {
    if (!elements.has(id)) {
      const listeners = new Map();
      const attributes = new Map();
      const node = {
        id,
        hidden: false,
        disabled: false,
        type: id.startsWith("statistics-date-") ? "date" : "text",
        tabIndex: 0,
        value: "",
        textContent: "",
        innerHTML: "",
        className: "",
        dataset: {},
        selectedIndex: 0,
        options: [{ text: "全部项目" }],
        addEventListener(name, handler) {
          if (!listeners.has(name)) listeners.set(name, []);
          listeners.get(name).push(handler);
        },
        dispatch(name, event = {}) {
          for (const handler of listeners.get(name) || []) {
            handler.call(node, {
              target: node,
              currentTarget: node,
              key: event.key || "",
              preventDefault() {},
              ...event,
            });
          }
        },
        focus() { activeElement = node; },
        setAttribute(name, value) { attributes.set(name, String(value)); },
        getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
      };
      elements.set(id, node);
    }
    return elements.get(id);
  }

  const document = {
    get activeElement() { return activeElement; },
    getElementById: element,
  };
  const appWindow = {
    WorkTraceApp: {},
    setTimeout(handler, delay) {
      nextTimer += 1;
      timers.set(nextTimer, { handler, delay });
      return nextTimer;
    },
    clearTimeout(timerId) { timers.delete(timerId); },
  };
  const context = {
    Promise,
    Error,
    String,
    Number,
    Array,
    Math,
    Date: FixedDate,
    setImmediate,
    parseInt,
    window: appWindow,
    document,
  };
  vm.createContext(context);

  const App = appWindow.WorkTraceApp;
  Object.assign(App, {
    statisticsLoaded: false,
    statisticsLoading: false,
    statisticsExportSaving: false,
    statisticsAcceptedPayload: null,
    statisticsSnapshotRevision: "",
    statisticsLoadPromise: null,
    requestCoordinator: {
      beginLatest() {
        latestRequest += 1;
        return { requestNumber: latestRequest };
      },
      isCurrent(token) { return token.requestNumber === latestRequest; },
    },
    handleResult(result, onError) {
      if (!result || result.ok === false) {
        onError((result && result.message) || "操作失败");
        return null;
      }
      return result;
    },
    escapeHtml(value) { return String(value); },
    formatDuration() { return "00:00:00"; },
    loadProjects() { return Promise.resolve([]); },
  });
  App.bridge = {
    getStatisticsExportSummary(dateFrom, dateTo, projectId) {
      statisticsCalls.push([dateFrom, dateTo, projectId]);
      return Promise.resolve(summaryResult(dateFrom, dateTo, projectId));
    },
    exportStatisticsCsv: () => Promise.resolve({ ok: true, filename: "worktrace.csv" }),
  };

  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/statistics.js"), "utf8"),
    context,
    { filename: "statistics.js" }
  );

  element("statistics-results").hidden = true;
  element("stats-export-action-btn").disabled = true;

  function runTimers() {
    const pending = Array.from(timers.entries());
    timers.clear();
    pending.forEach(([, timer]) => timer.handler());
  }

  function seedAcceptedPresentation() {
    App.statisticsLoaded = true;
    App.statisticsAcceptedPayload = {
      summary: summaryResult("2026-07-13", "2026-07-17").summary,
      exportTicket: {
        date_from: "2026-07-13",
        date_to: "2026-07-17",
        revision: "old-revision",
        project_id: "",
      },
    };
    App.statisticsSnapshotRevision = "old-revision";
    element("statistics-results").hidden = false;
    element("stats-total").textContent = "09:00:00";
    element("stats-by-project").innerHTML = "<tr><td>旧结果</td></tr>";
    App.setStatisticsLoading(false);
  }

  return { App, element, runTimers, seedAcceptedPresentation, statisticsCalls, activeElement: () => activeElement };
}

test("first initialization defaults to Monday through today without querying", () => {
  const { App, element, statisticsCalls } = harness();
  App.initStatisticsDefaults();
  assert.deepEqual(JSON.parse(JSON.stringify(App.statisticsSelection)), {
    allTime: false,
    dateFrom: "2026-07-13",
    dateTo: "2026-07-17",
  });
  assert.deepEqual(JSON.parse(JSON.stringify(App.statisticsDraftSelection)), {
    allTime: false,
    dateFrom: "2026-07-13",
    dateTo: "2026-07-17",
  });
  assert.equal(element("statistics-date-from").value, "2026-07-13");
  assert.equal(element("statistics-date-to").value, "2026-07-17");
  assert.equal(element("statistics-date-from").type, "date");
  assert.equal(element("statistics-date-from").getAttribute("data-empty"), "false");
  assert.equal(element("statistics-week-btn").getAttribute("aria-pressed"), "true");
  assert.equal(statisticsCalls.length, 0);
});

test("today quick range queries today through today", async () => {
  const { App, element, statisticsCalls } = harness();
  App.initStatisticsDefaults();
  await App.applyStatisticsQuickRange("today");
  assert.deepEqual(statisticsCalls.at(-1), ["2026-07-17", "2026-07-17", ""]);
  assert.equal(statisticsCalls.length, 1);
  assert.equal(element("statistics-today-btn").getAttribute("aria-pressed"), "true");
});

test("week quick range queries Monday through today", async () => {
  const { App, element, statisticsCalls } = harness();
  App.initStatisticsDefaults();
  await App.applyStatisticsQuickRange("week");
  assert.deepEqual(statisticsCalls.at(-1), ["2026-07-13", "2026-07-17", ""]);
  assert.equal(statisticsCalls.length, 1);
  assert.equal(element("statistics-week-btn").getAttribute("aria-pressed"), "true");
});

test("month quick range queries month start through today", async () => {
  const { App, element, statisticsCalls } = harness();
  App.initStatisticsDefaults();
  await App.applyStatisticsQuickRange("month");
  assert.deepEqual(statisticsCalls.at(-1), ["2026-07-01", "2026-07-17", ""]);
  assert.equal(statisticsCalls.length, 1);
  assert.equal(element("statistics-month-btn").getAttribute("aria-pressed"), "true");
});

test("all quick range keeps native date controls and controlled empty presentation", async () => {
  const { App, element, statisticsCalls } = harness();
  App.initStatisticsDefaults();
  await App.applyStatisticsQuickRange("all");
  assert.deepEqual(statisticsCalls.at(-1), ["", "", ""]);
  assert.equal(statisticsCalls.length, 1);
  assert.equal(element("statistics-date-from").value, "");
  assert.equal(element("statistics-date-to").value, "");
  assert.equal(element("statistics-date-from").type, "date");
  assert.equal(element("statistics-date-to").type, "date");
  assert.equal(element("statistics-date-from").getAttribute("data-empty"), "true");
  assert.equal(element("statistics-date-to").getAttribute("data-empty"), "true");
  assert.equal(element("statistics-all-btn").getAttribute("aria-pressed"), "true");

  element("statistics-date-from").value = "2026-07-01";
  element("statistics-date-from").dispatch("change");
  element("statistics-date-to").value = "2026-07-17";
  element("statistics-date-to").dispatch("change");
  assert.equal(App.statisticsDraftSelection.allTime, false);
  assert.equal(element("statistics-date-from").getAttribute("data-empty"), "false");
  assert.equal(element("statistics-date-to").getAttribute("data-empty"), "false");
  assert.equal(element("statistics-date-status").textContent, "日期范围尚未应用");

  await App.applyStatisticsDraftSelection();
  assert.deepEqual(statisticsCalls.at(-1), ["2026-07-01", "2026-07-17", ""]);
  assert.equal(element("statistics-month-btn").getAttribute("aria-pressed"), "true");
  assert.equal(element("statistics-all-btn").getAttribute("aria-pressed"), "false");
});

test("manual start and end date changes only update draft and preserve accepted results", () => {
  const { App, element, seedAcceptedPresentation, statisticsCalls } = harness();
  App.initStatisticsDefaults();
  seedAcceptedPresentation();
  element("statistics-date-from").value = "2026-07-14";
  element("statistics-date-from").dispatch("change");
  element("statistics-date-to").value = "2026-07-16";
  element("statistics-date-to").dispatch("input");
  assert.equal(statisticsCalls.length, 0);
  assert.equal(App.statisticsAcceptedPayload.exportTicket.revision, "old-revision");
  assert.equal(App.statisticsSnapshotRevision, "old-revision");
  assert.equal(App.statisticsLoaded, true);
  assert.equal(App.statisticsLoading, false);
  assert.equal(element("statistics-results").hidden, false);
  assert.equal(element("stats-total").textContent, "09:00:00");
  assert.equal(element("stats-by-project").innerHTML, "<tr><td>旧结果</td></tr>");
  assert.equal(element("stats-export-action-btn").disabled, false);
  assert.deepEqual(JSON.parse(JSON.stringify(App.statisticsSelection)), {
    allTime: false, dateFrom: "2026-07-13", dateTo: "2026-07-17",
  });
  assert.deepEqual(JSON.parse(JSON.stringify(App.statisticsDraftSelection)), {
    allTime: false, dateFrom: "2026-07-14", dateTo: "2026-07-16",
  });
  assert.equal(element("statistics-date-status").textContent, "日期范围尚未应用");
});

test("apply commits the complete draft and starts exactly one query", async () => {
  const { App, element, statisticsCalls } = harness();
  App.initStatisticsDefaults();
  element("statistics-date-from").value = "2026-07-14";
  element("statistics-date-from").dispatch("change");
  element("statistics-date-to").value = "2026-07-16";
  element("statistics-date-to").dispatch("change");
  await App.applyStatisticsDraftSelection();
  assert.deepEqual(statisticsCalls, [["2026-07-14", "2026-07-16", ""]]);
  assert.equal(App.statisticsLoaded, true);
  assert.equal(element("statistics-results").hidden, false);
  assert.equal(App.statisticsDraftDirty, false);
  assert.deepEqual(JSON.parse(JSON.stringify(App.statisticsSelection)), {
    allTime: false, dateFrom: "2026-07-14", dateTo: "2026-07-16",
  });
});

test("invalid or incomplete draft stays local and never queries", async () => {
  const { App, element, statisticsCalls } = harness();
  App.initStatisticsDefaults();
  element("statistics-date-from").value = "2026-07-18";
  element("statistics-date-to").value = "2026-07-17";
  element("statistics-date-from").dispatch("input");
  element("statistics-date-to").dispatch("change");
  await App.applyStatisticsDraftSelection();
  assert.equal(statisticsCalls.length, 0);
  assert.equal(element("statistics-date-status").textContent, "请选择有效日期范围");
  assert.equal(element("statistics-date-status").className.includes("error"), true);
});

test("project change immediately hides results and starts a scoped query", () => {
  const { App, element, seedAcceptedPresentation, statisticsCalls } = harness();
  const pending = deferred();
  App.initStatisticsDefaults();
  seedAcceptedPresentation();
  App.bridge.getStatisticsExportSummary = (...args) => {
    statisticsCalls.push(args);
    return pending.promise;
  };
  element("statistics-project-filter").value = "7";
  element("statistics-project-filter").dispatch("change");
  assert.equal(element("statistics-results").hidden, true);
  assert.equal(App.statisticsAcceptedPayload, null);
  assert.equal(App.statisticsLoading, true);
  assert.equal(element("stats-export-action-btn").disabled, true);
  assert.deepEqual(statisticsCalls.at(-1), ["2026-07-13", "2026-07-17", "7"]);
});

test("generic loading state blocks export without implicitly discarding a snapshot", () => {
  const { App } = harness();
  let calls = 0;
  const accepted = {
    exportTicket: { date_from: "2026-07-01", date_to: "2026-07-17", revision: "revision-1" },
  };
  App.statisticsAcceptedPayload = accepted;
  App.setStatisticsLoading(true);
  App.bridge.exportStatisticsCsv = () => {
    calls += 1;
    return Promise.resolve({ ok: true });
  };
  App.exportStatisticsCsv();
  assert.equal(calls, 0);
  assert.equal(App.statisticsAcceptedPayload, accepted);
});

test("successful latest query accepts its ticket and shows fresh results", async () => {
  const { App, element, seedAcceptedPresentation } = harness();
  const pending = deferred();
  App.initStatisticsDefaults();
  seedAcceptedPresentation();
  App.bridge.getStatisticsExportSummary = () => pending.promise;
  const load = App.applyStatisticsQuickRange("month");
  assert.equal(element("statistics-results").hidden, true);
  pending.resolve(summaryResult("2026-07-01", "2026-07-17", "", "fresh-revision"));
  await load;
  assert.equal(App.statisticsSnapshotRevision, "fresh-revision");
  assert.equal(App.statisticsAcceptedPayload.exportTicket.revision, "fresh-revision");
  assert.equal(App.statisticsLoaded, true);
  assert.equal(App.statisticsLoading, false);
  assert.equal(element("statistics-results").hidden, false);
  assert.equal(element("stats-total").textContent, "01:00:00");
  assert.equal(element("stats-activity-count").textContent, "4");
  assert.equal(element("stats-file-count").textContent, "1");
  assert.equal(element("stats-export-action-btn").disabled, false);
  assert.match(element("stats-by-project").innerHTML, />3<\/td>/);
  assert.doesNotMatch(element("stats-by-project").innerHTML, />4<\/td>/);
});

test("failed latest query never restores stale results or ticket", async () => {
  const { App, element, seedAcceptedPresentation } = harness();
  App.initStatisticsDefaults();
  seedAcceptedPresentation();
  App.bridge.getStatisticsExportSummary = () => Promise.reject(new Error("failed"));
  await App.applyStatisticsQuickRange("month");
  assert.equal(App.statisticsAcceptedPayload, null);
  assert.equal(App.statisticsLoaded, false);
  assert.equal(App.statisticsLoading, false);
  assert.equal(element("statistics-results").hidden, true);
  assert.equal(element("statistics-error").hidden, false);
  assert.equal(element("stats-export-action-btn").disabled, true);
});

test("stale request cannot render or end loading owned by the latest request", async () => {
  const { App, element } = harness();
  const first = deferred();
  const second = deferred();
  let call = 0;
  App.initStatisticsDefaults();
  App.bridge.getStatisticsExportSummary = () => {
    call += 1;
    return call === 1 ? first.promise : second.promise;
  };
  const firstLoad = App.applyStatisticsQuickRange("month");
  const secondLoad = App.applyStatisticsQuickRange("all");
  first.resolve(summaryResult("2026-07-01", "2026-07-17", "", "stale-revision"));
  await firstLoad;
  assert.equal(App.statisticsAcceptedPayload, null);
  assert.equal(App.statisticsLoading, true);
  assert.equal(element("statistics-results").hidden, true);
  second.resolve(summaryResult("", "", "", "latest-revision"));
  await secondLoad;
  assert.equal(App.statisticsAcceptedPayload.exportTicket.revision, "latest-revision");
  assert.equal(App.statisticsLoading, false);
  assert.equal(element("statistics-results").hidden, false);
});

test("applied manual dates derive shortcut highlighting without a custom mode", async () => {
  const { App, element } = harness();
  App.initStatisticsDefaults();
  element("statistics-date-from").value = "2026-07-01";
  element("statistics-date-to").value = "2026-07-17";
  element("statistics-date-from").dispatch("change");
  await App.applyStatisticsDraftSelection();
  assert.equal(element("statistics-month-btn").getAttribute("aria-pressed"), "true");
  element("statistics-date-from").value = "2026-07-02";
  element("statistics-date-from").dispatch("change");
  await App.applyStatisticsDraftSelection();
  for (const name of ["today", "week", "month", "all"]) {
    assert.equal(element(`statistics-${name}-btn`).getAttribute("aria-pressed"), "false");
  }
});

test("statistics tabs use one roving keyboard lifecycle", () => {
  const { App, element, activeElement } = harness();
  App.initStatisticsDefaults();
  const project = element("stats-project-tab");
  const file = element("stats-file-tab");
  const app = element("stats-app-tab");
  assert.equal(project.tabIndex, 0);
  assert.equal(file.tabIndex, -1);
  project.dispatch("keydown", { key: "ArrowRight" });
  assert.equal(file.getAttribute("aria-selected"), "true");
  assert.equal(file.tabIndex, 0);
  assert.equal(project.tabIndex, -1);
  assert.equal(activeElement(), file);
  file.dispatch("keydown", { key: "End" });
  assert.equal(app.getAttribute("aria-selected"), "true");
  assert.equal(activeElement(), app);
  app.dispatch("keydown", { key: "Home" });
  assert.equal(project.getAttribute("aria-selected"), "true");
  assert.equal(activeElement(), project);
});

test("export uses only the newest successfully accepted ticket", async () => {
  const { App } = harness();
  const calls = [];
  App.initStatisticsDefaults();
  await App.applyStatisticsQuickRange("month");
  App.bridge.exportStatisticsCsv = (...args) => {
    calls.push(args);
    return Promise.resolve({ ok: true, filename: "worktrace.csv" });
  };
  App.exportStatisticsCsv();
  await flush();
  await flush();
  assert.deepEqual(calls, [["2026-07-01", "2026-07-17", "revision-1", ""]]);
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
  pending.resolve({ ok: true, filename: "worktrace.csv" });
  await flush();
  await flush();
  assert.equal(App.statisticsExportSaving, false);
});
