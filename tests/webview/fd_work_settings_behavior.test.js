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
