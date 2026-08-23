const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function harness() {
  const loading = { hidden: true };
  const statusResponses = [];
  const writeResponses = [];
  let statusRequests = 0;
  const document = {
    activeElement: null,
    getElementById(id) { return id === "settings-loading" ? loading : null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  const App = {
    currentPage: "overview",
    settingsLoaded: false,
    settingsLoading: false,
    settingsRequestToken: 0,
    settingsWriteInProgress: false,
    launchAtLoginWriteInProgress: false,
    fdWorkSettingsWriteInProgress: false,
    settingsBackupExportInProgress: false,
    settingsBackupManifestInProgress: false,
    settingsBackupImportInProgress: false,
    settingsClearAllInProgress: false,
    recoveryInProgress: false,
    bridge: {
      getSettingsPrivacyStatus() {
        statusRequests += 1;
        const response = statusResponses.shift();
        return response ? response.promise : Promise.resolve({ ok: true, status: {} });
      },
      setClipboardCaptureEnabled() {
        const response = writeResponses.shift();
        return response ? response.promise : Promise.resolve({ ok: true, status: {} });
      },
    },
    handleResult(result, onError) {
      if (result && result.ok === false) {
        if (onError) onError(result.error || "error");
        return null;
      }
      return result;
    },
  };
  const window = {
    document,
    WorkTraceApp: App,
    addEventListener() {},
  };
  const context = {
    window,
    document,
    Promise,
    Object,
    String,
    Array,
    Number,
    Boolean,
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/settings.js"), "utf8"),
    context,
    { filename: "settings.js" }
  );
  return {
    App,
    loading,
    statusResponses,
    writeResponses,
    statusRequests: () => statusRequests,
  };
}

test("Settings first entry is visible and loaded re-entry is silent", async () => {
  const { App, loading, statusResponses, statusRequests } = harness();
  App.currentPage = "settings";
  const initial = deferred();
  statusResponses.push(initial);

  const initialLoad = App.settings.onPageEntered();
  assert.equal(App.settingsLoading, true);
  assert.equal(loading.hidden, false);
  initial.resolve({ ok: true, status: { collector_running: true } });
  await initialLoad;
  assert.equal(App.settingsLoading, false);
  assert.equal(loading.hidden, true);

  const silent = deferred();
  statusResponses.push(silent);
  const reentry = App.settings.onPageEntered();
  assert.equal(App.settingsLoading, false);
  silent.resolve({ ok: true, status: { collector_running: false } });
  await reentry;

  assert.equal(statusRequests(), 2);
  assert.deepEqual(App.lastSettingsStatus, { collector_running: false });
});

test("Settings defers hidden invalidation and silently refreshes on re-entry", async () => {
  const { App, statusRequests } = harness();
  App.settingsLoaded = true;

  await App.settings.onDataChanged({ source: "refresh-state", settingsChanged: true });
  assert.equal(statusRequests(), 0);
  assert.equal(App.settingsRefreshPending, true);

  App.currentPage = "settings";
  await App.settings.onPageEntered();
  assert.equal(statusRequests(), 1);
  assert.equal(App.settingsRefreshPending, false);
  assert.equal(App.settingsLoading, false);
});

test("Settings keeps refresh pending during a write and drains after the write settles", async () => {
  const { App, writeResponses, statusRequests } = harness();
  App.currentPage = "settings";
  App.settingsLoaded = true;
  const write = deferred();
  writeResponses.push(write);

  const operation = App.setCaptureEnabled(true);
  assert.equal(App.settingsWriteInProgress, true);
  await App.settings.onDataChanged({ source: "refresh-state", settingsChanged: true });
  assert.equal(statusRequests(), 0);
  assert.equal(App.settingsRefreshPending, true);

  write.resolve({ ok: true, status: { clipboard_capture_enabled: true } });
  await operation;
  await Promise.resolve();

  assert.equal(App.settingsWriteInProgress, false);
  assert.equal(statusRequests(), 1);
  assert.equal(App.settingsRefreshPending, false);
  assert.equal(App.settingsLoading, false);
});

test("Settings request token rejects a result from the previous generation", async () => {
  const { App, statusResponses } = harness();
  App.currentPage = "settings";
  const stale = deferred();
  const current = deferred();
  statusResponses.push(stale, current);

  const staleLoad = App.settings.onPageEntered();
  App.settings.resetGeneration();
  const currentLoad = App.settings.onPageEntered();
  current.resolve({ ok: true, status: { marker: "current" } });
  await currentLoad;
  stale.resolve({ ok: true, status: { marker: "stale" } });
  await staleLoad;

  assert.deepEqual(App.lastSettingsStatus, { marker: "current" });
});

