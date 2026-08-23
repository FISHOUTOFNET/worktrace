const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  const loadingStates = [];
  let requests = 0;
  let currentToken = null;
  const document = {
    getElementById() { return null; },
    querySelectorAll() { return []; },
  };
  const App = {
    currentPage: "overview",
    rulesLoaded: false,
    rulesLoading: false,
    rulesRefreshPending: false,
    rulesLoadPromise: null,
    bridge: {
      getProjectRules() {
        requests += 1;
        return Promise.resolve({ ok: true, projects: [] });
      },
    },
    requestCoordinator: {
      beginLatest() { currentToken = {}; return currentToken; },
      isCurrent(token) { return token === currentToken; },
    },
    clearRulesError() {},
    showRulesError() {},
    safeText(value, fallback) { return value == null ? fallback : String(value); },
  };
  const window = { document, WorkTraceApp: App };
  const context = {
    window,
    document,
    Promise,
    Object,
    String,
    Array,
    Number,
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/rules.js"), "utf8"),
    context,
    { filename: "rules.js" }
  );
  App.setRulesLoading = (value) => {
    App.rulesLoading = !!value;
    loadingStates.push(!!value);
  };
  return {
    App,
    loadingStates,
    requests: () => requests,
  };
}

test("Rules ignores live-only changes and silently reconciles relevant visible changes", async () => {
  const { App, loadingStates, requests } = harness();
  App.currentPage = "rules";
  App.rulesLoaded = true;

  await App.rules.onDataChanged({ source: "refresh-state", liveChanged: true });
  assert.equal(requests(), 0);

  await App.rules.onDataChanged({
    source: "refresh-state",
    classificationChanged: true,
  });
  assert.equal(requests(), 1);
  assert.deepEqual(loadingStates, []);
  assert.equal(App.rulesRefreshPending, false);
});

test("Rules keeps visible structure-only changes pending until re-entry", async () => {
  const { App, loadingStates, requests } = harness();
  App.currentPage = "rules";
  App.rulesLoaded = true;

  await App.rules.onDataChanged({
    source: "refresh-state",
    structureChanged: true,
  });
  assert.equal(requests(), 0);
  assert.equal(App.rulesRefreshPending, true);

  await App.rules.onPageEntered();
  assert.equal(requests(), 1);
  assert.deepEqual(loadingStates, []);
  assert.equal(App.rulesRefreshPending, false);
});

test("Rules defers hidden invalidation and silently refreshes on re-entry", async () => {
  const { App, loadingStates, requests } = harness();
  App.rulesLoaded = true;

  await App.rules.onDataChanged({
    source: "refresh-state",
    structureChanged: true,
  });
  assert.equal(requests(), 0);
  assert.equal(App.rulesRefreshPending, true);

  App.currentPage = "rules";
  await App.rules.onPageEntered();
  assert.equal(requests(), 1);
  assert.deepEqual(loadingStates, []);
  assert.equal(App.rulesRefreshPending, false);
});

test("Rules first entry keeps visible loading", async () => {
  const { App, loadingStates, requests } = harness();
  App.currentPage = "rules";

  await App.rules.onPageEntered();

  assert.equal(requests(), 1);
  assert.deepEqual(loadingStates, [true, false]);
  assert.equal(App.rulesLoaded, true);
});
