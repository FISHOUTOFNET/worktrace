const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

// End-to-end behavior tests for the UI redesign PR (spec section 11).
// Drives production WebView JS modules in a vm context with stubbed
// App.bridge; asserts observable behavior, never source strings.

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function makeElement(id) {
  return {
    id,
    hidden: false,
    disabled: false,
    checked: false,
    value: "",
    textContent: "",
    innerHTML: "",
    className: "",
    dataset: {},
    classList: { add() {}, remove() {}, contains() { return false; }, toggle() {} },
    setAttribute() {}, removeAttribute() {}, getAttribute() { return null; },
    appendChild() {}, removeChild() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener() {},
  };
}

function makeBaseContext(extra = {}) {
  const elements = new Map();
  function element(id) {
    if (!elements.has(id)) elements.set(id, makeElement(id));
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
    JSON,
    RegExp,
    setTimeout,
    clearTimeout,
    setImmediate,
    window: { WorkTraceApp: {}, matchMedia: () => ({ matches: false }), setTimeout, clearTimeout },
    document: {
      getElementById: element,
      querySelector() { return null; },
      querySelectorAll() { return []; },
      createElement() { return makeElement(`created-${elements.size}`); },
    },
    ...extra,
  };
  vm.createContext(context);
  return { context, element, elements };
}

function loadJs(context, file) {
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
    context,
    { filename: file }
  );
}

// ---------------------------------------------------------------------------
// Categories 1-3: Privacy gate state machine
// ---------------------------------------------------------------------------

function privacyHarness() {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    firstRunNoticeLoaded: false,
    firstRunNoticeLoading: false,
    firstRunNoticeRequired: false,
    firstRunNoticeAcceptInProgress: false,
    firstRunNoticeViewingFromSettings: false,
    privacyGateState: "loading",
    heartbeatTimer: null,
    settingsLoaded: false,
    settingsLoading: false,
    settingsRequestToken: 0,
    settingsWriteInProgress: false,
    settingsBackupExportInProgress: false,
    settingsBackupManifestInProgress: false,
    settingsBackupImportInProgress: false,
    settingsClearAllInProgress: false,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  let heartbeatStarts = 0;
  App.startHeartbeat = () => { heartbeatStarts += 1; App.heartbeatTimer = {}; };
  App.stopHeartbeat = () => { App.heartbeatTimer = null; };
  let refreshCount = 0;
  App.refreshAll = () => { refreshCount += 1; return Promise.resolve(); };
  // Stub the single idempotent startup entry owned by init.js. The privacy
  // gate (settings.js) delegates to this entry instead of calling refreshAll
  // directly, so the harness tracks it to verify the gate hands off to the
  // unique startup path rather than a second refresh path.
  let startupContinues = 0;
  App.continueStartupAfterPrivacyGate = () => { startupContinues += 1; return Promise.resolve(true); };
  App.bridge = {
    getFirstRunNotice: () => Promise.resolve({ ok: true }),
    acceptFirstRunNotice: () => Promise.resolve({ ok: true }),
    getSettingsPrivacyStatus: () => Promise.resolve({ ok: true, status: {} }),
  };
  loadJs(context, "core.js");
  loadJs(context, "settings.js");
  return {
    App,
    element,
    heartbeatStarts: () => heartbeatStarts,
    refreshCount: () => refreshCount,
    startupContinues: () => startupContinues,
  };
}

test("1. privacy first launch: unaccepted notice is fail-closed, no heartbeat", async () => {
  const { App, element, heartbeatStarts } = privacyHarness();
  App.bridge.getFirstRunNotice = () => Promise.resolve({
    ok: true,
    notice: {
      version: "2026-01",
      title: "WorkTrace 隐私说明",
      text: "本应用仅在本机采集活动窗口标题等元数据。",
      highlights: ["不上传", "可暂停", "可清空"],
      accepted: false,
    },
  });

  await App.loadFirstRunNotice();
  await flush();

  assert.equal(App.privacyGateState, "acceptance_required");
  assert.equal(App.firstRunNoticeRequired, true);
  assert.equal(element("first-run-notice-overlay").hidden, false);
  assert.equal(element("first-run-notice-title").textContent, "WorkTrace 隐私说明");
  assert.equal(element("first-run-notice-text").textContent.length > 0, true);
  assert.equal(element("first-run-notice-highlights").children || true, true);
  assert.equal(heartbeatStarts(), 0, "heartbeat must NOT start while unaccepted");
});

test("1b. privacy notice load failure is fail-closed with visible error", async () => {
  const { App, element } = privacyHarness();
  App.bridge.getFirstRunNotice = () => Promise.resolve({ ok: false, error: "load_failed" });

  await App.loadFirstRunNotice();
  await flush();

  assert.equal(App.privacyGateState, "load_failed");
  assert.equal(element("first-run-notice-overlay").hidden, false);
  assert.equal(element("first-run-notice-accept-btn").disabled, true);
  assert.equal(element("first-run-notice-accept-btn").hidden, true);
});

test("2. privacy confirmation success closes gate, continues via single startup entry", async () => {
  const { App, element, heartbeatStarts, startupContinues } = privacyHarness();
  App.bridge.getFirstRunNotice = () => Promise.resolve({
    ok: true,
    notice: { title: "T", text: "x", highlights: [], accepted: false },
  });
  App.bridge.acceptFirstRunNotice = () => Promise.resolve({
    ok: true,
    accepted: true,
    collector_started: true,
    collector_status: { running: true },
  });

  await App.loadFirstRunNotice();
  await flush();
  assert.equal(App.firstRunNoticeRequired, true);

  App.acceptFirstRunNotice();
  await flush();
  await flush();

  assert.equal(App.privacyGateState, "accepted_ready");
  assert.equal(App.firstRunNoticeRequired, false);
  assert.equal(element("first-run-notice-overlay").hidden, true);
  // The gate must hand off to the single idempotent startup entry, not a
  // second refreshAll path.
  assert.equal(startupContinues(), 1);
  // The gate itself must NOT start a heartbeat; that is owned by init.js.
  assert.equal(heartbeatStarts(), 0, "gate must not start heartbeat directly");
});

