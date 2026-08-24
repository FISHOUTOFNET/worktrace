const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function runtime({ live = true, acceptedAt = Date.now(), revision = "live-1" } = {}) {
  return {
    acceptedAtEpochMs: acceptedAt,
    structureRevision: "structure-1",
    liveRevision: revision,
    generations: {
      report_structure: 1,
      classification_catalog: 1,
      settings: 1,
    },
    collector: { live_eligible: live },
    liveClock: {
      is_live: live,
      display_span_id: live ? "span-1" : "",
      stable_live_key_hash: live ? "key-1" : "",
    },
  };
}

function harness() {
  let acceptedRuntime = null;
  let pageDirty = false;
  let renderCalls = 0;
  let baseTickerCalls = 0;
  let statisticsTicks = 0;

  const App = {
    currentPage: "overview",
    liveClockContractRefreshRequested: false,
    liveRuntimeStore: {
      get() { return acceptedRuntime; },
    },
    acceptRefreshStateRuntime(state) {
      if (state && state.runtime) acceptedRuntime = state.runtime;
      return true;
    },
    acceptPagePayloadRuntime(payload) {
      if (payload && payload.runtime) acceptedRuntime = payload.runtime;
      return true;
    },
    applyLocalTicker() {
      baseTickerCalls += 1;
    },
    renderLiveDurationTarget() {
      renderCalls += 1;
    },
    getActiveLiveClock() {
      return acceptedRuntime && acceptedRuntime.liveClock || null;
    },
    pageNeedsRefresh() {
      return pageDirty;
    },
    statistics: Object.freeze({
      applyLocalTick() {
        statisticsTicks += 1;
        return { ticked: true };
      },
      onRuntimeTransition() {},
    }),
    showStatus() {},
  };

  const context = {
    window: { WorkTraceApp: App },
    document: {},
    console,
    Date,
    Math,
    Number,
    String,
    Array,
    Object,
    JSON,
    parseInt,
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/ui_composition.js"),
      "utf8"
    ),
    context,
    { filename: "ui_composition.js" }
  );

  return {
    App: context.window.WorkTraceApp,
    setRuntime(value) { acceptedRuntime = value; },
    setPageDirty(value) { pageDirty = value === true; },
    counts() { return { renderCalls, baseTickerCalls, statisticsTicks }; },
  };
}

test("stale runtime lease freezes generic live projections until authoritative rebase", () => {
  const { App, setRuntime, setPageDirty, counts } = harness();
  const stale = runtime({ acceptedAt: Date.now() - 11000, revision: "live-old" });
  setRuntime(stale);

  App.applyLocalTicker();
  App.renderLiveDurationTarget({}, stale.liveClock, Date.now());

  assert.equal(counts().baseTickerCalls, 1, "heartbeat owner must still run");
  assert.equal(counts().renderCalls, 0, "stale runtime must not extrapolate");
  assert.equal(App.getActiveLiveClock(), null);
  assert.equal(App.isLiveRuntimeFresh(stale, Date.now()), false);

  App.acceptRefreshStateRuntime({
    runtime: runtime({ acceptedAt: Date.now(), revision: "live-recovered-1" }),
  });
  assert.equal(App.liveClockContractRefreshRequested, true);
  App.renderLiveDurationTarget({}, {}, Date.now());
  assert.equal(counts().renderCalls, 0, "first recovered heartbeat still needs page rebase");

  setPageDirty(true);
  App.acceptRefreshStateRuntime({
    runtime: runtime({ acceptedAt: Date.now(), revision: "live-recovered-2" }),
  });
  App.renderLiveDurationTarget({}, {}, Date.now());
  assert.equal(counts().renderCalls, 0, "failed or pending page refresh stays frozen");

  setPageDirty(false);
  App.acceptRefreshStateRuntime({
    runtime: runtime({ acceptedAt: Date.now(), revision: "live-recovered-3" }),
  });
  App.renderLiveDurationTarget({}, {}, Date.now());
  assert.equal(counts().renderCalls, 1, "clean authoritative page rebase resumes ticking");
});

test("authoritative page payload clears a pending runtime rebase immediately", () => {
  const { App, setRuntime, counts } = harness();
  setRuntime(runtime({ acceptedAt: Date.now() - 11000, revision: "live-old" }));
  App.applyLocalTicker();

  App.acceptRefreshStateRuntime({
    runtime: runtime({ acceptedAt: Date.now(), revision: "live-recovered" }),
  });
  App.renderLiveDurationTarget({}, {}, Date.now());
  assert.equal(counts().renderCalls, 0);

  App.acceptPagePayloadRuntime({
    runtime: runtime({ acceptedAt: Date.now(), revision: "page-authoritative" }),
  });
  App.renderLiveDurationTarget({}, {}, Date.now());
  assert.equal(counts().renderCalls, 1);
});

test("statistics local ticker obeys authoritative liveness and requires rebase on resume", () => {
  const { App, setRuntime, setPageDirty, counts } = harness();
  App.currentPage = "statistics";
  setRuntime(runtime({ live: true, acceptedAt: Date.now(), revision: "live-1" }));

  assert.deepEqual(App.statistics.applyLocalTick(), { ticked: true });
  assert.equal(counts().statisticsTicks, 1);

  App.acceptRefreshStateRuntime({
    runtime: runtime({ live: false, acceptedAt: Date.now(), revision: "stopped" }),
  });
  assert.equal(App.statistics.applyLocalTick(), null);
  assert.equal(counts().statisticsTicks, 1, "backend live_eligible=false must freeze old statistics target");

  App.acceptRefreshStateRuntime({
    runtime: runtime({ live: true, acceptedAt: Date.now(), revision: "resumed-1" }),
  });
  assert.equal(App.liveClockContractRefreshRequested, true);
  assert.equal(App.statistics.applyLocalTick(), null);
  assert.equal(counts().statisticsTicks, 1, "resume cannot reuse pre-stop statistics target");

  setPageDirty(true);
  App.acceptRefreshStateRuntime({
    runtime: runtime({ live: true, acceptedAt: Date.now(), revision: "resumed-2" }),
  });
  assert.equal(App.statistics.applyLocalTick(), null);

  setPageDirty(false);
  App.acceptRefreshStateRuntime({
    runtime: runtime({ live: true, acceptedAt: Date.now(), revision: "resumed-3" }),
  });
  assert.deepEqual(App.statistics.applyLocalTick(), { ticked: true });
  assert.equal(counts().statisticsTicks, 2);
});

test("legacy narrow runtime without freshness metadata remains compatible", () => {
  const { App, setRuntime, counts } = harness();
  setRuntime({ structureRevision: "s", liveRevision: "l", generations: {} });

  App.applyLocalTicker();
  App.renderLiveDurationTarget({}, {}, Date.now());

  assert.equal(counts().baseTickerCalls, 1);
  assert.equal(counts().renderCalls, 1);
  assert.equal(App.isLiveRuntimeProjectionAllowed(Date.now()), true);
});
