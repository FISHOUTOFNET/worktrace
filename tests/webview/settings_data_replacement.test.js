const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { loadSettingsModules } = require("./settings_test_helpers");

const MAINTENANCE_STATUS = {
  maintenance_in_progress: false,
  maintenance_restored: true,
  recovery_blocked: false,
  blocked_reason: null,
  collector_running: true,
  collector_status: "running",
  user_paused: false,
};

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
        checked: false,
        value: "",
        textContent: "",
        className: "",
        firstChild: null,
        dataset: {},
        appendChild() {},
        removeChild() { this.firstChild = null; },
        querySelector() { return null; },
      });
    }
    return elements.get(id);
  }

  function settingsLine(key) {
    return element(`settings-line-${key}`);
  }

  const context = {
    Promise,
    Error,
    String,
    Number,
    Array,
    setImmediate,
    window: { WorkTraceApp: {} },
    document: {
      getElementById: element,
      querySelector(selector) {
        const match = String(selector).match(/data-settings-key="([^"]+)"/);
        return match ? settingsLine(match[1]) : null;
      },
      createElement(tag) { return element(`created-${tag}-${elements.size}`); },
    },
  };
  vm.createContext(context);

  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    currentPage: "settings",
    handleResult(result, onError) {
      if (!result || result.ok === false) {
        onError((result && result.message) || "操作失败");
        return null;
      }
      return result;
    },
    openConfirmDialog: () => Promise.resolve(true),
  });

  const generationResets = [];
  let refreshCount = 0;
  App.resetClientGeneration = (reason) => { generationResets.push(reason); };
  App.refreshAll = () => { refreshCount += 1; return Promise.resolve(); };
  App.bridge = {
    getSettingsPrivacyStatus: () => Promise.resolve({
      ok: true,
      status: {
        clipboard_capture_enabled: false,
        export_path_configured: false,
        storage_model: "local_only",
        ...MAINTENANCE_STATUS,
        first_run_notice: { accepted: true },
      },
    }),
    setClipboardCaptureEnabled: () => Promise.resolve({ ok: true, status: {} }),
    exportEncryptedBackup: () => Promise.resolve({ ok: true, filename: "backup.wtbackup" }),
    previewEncryptedBackupManifest: () => Promise.resolve({ ok: true, manifest: {}, filename: "backup.wtbackup" }),
    importEncryptedBackup: () => Promise.resolve({ ok: true, message: "已导入" }),
    clearAllLocalData: () => Promise.resolve({ ok: true, message: "已清空" }),
    getFirstRunNotice: () => Promise.resolve({ ok: true, accepted: true, highlights: [] }),
    acceptFirstRunNotice: () => Promise.resolve({ ok: true, accepted: true, collector_started: true }),
  };

  loadSettingsModules(context);

  return {
    App,
    element,
    settingsLine,
    generationResets,
    get refreshCount() { return refreshCount; },
  };
}

test("settings renders the exact maintenance DTO without legacy aliases", () => {
  const { App, settingsLine } = harness();
  App.renderSettingsStatus({
    clipboard_capture_enabled: false,
    export_path_configured: false,
    storage_model: "local_only",
    ...MAINTENANCE_STATUS,
    first_run_notice: { accepted: true },
  });

  assert.equal(settingsLine("maintenance_in_progress").textContent, "数据库维护进行中：否");
  assert.equal(settingsLine("maintenance_restored").textContent, "维护恢复完成：是");
  assert.equal(settingsLine("recovery_blocked").textContent, "维护恢复阻断：否");
  assert.equal(settingsLine("blocked_reason").textContent, "阻断原因：无");
  assert.equal(settingsLine("collector_running").textContent, "采集器运行中：是");
  assert.equal(settingsLine("collector_status").textContent, "采集器状态：running");
  assert.equal(settingsLine("user_paused").textContent, "用户暂停：否");
});

test("secure import resets replacement generation, reloads settings, refreshes, and clears secrets", async () => {
  const state = harness();
  const { App, element, generationResets } = state;
  let statusReads = 0;
  App.bridge.getSettingsPrivacyStatus = () => {
    statusReads += 1;
    return Promise.resolve({
      ok: true,
      status: {
        clipboard_capture_enabled: false,
        export_path_configured: false,
        storage_model: "local_only",
        ...MAINTENANCE_STATUS,
        first_run_notice: { accepted: true },
      },
    });
  };
  element("settings-backup-import-passphrase").value = "secret";

  App.importEncryptedBackup();
  await flush();
  await flush();

  assert.deepEqual(generationResets, ["database_replacement"]);
  assert.equal(statusReads, 1);
  assert.equal(state.refreshCount, 1);
  assert.equal(element("settings-backup-import-passphrase").value, "");
  assert.equal(App.settings.operationName(), "");
});