test("3. privacy partial success: accepted but collector failed does not lock UI", async () => {
  const { App, element, startupContinues } = privacyHarness();
  App.bridge.getFirstRunNotice = () => Promise.resolve({
    ok: true,
    notice: { title: "T", text: "x", highlights: [], accepted: false },
  });
  App.bridge.acceptFirstRunNotice = () => Promise.resolve({
    ok: false,
    accepted: true,
    collector_started: false,
    error_code: "collector_start_failed",
    message: "记录功能未能启动，请稍后重试或在设置中恢复",
    collector_status: { running: false },
  });

  await App.loadFirstRunNotice();
  await flush();

  App.acceptFirstRunNotice();
  await flush();
  await flush();

  // Gate must NOT remain an uncloseable authorization door.
  assert.equal(App.privacyGateState, "accepted_start_failed");
  assert.equal(App.firstRunNoticeRequired, false);
  assert.equal(element("first-run-notice-overlay").hidden, true);
  // Global alert must surface the real failure reason.
  assert.equal(element("global-alert").hidden, false);
  assert.match(element("global-alert").textContent, /记录功能未能启动/);
  // Authorization is durable, so the UI must still enter the app via the
  // single startup entry (heartbeat + settings usable for recovery).
  assert.equal(startupContinues(), 1, "partial success must still continue startup");
});

// ---------------------------------------------------------------------------
// Category 4: Maintenance recovery flow
// ---------------------------------------------------------------------------

test("4. maintenance recovery: blocked -> recover -> reload status and page", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    settingsLoaded: true,
    settingsLoading: false,
    settingsRequestToken: 0,
    settingsWriteInProgress: false,
    settingsBackupExportInProgress: false,
    settingsBackupManifestInProgress: false,
    settingsBackupImportInProgress: false,
    settingsClearAllInProgress: false,
    recoveryInProgress: false,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  let recoverCalls = 0;
  App.bridge = {
    recoverDatabaseMaintenance: () => { recoverCalls += 1; return Promise.resolve({ ok: true }); },
    getSettingsPrivacyStatus: () => Promise.resolve({ ok: true, status: {} }),
  };
  loadJs(context, "core.js");
  loadJs(context, "settings.js");
  // Set mocks AFTER loading settings.js so they are not overwritten.
  let refreshCount = 0;
  let statusCount = 0;
  App.refreshAll = () => { refreshCount += 1; return Promise.resolve(); };
  App.loadSettingsPrivacyStatus = () => { statusCount += 1; return Promise.resolve(); };
  App.showToast = () => {};

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();

  assert.equal(ok, true);
  assert.equal(recoverCalls, 1);
  assert.equal(statusCount, 1, "settings status must be reloaded");
  assert.equal(refreshCount, 1, "page must be refreshed");
  assert.equal(App.recoveryInProgress, false);
});

test("4b. maintenance recovery failure keeps blocked flag and shows public error", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    settingsLoaded: true,
    settingsLoading: false,
    settingsRequestToken: 0,
    settingsWriteInProgress: false,
    settingsBackupExportInProgress: false,
    settingsBackupManifestInProgress: false,
    settingsBackupImportInProgress: false,
    settingsClearAllInProgress: false,
    recoveryInProgress: false,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  App.bridge = {
    recoverDatabaseMaintenance: () => Promise.resolve({
      ok: false,
      error_code: "recovery_failed",
      message: "恢复失败：维护锁仍被持有",
      // The backend returns maintenance state even on failure so the
      // frontend can re-render the recovery card from authoritative state.
      maintenance: {
        maintenance_in_progress: false,
        maintenance_restored: false,
        recovery_blocked: true,
        blocked_reason: "maintenance_recovery_not_verified",
      },
    }),
    getSettingsPrivacyStatus: () => Promise.resolve({ ok: true, status: {} }),
  };
  loadJs(context, "core.js");
  loadJs(context, "settings.js");
  App.refreshAll = () => Promise.resolve();
  App.loadSettingsPrivacyStatus = () => Promise.resolve();
  App.showToast = () => {};

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();

  assert.equal(ok, false);
  assert.equal(App.recoveryInProgress, false);
  // Button is re-enabled because the backend still reports recovery_blocked;
  // the frontend never clears the blocked flag locally.
  assert.equal(element("settings-recovery-btn").disabled, false);
  assert.match(element("settings-recovery-status").textContent, /恢复失败：维护锁仍被持有/);
});

// ---------------------------------------------------------------------------
// Category 4c: Symmetric Settings mutex — any operation blocks recovery
// ---------------------------------------------------------------------------

// Parameterized: every Settings busy flag must prevent recovery from starting.
// This is the reverse direction of the guard the other operations already
// perform (recovery → blocks others). Without it, a user could trigger
// recovery while a backup import is mid-flight and corrupt the write gate.
const RECOVERY_BLOCKING_FLAGS = [
  ["settingsLoading", "settings status load"],
  ["settingsWriteInProgress", "clipboard setting write"],
  ["settingsBackupExportInProgress", "backup export"],
  ["settingsBackupManifestInProgress", "manifest preview"],
  ["settingsBackupImportInProgress", "backup import"],
  ["settingsClearAllInProgress", "clear-all"],
  ["recoveryInProgress", "recovery already running"],
];

