const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      id, hidden: false, disabled: false, checked: false, textContent: "",
      classList: { add() {}, remove() {} },
      setAttribute() {}, querySelector() { return null; },
    });
    return elements.get(id);
  };
  const context = {
    Promise, Error, Array,
    window: { WorkTraceApp: {} },
    document: {
      getElementById: element,
      querySelector() { return null; },
      querySelectorAll() { return []; },
    },
  };
  vm.createContext(context);
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    settingsLoaded: true,
    settingsLoading: false,
    settingsWriteInProgress: false,
    launchAtLoginWriteInProgress: false,
    fdWorkSettingsWriteInProgress: false,
    settingsBackupExportInProgress: false,
    settingsBackupManifestInProgress: false,
    settingsBackupImportInProgress: false,
    settingsClearAllInProgress: false,
    recoveryInProgress: false,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.error) || "failed"); return null; }
      return result;
    },
    updateFDWorkEntryButton() {},
  });
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/fd_work_v5.js"), "utf8"),
    context,
    { filename: "fd_work_v5.js" },
  );
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js/settings.js"), "utf8"),
    context,
    { filename: "settings.js" },
  );
  return { App, element };
}

test("FD Work settings status renders disabled by default", () => {
  const { App, element } = harness();
  App.renderSettingsStatus({ fd_work: { supported: true, enabled: false } });
  assert.equal(element("settings-fd-work-toggle").checked, false);
  assert.equal(element("settings-fd-work-toggle-status").textContent, "关闭");
});

test("FD Work settings write failure restores authoritative backend state", async () => {
  const { App, element } = harness();
  App.lastSettingsStatus = { fd_work: { supported: true, enabled: false } };
  element("settings-fd-work-toggle").checked = true;
  App.bridge = {
    setFDWorkEnabled: () => Promise.resolve({
      ok: false,
      error: "write failed",
      status: { fd_work: { supported: true, enabled: false } },
    }),
  };

  await App.setFDWorkEnabled(true);

  assert.equal(element("settings-fd-work-toggle").checked, false);
  assert.equal(element("settings-fd-work-toggle-status").textContent, "关闭");
  assert.match(element("settings-error").textContent, /write failed/);
});

test("FD Work startup timeout has a stable settings message and reconnect action", () => {
  const { App, element } = harness();
  App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "error", operation: "none",
    ready: false, login_required: false, error_code: "session_start_timeout",
    navigation_generation: 7,
  });
  App.renderSettingsStatus({ fd_work: App.fdWorkStatus });

  assert.equal(element("settings-fd-work-toggle-status").textContent, "连接超时");
  assert.equal(element("settings-fd-work-reconnect").hidden, false);
  assert.equal(element("settings-fd-work-reconnect").textContent, "重新连接");
});

test("probing recovery calls the explicit user-auth operation without local shadow state", async () => {
  const { App } = harness();
  let calls = 0;
  App.bridge = {
    showFDWorkLogin: () => {
      calls += 1;
      return Promise.resolve({ ok: true });
    },
  };
  App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "probing", operation: "none",
    ready: false, login_required: false, error_code: null,
    navigation_generation: 3,
  });

  assert.equal(await App.reconnectFDWork(), true);
  assert.equal(calls, 1);
  assert.equal(App.fdWorkStatus.session_state, "probing");
});

test("late status from an older navigation generation cannot overwrite recovery", () => {
  const { App } = harness();
  assert.equal(App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "ready", operation: "none",
    ready: true, login_required: false, error_code: null,
    navigation_generation: 9,
  }), true);

  assert.equal(App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "probing", operation: "none",
    ready: false, login_required: false, error_code: null,
    navigation_generation: 8,
  }), false);
  assert.equal(App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "probing", operation: "none",
    ready: false, login_required: false, error_code: null,
    navigation_generation: 9,
  }), false);
  assert.equal(App.fdWorkStatus.session_state, "ready");
  assert.equal(App.fdWorkStatus.navigation_generation, 9);
});