test("secure import cancellation preserves the passphrase and never enters bridge or busy", async () => {
  const { App, element } = harness();
  let bridgeCalls = 0;
  App.openConfirmDialog = () => Promise.resolve(false);
  App.bridge.importEncryptedBackup = () => {
    bridgeCalls += 1;
    return Promise.resolve({ ok: true });
  };
  element("settings-backup-import-passphrase").value = "secret";

  App.importEncryptedBackup();
  await flush();
  await flush();

  assert.equal(bridgeCalls, 0);
  assert.equal(App.settings.operationName(), "");
  assert.equal(element("settings-backup-import-passphrase").value, "secret");
});

test("secure import confirmation calls bridge once with internal literal", async () => {
  const { App, element } = harness();
  const calls = [];
  App.openConfirmDialog = () => Promise.resolve(true);
  App.bridge.importEncryptedBackup = (...args) => {
    calls.push(args);
    return Promise.resolve({ ok: false, message: "cancelled" });
  };
  element("settings-backup-import-passphrase").value = "secret";

  App.importEncryptedBackup();
  await flush();
  await flush();

  assert.deepEqual(calls, [["secret", "导入并替换"]]);
  assert.equal(element("settings-backup-import-passphrase").value, "");
  assert.equal(App.settings.operationName(), "");
});

test("secure import rejection clears the passphrase and releases busy", async () => {
  const { App, element } = harness();
  App.openConfirmDialog = () => Promise.resolve(true);
  App.bridge.importEncryptedBackup = () => Promise.reject(new Error("bridge unavailable"));
  element("settings-backup-import-passphrase").value = "secret";

  App.importEncryptedBackup();
  await flush();
  await flush();

  assert.equal(element("settings-backup-import-passphrase").value, "");
  assert.equal(App.settings.operationName(), "");
});

test("clear-all uses the same replacement boundary and clears confirmation", async () => {
  const state = harness();
  const { App, element, generationResets } = state;
  element("settings-clear-confirm").value = "清空本地数据";

  App.clearAllLocalData();
  await flush();
  await flush();

  assert.deepEqual(generationResets, ["database_replacement"]);
  assert.equal(state.refreshCount, 1);
  assert.equal(element("settings-clear-confirm").value, "");
  assert.equal(App.settings.operationName(), "");
});

test("one Settings operation blocks every other destructive write", async () => {
  const { App, element } = harness();
  let releaseImport;
  const importPending = new Promise((resolve) => { releaseImport = resolve; });
  let clearCalls = 0;
  App.bridge.importEncryptedBackup = () => importPending;
  App.bridge.clearAllLocalData = () => {
    clearCalls += 1;
    return Promise.resolve({ ok: true });
  };
  element("settings-backup-import-passphrase").value = "secret";
  const importing = App.importEncryptedBackup();
  await flush();
  assert.equal(App.settings.operationName(), "backup_import");
  element("settings-clear-confirm").value = "清空本地数据";

  const cleared = await App.clearAllLocalData();

  assert.equal(cleared, false);
  assert.equal(clearCalls, 0);
  releaseImport({ ok: false, message: "cancelled" });
  await importing;
  assert.equal(App.settings.operationName(), "");
});

test("backup passphrases are cleared after a rejected bridge call", async () => {
  const { App, element } = harness();
  App.bridge.exportEncryptedBackup = () => Promise.reject(new Error("bridge unavailable"));
  element("settings-backup-passphrase").value = "secret";
  element("settings-backup-passphrase-confirm").value = "secret";

  App.exportEncryptedBackup();
  await flush();
  await flush();

  assert.equal(element("settings-backup-passphrase").value, "");
  assert.equal(element("settings-backup-passphrase-confirm").value, "");
  assert.equal(App.settings.operationName(), "");
});

test("first-run acceptance does not couple application startup to Settings reads", async () => {
  const state = harness();
  const { App } = state;
  let statusReads = 0;
  let startupContinued = 0;
  App.continueStartupAfterPrivacyGate = () => { startupContinued += 1; return Promise.resolve(true); };
  App.bridge.getSettingsPrivacyStatus = () => {
    statusReads += 1;
    return Promise.resolve({
      ok: true,
      status: {
        clipboard_capture_enabled: false,
        storage_model: "local_only",
        ...MAINTENANCE_STATUS,
        first_run_notice: { accepted: true },
      },
    });
  };

  assert.equal(await App.privacyNotice.acceptGate(), true);

  assert.equal(App.privacyNotice.requiresAcceptance(), false);
  assert.equal(App.privacyNotice.state(), "accepted_ready");
  assert.equal(startupContinued, 0, "privacy owner must not coordinate application startup");
  assert.equal(statusReads, 0, "privacy acceptance must not eagerly read Settings state");
});