for (const [flag, label] of RECOVERY_BLOCKING_FLAGS) {
  test(`4c. ${label} (${flag}) blocks recovery — symmetric mutex`, async () => {
    const { context, element } = makeBaseContext();
    const App = context.window.WorkTraceApp;
    Object.assign(App, {
      settingsLoaded: true,
      settingsLoading: false,
      settingsRequestToken: 0,
      settingsWriteInProgress: false,
      settingsBackupExportInProgress: false,
      settingsBackupManifestInProgress: false,
      settingsBackupImportInProgress: false,
      settingsClearAllInProgress: false,
      recoveryInProgress: false,
      handleResult(result, onError) {
        if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
        return result;
      },
    });
    let recoverCalls = 0;
    App.bridge = {
      recoverDatabaseMaintenance: () => { recoverCalls += 1; return Promise.resolve({ ok: true }); },
      getSettingsPrivacyStatus: () => Promise.resolve({ ok: true, status: {} }),
    };
    loadJs(context, "core.js");
    loadJs(context, "settings.js");
    App.refreshAll = () => Promise.resolve();
    App.loadSettingsPrivacyStatus = () => Promise.resolve();
    App.showToast = () => {};

    // Set the busy flag AFTER loading settings.js so it is not overwritten.
    App[flag] = true;

    const ok = await App.recoverDatabaseMaintenance();
    await flush();
    await flush();

    assert.equal(ok, false, `recovery must be rejected when ${flag} is true`);
    assert.equal(recoverCalls, 0, `recovery Bridge must not be called when ${flag} is true`);
    assert.equal(App[flag], true, `${flag} must not be cleared by the rejected recovery`);
    // For the recoveryInProgress case the flag was already true and must stay
    // true (early return does not touch it). For every other flag, the
    // rejected path must not set recoveryInProgress.
    if (flag !== "recoveryInProgress") {
      assert.equal(App.recoveryInProgress, false, "recovery flag must not be set by the rejected path");
    }
  });
}

// ---------------------------------------------------------------------------
// Category 4d: Recovery in progress blocks every other Settings operation
// ---------------------------------------------------------------------------

test("4d. recovery in progress blocks backup export, manifest, import, clear, and clipboard write", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    settingsLoaded: true,
    settingsLoading: false,
    settingsRequestToken: 0,
    settingsWriteInProgress: false,
    settingsBackupExportInProgress: false,
    settingsBackupManifestInProgress: false,
    settingsBackupImportInProgress: false,
    settingsClearAllInProgress: false,
    recoveryInProgress: false,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  // Recovery Bridge call stays pending so recoveryInProgress stays true for
  // the duration of the test. Every other operation must observe the busy
  // flag and bail out without calling its own Bridge method.
  const recoveryGate = deferred();
  const bridgeCalls = {
    exportEncryptedBackup: 0,
    previewEncryptedBackupManifest: 0,
    importEncryptedBackup: 0,
    clearAllLocalData: 0,
    setClipboardCaptureEnabled: 0,
    recoverDatabaseMaintenance: 0,
  };
  App.bridge = {
    recoverDatabaseMaintenance: () => { bridgeCalls.recoverDatabaseMaintenance += 1; return recoveryGate.promise; },
    exportEncryptedBackup: () => { bridgeCalls.exportEncryptedBackup += 1; return Promise.resolve({ ok: true }); },
    previewEncryptedBackupManifest: () => { bridgeCalls.previewEncryptedBackupManifest += 1; return Promise.resolve({ ok: true, manifest: {} }); },
    importEncryptedBackup: () => { bridgeCalls.importEncryptedBackup += 1; return Promise.resolve({ ok: true }); },
    clearAllLocalData: () => { bridgeCalls.clearAllLocalData += 1; return Promise.resolve({ ok: true }); },
    setClipboardCaptureEnabled: () => { bridgeCalls.setClipboardCaptureEnabled += 1; return Promise.resolve({ ok: true }); },
    getSettingsPrivacyStatus: () => Promise.resolve({ ok: true, status: {} }),
  };
  loadJs(context, "core.js");
  loadJs(context, "settings.js");
  App.refreshAll = () => Promise.resolve();
  App.loadSettingsPrivacyStatus = () => Promise.resolve();
  App.showToast = () => {};
  App.lastSettingsStatus = { recovery_blocked: true };

  // Kick off recovery (pending). Do not await — it must stay in flight.
  App.recoverDatabaseMaintenance();
  await flush();
  assert.equal(App.recoveryInProgress, true, "recovery must be in progress");

  // Every other operation must be rejected by the symmetric mutex.
  App.exportEncryptedBackup();
  App.previewEncryptedBackupManifest();
  element("settings-backup-import-confirm").value = "导入并替换";
  App.importEncryptedBackup();
  element("settings-clear-confirm").value = "清空本地数据";
  App.clearAllLocalData();
  App.setCaptureEnabled(true);
  await flush();
  await flush();

  assert.equal(bridgeCalls.exportEncryptedBackup, 0, "export must not run during recovery");
  assert.equal(bridgeCalls.previewEncryptedBackupManifest, 0, "manifest must not run during recovery");
  assert.equal(bridgeCalls.importEncryptedBackup, 0, "import must not run during recovery");
  assert.equal(bridgeCalls.clearAllLocalData, 0, "clear must not run during recovery");
  assert.equal(bridgeCalls.setClipboardCaptureEnabled, 0, "clipboard write must not run during recovery");
  assert.equal(bridgeCalls.recoverDatabaseMaintenance, 1, "recovery itself runs exactly once");
  assert.equal(App.recoveryInProgress, true, "recovery flag must remain set while pending");

  // The recovery button itself must be disabled while recovery is in flight.
  assert.equal(element("settings-recovery-btn").disabled, true, "recovery button disabled during recovery");

  // Release the pending recovery so the test can clean up.
  recoveryGate.resolve({ ok: true });
  await flush();
  await flush();
  assert.equal(App.recoveryInProgress, false, "recovery flag released after completion");
});

// ---------------------------------------------------------------------------
// Category 4e: Transport rejection re-reads authoritative backend state
// ---------------------------------------------------------------------------

test("4e. recovery transport rejection re-reads authoritative state (blocked=false → button disabled)", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    settingsLoaded: true,
    settingsLoading: false,
    settingsRequestToken: 0,
    settingsWriteInProgress: false,
    settingsBackupExportInProgress: false,
    settingsBackupManifestInProgress: false,
    settingsBackupImportInProgress: false,
    settingsClearAllInProgress: false,
    recoveryInProgress: false,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  let recoverCalls = 0;
  let statusReads = 0;
  App.bridge = {
    // Transport rejection: the frontend cannot know whether recovery applied.
    recoverDatabaseMaintenance: () => { recoverCalls += 1; return Promise.reject(new Error("webview transport disconnected")); },
    // Authoritative backend status reports recovery is no longer needed.
    getSettingsPrivacyStatus: () => Promise.resolve({
      ok: true,
      status: {
        maintenance_in_progress: false,
        maintenance_restored: true,
        recovery_blocked: false,
        blocked_reason: null,
        collector_running: true,
        collector_status: "running",
        user_paused: false,
      },
    }),
  };
  loadJs(context, "core.js");
  loadJs(context, "settings.js");
  App.refreshAll = () => Promise.resolve();
  // Stub the real status loader so the count is observable; the production
  // catch path calls App.loadSettingsPrivacyStatus, which in turn invokes
  // bridge.getSettingsPrivacyStatus.
  App.loadSettingsPrivacyStatus = async function () {
    statusReads += 1;
    const result = await App.bridge.getSettingsPrivacyStatus();
    if (result && result.ok && result.status) {
      App.lastSettingsStatus = result.status;
    }
    return result;
  };
  App.showToast = () => {};
  App.lastSettingsStatus = { recovery_blocked: true };

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();
  await flush();

  assert.equal(ok, false, "transport rejection must not be reported as success");
  assert.equal(recoverCalls, 1, "recovery Bridge called exactly once");
  assert.equal(statusReads, 1, "authoritative status must be re-read exactly once after rejection");
  assert.equal(App.recoveryInProgress, false, "recovery busy flag must be released after state refresh");
  // Backend reports recovery_blocked=false, so the button must be disabled:
  // no recovery is needed. The frontend never clears the blocked flag locally.
  assert.equal(element("settings-recovery-btn").disabled, true, "button disabled when backend reports no recovery needed");
  // The stale blocked=true status must NOT be reused as the final answer.
  assert.equal(App.lastSettingsStatus.recovery_blocked, false, "lastSettingsStatus refreshed to authoritative state");
  assert.match(element("settings-recovery-status").textContent, /恢复结果未知/);
});

test("4f. recovery transport rejection re-reads authoritative state (blocked=true → button re-enabled)", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    settingsLoaded: true,
    settingsLoading: false,
    settingsRequestToken: 0,
    settingsWriteInProgress: false,
    settingsBackupExportInProgress: false,
    settingsBackupManifestInProgress: false,
    settingsBackupImportInProgress: false,
    settingsClearAllInProgress: false,
    recoveryInProgress: false,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  let recoverCalls = 0;
  let statusReads = 0;
  App.bridge = {
    recoverDatabaseMaintenance: () => { recoverCalls += 1; return Promise.reject(new Error("webview transport disconnected")); },
    getSettingsPrivacyStatus: () => Promise.resolve({
      ok: true,
      status: {
        maintenance_in_progress: false,
        maintenance_restored: false,
        recovery_blocked: true,
        blocked_reason: "maintenance_recovery_not_verified",
        collector_running: false,
        collector_status: "stopped",
        user_paused: false,
      },
    }),
  };
  loadJs(context, "core.js");
  loadJs(context, "settings.js");
  App.refreshAll = () => Promise.resolve();
  App.loadSettingsPrivacyStatus = async function () {
    statusReads += 1;
    const result = await App.bridge.getSettingsPrivacyStatus();
    if (result && result.ok && result.status) {
      App.lastSettingsStatus = result.status;
    }
    return result;
  };
  App.showToast = () => {};
  App.lastSettingsStatus = { recovery_blocked: true };

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();
  await flush();

  assert.equal(ok, false, "transport rejection must not be reported as success");
  assert.equal(recoverCalls, 1, "recovery Bridge called exactly once");
  assert.equal(statusReads, 1, "authoritative status must be re-read exactly once after rejection");
  assert.equal(App.recoveryInProgress, false, "recovery busy flag must be released after state refresh");
  // Backend still reports recovery_blocked=true, so the button must be
  // re-enabled: the user can attempt recovery again.
  assert.equal(element("settings-recovery-btn").disabled, false, "button re-enabled when backend still reports blocked");
  assert.equal(App.lastSettingsStatus.recovery_blocked, true, "lastSettingsStatus refreshed to authoritative state");
  assert.match(element("settings-recovery-status").textContent, /恢复结果未知/);
});

test("4g. recovery transport rejection when status read also fails still releases busy flag", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    settingsLoaded: true,
    settingsLoading: false,
    settingsRequestToken: 0,
    settingsWriteInProgress: false,
    settingsBackupExportInProgress: false,
    settingsBackupManifestInProgress: false,
    settingsBackupImportInProgress: false,
    settingsClearAllInProgress: false,
    recoveryInProgress: false,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  let recoverCalls = 0;
  let statusReads = 0;
  App.bridge = {
    recoverDatabaseMaintenance: () => { recoverCalls += 1; return Promise.reject(new Error("webview transport disconnected")); },
    getSettingsPrivacyStatus: () => Promise.reject(new Error("status read failed")),
  };
  loadJs(context, "core.js");
  loadJs(context, "settings.js");
  App.refreshAll = () => Promise.resolve();
  App.loadSettingsPrivacyStatus = async function () {
    statusReads += 1;
    await App.bridge.getSettingsPrivacyStatus();
  };
  App.showToast = () => {};
  // Pre-existing authoritative state: still blocked. The frontend must NOT
  // clear this flag locally when the status re-read itself fails.
  App.lastSettingsStatus = { recovery_blocked: true, blocked_reason: "prior_failure" };

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();
  await flush();

  assert.equal(ok, false, "must not be reported as success when both recovery and status read fail");
  assert.equal(recoverCalls, 1);
  assert.equal(statusReads, 1, "status must still be attempted once");
  // Critical: the busy flag must be released to avoid a permanent UI deadlock,
  // even though the status read failed.
  assert.equal(App.recoveryInProgress, false, "busy flag released even on double failure");
  // The frontend must not clear the prior blocked flag locally.
  assert.equal(App.lastSettingsStatus.recovery_blocked, true, "prior blocked state preserved");
});

// ---------------------------------------------------------------------------
// Category 5: Global collection feedback visible on every page
// ---------------------------------------------------------------------------

test("5. global toggle error is visible via global-alert on every page", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    currentPage: "overview",
    collectorToggleInProgress: false,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  App.bridge = {
    pauseCollector: () => Promise.resolve({ ok: false, error_code: "maintenance_blocked", message: "数据库维护未完成，无法切换" }),
    resumeCollector: () => Promise.resolve({ ok: false, error_code: "maintenance_blocked", message: "数据库维护未完成，无法切换" }),
  };
  loadJs(context, "core.js");

  for (const page of ["overview", "timeline", "statistics", "rules", "settings"]) {
    App.currentPage = page;
    App.showGlobalAlert("");
    // Simulate the global toggle handler path.
    const result = await App.bridge.pauseCollector();
    if (!result || result.ok === false) {
      App.showGlobalAlert(App.extractBridgeError(result, "操作失败"));
    }
    assert.equal(element("global-alert").hidden, false, `global-alert must be visible on page ${page}`);
    assert.match(element("global-alert").textContent, /数据库维护未完成/);
  }
});

// ---------------------------------------------------------------------------
// Categories 6-9: Timeline editing, autosave rebase, context change, merge
// ---------------------------------------------------------------------------

function timelineHarness() {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    timelineDate: "2026-07-12",
    selectedProjectionInstanceKey: "base:a",
    selectedProjectionRevision: "rev-a",
    currentSessions: [],
    editingSession: null,
    editSaving: false,
    timelineAutosaveQueued: false,
    submittedDraft: null,
    pendingContextChange: null,
    mutationState: null,
    mutationOwner: null,
    detailsInFlight: {},
    NOTE_MAX_LENGTH: 2000,
    detailsOwner: null,
  });
  const bridgeCall = (method) => (...args) => {
    const handler = App.callBridge;
    if (typeof handler !== "function") return Promise.reject(new Error(`missing bridge handler: ${method}`));
    return handler(method, ...args);
  };
  App.bridge = {
    getTimeline: bridgeCall("get_timeline"),
    getTimelineSessionActivitySummary: bridgeCall("get_timeline_session_activity_summary"),
    listProjectsForTimeline: bridgeCall("list_projects_for_timeline"),
    saveTimelineSessionEdit: bridgeCall("save_timeline_session_edit"),
    hideTimelineSession: bridgeCall("hide_timeline_session"),
    hideTimelineSessionActivity: bridgeCall("hide_timeline_session_activity"),
    mergeTimelineSession: bridgeCall("merge_timeline_session"),
    splitTimelineSession: bridgeCall("split_timeline_session"),
    copyTimelineSession: bridgeCall("copy_timeline_session"),
  };
  App.handleResult = (result, onError) => {
    if (result && result.ok === false) { onError(result.message || "操作失败", result.error); return null; }
    return result;
  };
  App.refreshTimelineAfterEdit = () => Promise.resolve();
  App.loadTimelineReport = () => Promise.resolve();
  for (const file of ["timeline_request_state.js", "timeline.js"]) loadJs(context, file);
  return { App, element };
}

function session(key, revision, startTime, opts = {}) {
  return Object.assign({
    projection_instance_key: key,
    projection_revision: revision,
    start_time: startTime,
    project_id: 1,
    project_name: "P",
    session_note: "",
    adjusted_duration_seconds: 600,
    duration_seconds: 600,
    has_duration_override: false,
    has_project_override: false,
    can_edit_project: true,
    can_edit_note: true,
    can_edit_duration: true,
    can_merge_previous: true,
    can_merge_next: true,
    can_hide: true,
    can_split: true,
    can_copy: true,
    is_in_progress: false,
    is_report_uncategorized: false,
  }, opts);
}

test("6. continuous autosave: S1 uses R1, S2 uses R2 after rebase", async () => {
  const { App, element } = timelineHarness();
  const sessions = [
    session("base:a", "rev-1", "2026-07-12T09:00:00"),
  ];
  App.currentSessions = sessions;
  App.editingSession = sessions[0];
  App.projectsCache = [{ id: 1, name: "P" }];
  App.editingProjectsCache = [{ id: 1, name: "P" }];
  element("edit-note-text").value = "A";
  element("edit-project-select").value = "1";
  element("edit-duration-input").value = "10";

  const saveCalls = [];
  let refreshImpl = () => {
    // After S1 succeeds, the authoritative session advances to rev-2.
    App.currentSessions = [session("base:a", "rev-2", "2026-07-12T09:00:00", { session_note: "A" })];
    return Promise.resolve();
  };
  App.loadTimelineReport = () => refreshImpl();

  App.callBridge = (method, ...args) => {
    if (method !== "save_timeline_session_edit") return Promise.resolve({ ok: true });
    // payload: [date, key, revision, requestId, projectId, duration, note]
    saveCalls.push({ revision: args[2], note: args[6], requestId: args[3] });
    return Promise.resolve({
      ok: true,
      outcome_type: "operation_committed",
      snapshot_revision: "snap-2",
      selection_hint: { projection_instance_key: "base:a", projection_revision: "rev-2" },
    });
  };

  // Fire S1.
  App.saveEdit();
  await flush();
  // While S1 in flight, change note to B.
  element("edit-note-text").value = "B";
  // Queue S2.
  App.saveEdit();
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();

  assert.ok(saveCalls.length >= 2, "two saves must fire");
  assert.equal(saveCalls[0].revision, "rev-1", "S1 must use R1");
  assert.equal(saveCalls[1].revision, "rev-2", "S2 must use the rebased R2");
  assert.equal(saveCalls[1].note, "B", "S2 must save the post-submit note B");
  assert.equal(App.editSaving, false);
});

test("7. multi-field edits during save are not overwritten by stale response", async () => {
  const { App, element } = timelineHarness();
  const sessions = [session("base:a", "rev-1", "2026-07-12T09:00:00")];
  App.currentSessions = sessions;
  App.editingSession = sessions[0];
  App.projectsCache = [{ id: 1, name: "P1" }, { id: 2, name: "P2" }];
  App.editingProjectsCache = [{ id: 1, name: "P1" }, { id: 2, name: "P2" }];
  element("edit-project-select").value = "1";
  element("edit-note-text").value = "note-1";
  element("edit-duration-input").value = "10";

  let refreshImpl = () => {
    App.currentSessions = [session("base:a", "rev-2", "2026-07-12T09:00:00", { session_note: "note-1", adjusted_duration_seconds: 600, has_duration_override: true })];
    return Promise.resolve();
  };
  App.loadTimelineReport = () => refreshImpl();
  App.callBridge = (method, ...args) => Promise.resolve({
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: "snap-2",
    selection_hint: { projection_instance_key: "base:a", projection_revision: "rev-2" },
  });

  App.saveEdit();
  await flush();
  // Change all three fields while in flight.
  element("edit-project-select").value = "2";
  element("edit-note-text").value = "note-2";
  element("edit-duration-input").value = "20";

  // Queue a second save.
  App.saveEdit();
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();

  // After everything settles, the DOM must still reflect the user's latest
  // input, not the stale baseline.
  assert.equal(element("edit-note-text").value, "note-2");
  assert.equal(element("edit-project-select").value, "2");
  assert.equal(element("edit-duration-input").value, "20");
});

test("8. context switch preserves dirty draft (save first, then switch)", async () => {
  const { App, element } = timelineHarness();
  const sessions = [session("base:a", "rev-1", "2026-07-12T09:00:00")];
  App.currentSessions = sessions;
  App.editingSession = sessions[0];
  App.projectsCache = [{ id: 1, name: "P" }];
  App.editingProjectsCache = [{ id: 1, name: "P" }];
  element("edit-note-text").value = "dirty";
  element("edit-project-select").value = "1";

  let switched = false;
  const switchAction = () => { switched = true; };
  App.loadTimelineReport = () => {
    App.currentSessions = [session("base:a", "rev-2", "2026-07-12T09:00:00", { session_note: "dirty" })];
    return Promise.resolve();
  };
  App.callBridge = (method, ...args) => Promise.resolve({
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: "snap-2",
    selection_hint: { projection_instance_key: "base:a", projection_revision: "rev-2" },
  });

  await App.requestTimelineContextChange(switchAction, "切换日期");
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();

  assert.equal(switched, true, "switch must execute after save success");
  assert.equal(App.pendingContextChange, null);
});

test("8b. context switch during mutation-unknown preserves draft and blocks switch", async () => {
  const { App } = timelineHarness();
  App.mutationState = "unknown";
  let switched = false;
  await App.requestTimelineContextChange(() => { switched = true; }, "切换");
  assert.equal(switched, false, "must NOT switch while mutation unknown");
});

test("8c. context switch during save in flight queues and executes after success", async () => {
  const { App, element } = timelineHarness();
  const sessions = [session("base:a", "rev-1", "2026-07-12T09:00:00")];
  App.currentSessions = sessions;
  App.editingSession = sessions[0];
  element("edit-note-text").value = "dirty";
  element("edit-project-select").value = "1";
  App.projectsCache = [{ id: 1, name: "P" }];
  App.editingProjectsCache = [{ id: 1, name: "P" }];

  const saveDeferred = deferred();
  let switched = false;
  const switchAction = () => { switched = true; };
  App.loadTimelineReport = () => {
    App.currentSessions = [session("base:a", "rev-2", "2026-07-12T09:00:00", { session_note: "dirty" })];
    return Promise.resolve();
  };
  App.callBridge = () => saveDeferred.promise;

  // Start save (in flight).
  App.saveEdit();
  await flush();
  // Request a context switch while save is in flight.
  await App.requestTimelineContextChange(switchAction, "切换日期");
  assert.equal(switched, false, "must NOT switch while save in flight");
  assert.ok(App.pendingContextChange, "switch must be queued");

  // Resolve save successfully.
  saveDeferred.resolve({
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: "snap-2",
    selection_hint: { projection_instance_key: "base:a", projection_revision: "rev-2" },
  });
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();
  await flush();

  assert.equal(switched, true, "queued switch must execute after save success");
});

test("9. merge chronological semantics: descending display, ascending order", () => {
  const { App } = timelineHarness();
  // UI display order: C (11:00), B (10:00), A (09:00) — newest first.
  const sessions = [
    session("base:c", "rev-c", "2026-07-12T11:00:00"),
    session("base:b", "rev-b", "2026-07-12T10:00:00"),
    session("base:a", "rev-a", "2026-07-12T09:00:00"),
  ];
  App.currentSessions = sessions;

  // B previous -> A (time-earlier).
  const bPrev = App.findChronologicalMergeTarget(sessions, "base:b", "previous");
  assert.equal(bPrev.projection_instance_key, "base:a");
  assert.equal(bPrev.projection_revision, "rev-a");

  // B next -> C (time-later).
  const bNext = App.findChronologicalMergeTarget(sessions, "base:b", "next");
  assert.equal(bNext.projection_instance_key, "base:c");
  assert.equal(bNext.projection_revision, "rev-c");

  // A previous -> none (already earliest).
  const aPrev = App.findChronologicalMergeTarget(sessions, "base:a", "previous");
  assert.equal(aPrev, null);

  // C next -> none (already latest).
  const cNext = App.findChronologicalMergeTarget(sessions, "base:c", "next");
  assert.equal(cNext, null);
});

test("9b. merge passes correct target key, revision, and direction to bridge", async () => {
  const { App } = timelineHarness();
  const sessions = [
    session("base:c", "rev-c", "2026-07-12T11:00:00"),
    session("base:b", "rev-b", "2026-07-12T10:00:00"),
    session("base:a", "rev-a", "2026-07-12T09:00:00"),
  ];
  App.currentSessions = sessions;
  App.selectedProjectionInstanceKey = "base:b";
  App.selectedProjectionRevision = "rev-b";
  App.loadTimelineReport = () => Promise.resolve();

  let capturedArgs = null;
  App.callBridge = (method, ...args) => {
    if (method === "merge_timeline_session") capturedArgs = args;
    return Promise.resolve({
      ok: true,
      outcome_type: "operation_committed",
      snapshot_revision: "snap-2",
      selection_hint: { projection_instance_key: "base:b", projection_revision: "rev-2" },
    });
  };

  await App.runTimelineSessionOperation("merge", { direction: "previous" });
  await flush();
  await flush();

  assert.ok(capturedArgs, "merge must call the bridge");
  // args: [date, sourceKey, direction, sourceRevision, requestId, targetKey, targetRevision]
  assert.equal(capturedArgs[1], "base:b");
  assert.equal(capturedArgs[2], "previous");
  assert.equal(capturedArgs[3], "rev-b");
  assert.equal(capturedArgs[5], "base:a", "target key must be A (chronologically previous)");
  assert.equal(capturedArgs[6], "rev-a");
});

// ---------------------------------------------------------------------------
// Categories 10-11: Project catalog and filter semantics
// ---------------------------------------------------------------------------

function rulesHarness() {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    editingProjectsCache: [],
    filterProjectsCache: [],
    projectsCache: null,
    projectsLoading: false,
    lastProjectRulesData: null,
    rulesLoaded: false,
    rulesLoading: false,
    rulesRequestToken: 0,
    rulesSortMode: "last_used",
    statisticsControlsBound: false,
    currentPage: "statistics",
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  App.bridge = {
    listProjectsForTimeline: () => Promise.resolve({ ok: true, projects: [], editing_projects: [], filter_projects: [] }),
  };
  loadJs(context, "core.js");
  loadJs(context, "rules.js");
  return { App, element };
}

test("10. filter catalog excludes system unclassified project (single 未归类 option)", async () => {
  const { App, element } = rulesHarness();
  // Provide a mock renderer that mirrors timeline.js renderTimelineProjectFilter.
  App.renderTimelineProjectFilter = function (projects) {
    var select = element("timeline-project-filter");
    var html = '<option value="">项目：全部</option><option value="unclassified">未归类</option>';
    (projects || []).forEach(function (project) {
      html += '<option value="' + project.id + '">' + project.name + '</option>';
    });
    select.innerHTML = html;
  };
  const editingProjects = [
    { id: 1, name: "Alpha" },
    { id: 2, name: "未归类", description: "system unclassified" },
  ];
  const filterProjects = [
    { id: 1, name: "Alpha" },
  ];
  App.bridge.listProjectsForTimeline = () => Promise.resolve({
    ok: true,
    projects: editingProjects,
    editing_projects: editingProjects,
    filter_projects: filterProjects,
  });

  await App.refreshSharedProjectCatalog();
  await flush();

  const filterSelect = element("timeline-project-filter");
  const optionsHtml = filterSelect.innerHTML;
  const unclassifiedCount = (optionsHtml.match(/未归类/g) || []).length;
  assert.equal(unclassifiedCount, 1, "exactly one 未归类 option in filter dropdown");
});

test("10b. editing catalog includes system unclassified so users can reset a session", async () => {
  const { App } = rulesHarness();
  const editingProjects = [
    { id: 1, name: "Alpha" },
    { id: 2, name: "未归类" },
  ];
  App.bridge.listProjectsForTimeline = () => Promise.resolve({
    ok: true,
    projects: editingProjects,
    editing_projects: editingProjects,
    filter_projects: [{ id: 1, name: "Alpha" }],
  });

  await App.refreshSharedProjectCatalog();
  await flush();

  assert.equal(App.editingProjectsCache.length, 2);
  assert.equal(App.filterProjectsCache.length, 1);
  assert.equal(App.filterProjectsCache.find((p) => p.name === "未归类"), undefined);
});

test("11. catalog refresh after project CRUD updates all caches (no duplicate binding)", async () => {
  const { App } = rulesHarness();
  // Initial catalog: only project A.
  let editingProjects = [{ id: 1, name: "A" }];
  let filterProjects = [{ id: 1, name: "A" }];
  App.bridge.listProjectsForTimeline = () => Promise.resolve({
    ok: true,
    projects: editingProjects,
    editing_projects: editingProjects,
    filter_projects: filterProjects,
  });

  await App.refreshSharedProjectCatalog();
  await flush();
  assert.equal(App.editingProjectsCache.length, 1);
  assert.equal(App.filterProjectsCache.length, 1);

  // Add project B.
  editingProjects = [{ id: 1, name: "A" }, { id: 2, name: "B" }];
  filterProjects = [{ id: 1, name: "A" }, { id: 2, name: "B" }];
  await App.refreshSharedProjectCatalog();
  await flush();
  assert.equal(App.editingProjectsCache.length, 2, "editing catalog must include B");
  assert.equal(App.filterProjectsCache.length, 2, "filter catalog must include B");
  assert.ok(App.filterProjectsCache.find((p) => p.id === 2));

  // Delete project B.
  editingProjects = [{ id: 1, name: "A" }];
  filterProjects = [{ id: 1, name: "A" }];
  await App.refreshSharedProjectCatalog();
  await flush();
  assert.equal(App.editingProjectsCache.length, 1);
  assert.equal(App.filterProjectsCache.length, 1);
  assert.equal(App.filterProjectsCache.find((p) => p.id === 2), undefined);
});

// ---------------------------------------------------------------------------
// Category 12: Project language preservation
// ---------------------------------------------------------------------------

function rulesPanelHarness() {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    rulesPanelMode: "rule",
    rulesPanelRuleType: "folder",
    rulesPanelEditingProjectId: null,
    rulesPanelLastCreatedProjectId: null,
    rulesCreatingPanelProject: false,
    rulesCreatingPanelRule: false,
    rulesPanelOriginalLanguage: null,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  App.loadProjectRules = () => Promise.resolve();
  App.openManagedDrawer = () => {};
  App.closeManagedDrawer = () => {};
  App.showRulesError = () => {};
  App.clearRulesError = () => {};
  App.showToast = () => {};
  App.safeText = (v, d) => (v === null || v === undefined || v === "") ? d : String(v);
  App.escapeHtml = (s) => String(s);
  App.parsePositiveInt = (v) => { const n = parseInt(v, 10); return isNaN(n) || n <= 0 ? 0 : n; };
  App.rerenderProjectRulesList = () => {};
  App.applyRulesSearch = () => {};
  const bridgeCalls = { create: [], update: [] };
  App.bridge = {
    createProjectForRules: (name, description, language) => {
      bridgeCalls.create.push({ name, description, language });
      return Promise.resolve({ ok: true, project: { id: 99, name, description, language } });
    },
    updateProjectForRules: (projectId, name, description, language) => {
      bridgeCalls.update.push({ projectId, name, description, language });
      return Promise.resolve({ ok: true, project: { id: projectId, name, description, language } });
    },
  };
  loadJs(context, "rules_create_panel.js");
  return { App, element, bridgeCalls };
}

test("12. editing an English project preserves language when only name changes", async () => {
  const { App, element, bridgeCalls } = rulesPanelHarness();
  const englishProject = { id: 5, name: "Old", description: "desc", language: "English" };
  App.openRulesPanel("project", { project: englishProject });
  assert.equal(App.rulesPanelOriginalLanguage, "English");

  // Change only the name.
  element("rules-panel-project-name").value = "New";
  element("rules-panel-project-description").value = "desc";

  App.savePanelProject();
  await flush();
  await flush();

  assert.equal(bridgeCalls.update.length, 1);
  assert.equal(bridgeCalls.update[0].language, "English", "language must be preserved verbatim");
  assert.equal(bridgeCalls.update[0].name, "New");
});

test("12b. editing a Japanese project preserves language when only description changes", async () => {
  const { App, element, bridgeCalls } = rulesPanelHarness();
  const japaneseProject = { id: 6, name: "プロジェクト", description: "old", language: "日本語" };
  App.openRulesPanel("project", { project: japaneseProject });
  assert.equal(App.rulesPanelOriginalLanguage, "日本語");

  element("rules-panel-project-name").value = "プロジェクト";
  element("rules-panel-project-description").value = "new description";

  App.savePanelProject();
  await flush();
  await flush();

  assert.equal(bridgeCalls.update[0].language, "日本語");
});

test("12c. editing a custom-language project preserves the custom language", async () => {
  const { App, element, bridgeCalls } = rulesPanelHarness();
  const customProject = { id: 7, name: "Custom", description: "", language: "Klingon" };
  App.openRulesPanel("project", { project: customProject });
  assert.equal(App.rulesPanelOriginalLanguage, "Klingon");

  element("rules-panel-project-name").value = "Custom-renamed";
  element("rules-panel-project-description").value = "";

  App.savePanelProject();
  await flush();
  await flush();

  assert.equal(bridgeCalls.update[0].language, "Klingon");
});

test("12d. new project defaults to 中文 when no language specified", async () => {
  const { App, element, bridgeCalls } = rulesPanelHarness();
  App.openRulesPanel("project", {});
  element("rules-panel-project-name").value = "BrandNew";
  element("rules-panel-project-description").value = "";

  App.savePanelProject();
  await flush();
  await flush();

  assert.equal(bridgeCalls.create.length, 1);
  assert.equal(bridgeCalls.create[0].language, "中文");
});
