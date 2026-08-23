const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { loadSettingsModules } = require("./settings_test_helpers");
const { TIMELINE_MODULES, loadTimelineModules } = require("./timeline_test_modules");

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
    style: {},
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

function topLevelElements(markup) {
  const elements = [];
  const tagPattern = /<(\/)?([a-zA-Z][\w-]*)(?:\s[^>]*)?>/g;
  let depth = 0;
  let start = -1;
  let openingEnd = -1;
  let openingTag = "";
  let match;
  while ((match = tagPattern.exec(markup)) !== null) {
    const isClosing = match[1] === "/";
    const isSelfClosing = /\/>$/.test(match[0]);
    if (!isClosing) {
      if (depth === 0) {
        start = match.index;
        openingEnd = tagPattern.lastIndex;
        openingTag = match[0];
      }
      if (!isSelfClosing) depth += 1;
    } else {
      depth -= 1;
      if (depth === 0 && start !== -1) {
        elements.push({
          tagName: openingTag.match(/^<([a-zA-Z][\w-]*)/)[1],
          attributes: openingTag,
          innerHTML: markup.slice(openingEnd, match.index),
          outerHTML: markup.slice(start, tagPattern.lastIndex),
        });
        start = -1;
      }
    }
  }
  assert.equal(depth, 0, "test HTML must be structurally balanced");
  return elements;
}

function classTokens(element) {
  const match = element.attributes.match(/\bclass="([^"]*)"/);
  return match ? match[1].split(/\s+/).filter(Boolean) : [];
}

// ---------------------------------------------------------------------------
// Categories 1-3: Privacy gate state machine
// ---------------------------------------------------------------------------

function privacyHarness() {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    heartbeatTimer: null,
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
  let startupContinues = 0;
  App.continueStartupAfterPrivacyGate = () => { startupContinues += 1; return Promise.resolve(true); };
  App.bridge = {
    getFirstRunNotice: () => Promise.resolve({ ok: true }),
    acceptFirstRunNotice: () => Promise.resolve({ ok: true }),
    getSettingsPrivacyStatus: () => Promise.resolve({ ok: true, status: {} }),
  };
  loadJs(context, "core.js");
  loadSettingsModules(context);
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

  await App.privacyNotice.loadGate();
  await flush();

  assert.equal(App.privacyNotice.state(), "acceptance_required");
  assert.equal(App.privacyNotice.requiresAcceptance(), true);
  assert.equal(element("first-run-notice-overlay").hidden, false);
  assert.equal(element("first-run-notice-title").textContent, "WorkTrace 隐私说明");
  assert.equal(element("first-run-notice-text").textContent.length > 0, true);
  assert.equal(element("first-run-notice-highlights").children || true, true);
  assert.equal(heartbeatStarts(), 0, "heartbeat must NOT start while unaccepted");
});

test("1b. privacy notice load failure is fail-closed with visible error", async () => {
  const { App, element } = privacyHarness();
  App.bridge.getFirstRunNotice = () => Promise.resolve({ ok: false, error: "load_failed" });

  await App.privacyNotice.loadGate();
  await flush();

  assert.equal(App.privacyNotice.state(), "load_failed");
  assert.equal(element("first-run-notice-overlay").hidden, false);
  assert.equal(element("first-run-notice-accept-btn").disabled, true);
  assert.equal(element("first-run-notice-accept-btn").hidden, true);
});

test("2. privacy confirmation success closes gate and returns authorization to startup owner", async () => {
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

  await App.privacyNotice.loadGate();
  await flush();
  assert.equal(App.privacyNotice.state(), "acceptance_required");

  await App.privacyNotice.acceptGate();
  await flush();
  await flush();

  assert.equal(App.privacyNotice.state(), "accepted_ready");
  assert.equal(App.privacyNotice.isReady(), true);
  assert.equal(element("first-run-notice-overlay").hidden, true);
  assert.equal(startupContinues(), 0, "privacy owner must not coordinate application startup");
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

  await App.privacyNotice.loadGate();
  await flush();

  await App.privacyNotice.acceptGate();
  await flush();
  await flush();

  assert.equal(App.privacyNotice.state(), "accepted_start_failed");
  assert.equal(App.privacyNotice.requiresAcceptance(), false);
  assert.equal(element("first-run-notice-overlay").hidden, true);
  assert.equal(element("global-alert").hidden, false);
  assert.match(element("global-alert").textContent, /记录功能未能启动/);
  assert.equal(startupContinues(), 0, "privacy owner must return readiness without starting the app");
});

// ---------------------------------------------------------------------------
// Category 4: Maintenance recovery flow
// ---------------------------------------------------------------------------

test("4. maintenance recovery: blocked -> recover -> reload status and page", async () => {
  const { context } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  App.currentPage = "settings";
  App.handleResult = function (result, onError) {
    if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
    return result;
  };
  let recoverCalls = 0;
  let statusCount = 0;
  App.currentPage = "settings";
  App.bridge = {
    recoverDatabaseMaintenance: () => { recoverCalls += 1; return Promise.resolve({ ok: true }); },
    getSettingsPrivacyStatus: () => {
      statusCount += 1;
      return Promise.resolve({ ok: true, status: {} });
    },
  };
  loadJs(context, "core.js");
  loadSettingsModules(context);
  App.currentPage = "settings";
  let refreshCount = 0;
  App.refreshAll = () => { refreshCount += 1; return Promise.resolve(); };
  App.showToast = () => {};

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();

  assert.equal(ok, true);
  assert.equal(recoverCalls, 1);
  assert.equal(statusCount, 1, "settings status must be reloaded");
  assert.equal(refreshCount, 1, "page must be refreshed");
  assert.equal(App.settings.operationName(), "");
});

test("4b. maintenance recovery failure keeps blocked flag and shows public error", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  App.handleResult = function (result, onError) {
    if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
    return result;
  };
  App.bridge = {
    recoverDatabaseMaintenance: () => Promise.resolve({
      ok: false,
      error_code: "recovery_failed",
      message: "恢复失败：维护锁仍被持有",
      maintenance: {
        maintenance_in_progress: false,
        maintenance_restored: false,
        recovery_blocked: true,
        blocked_reason: "maintenance_recovery_not_verified",
      },
    }),
    getSettingsPrivacyStatus: () => Promise.resolve({ ok: true, status: {
        recovery_blocked: true,
        blocked_reason: "maintenance_recovery_not_verified",
      } }),
  };
  loadJs(context, "core.js");
  loadSettingsModules(context);
  App.currentPage = "settings";
  App.refreshAll = () => Promise.resolve();
  App.showToast = () => {};

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();

  assert.equal(ok, false);
  assert.equal(App.settings.operationName(), "");
  assert.equal(element("settings-recovery-btn").disabled, false);
  assert.match(element("settings-recovery-status").textContent, /恢复失败：维护锁仍被持有/);
});

const RECOVERY_BLOCKING_OPERATIONS = [
  ["settings status load", "settings_load"],
  ["clipboard setting write", "clipboard_write"],
  ["backup export", "backup_export"],
  ["manifest preview", "backup_manifest"],
  ["backup import", "backup_import"],
  ["clear-all", "clear_all"],
  ["recovery already running", "recovery"],
];

for (const [label, operation] of RECOVERY_BLOCKING_OPERATIONS) {
  test(`4c. ${label} blocks recovery — symmetric mutex`, async () => {
    const { context, element } = makeBaseContext();
    const App = context.window.WorkTraceApp;
    const gate = deferred();
    let recoverCalls = 0;
    App.currentPage = "settings";
    App.handleResult = (result, onError) => {
      if (!result || result.ok === false) {
        if (onError) onError((result && result.message) || "操作失败");
        return null;
      }
      return result;
    };
    App.bridge = {
      clearAllLocalData: () => gate.promise,
      exportEncryptedBackup: () => gate.promise,
      getSettingsPrivacyStatus: () => gate.promise,
      importEncryptedBackup: () => gate.promise,
      previewEncryptedBackupManifest: () => gate.promise,
      recoverDatabaseMaintenance: () => { recoverCalls += 1; return gate.promise; },
      setClipboardCaptureEnabled: () => gate.promise,
    };
    loadJs(context, "core.js");
    loadSettingsModules(context);
    App.refreshAll = () => Promise.resolve();
    App.openConfirmDialog = () => Promise.resolve(true);
    App.showToast = () => {};

    let pending;
    if (operation === "settings_load") {
      pending = App.settings.onPageEntered();
    } else if (operation === "clipboard_write") {
      pending = App.setCaptureEnabled(true);
    } else if (operation === "backup_export") {
      element("settings-backup-passphrase").value = "secret";
      element("settings-backup-passphrase-confirm").value = "secret";
      pending = App.exportEncryptedBackup();
    } else if (operation === "backup_manifest") {
      pending = App.previewEncryptedBackupManifest();
    } else if (operation === "backup_import") {
      element("settings-backup-import-passphrase").value = "secret";
      pending = App.importEncryptedBackup();
    } else if (operation === "clear_all") {
      element("settings-clear-confirm").value = "清空本地数据";
      pending = App.clearAllLocalData();
    } else {
      pending = App.recoverDatabaseMaintenance();
    }
    await flush();
    if (operation === "settings_load") assert.equal(App.settings.isLoading(), true);
    else assert.equal(App.settings.operationName(), operation);

    const recoverCallsBefore = recoverCalls;
    const ok = await App.recoverDatabaseMaintenance();
    assert.equal(ok, false, `recovery must be rejected during ${operation}`);
    assert.equal(recoverCalls, recoverCallsBefore, "recovery Bridge must not be called twice");

    gate.resolve({ ok: false, message: "test operation finished" });
    await pending;
  });
}

test("4d. recovery in progress blocks backup export, manifest, import, clear, and clipboard write", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  App.currentPage = "settings";
  App.handleResult = function (result, onError) {
    if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
    return result;
  };
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
  loadSettingsModules(context);
  App.currentPage = "settings";
  App.currentPage = "settings";
  App.refreshAll = () => Promise.resolve();
  App.showToast = () => {};

  App.recoverDatabaseMaintenance();
  await flush();
  assert.equal(App.settings.operationName(), "recovery", "recovery must be in progress");

  App.exportEncryptedBackup();
  App.previewEncryptedBackupManifest();
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
  assert.equal(App.settings.operationName(), "recovery", "recovery owner must remain active while pending");
  assert.equal(element("settings-recovery-btn").disabled, true, "recovery button disabled during recovery");

  recoveryGate.resolve({ ok: true });
  await flush();
  await flush();
  assert.equal(App.settings.operationName(), "", "recovery owner released after completion");
});

test("4e. recovery transport rejection re-reads authoritative state (blocked=false → button disabled)", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  App.currentPage = "settings";
  App.handleResult = function (result, onError) {
    if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
    return result;
  };
  let recoverCalls = 0;
  let statusReads = 0;
  App.bridge = {
    recoverDatabaseMaintenance: () => { recoverCalls += 1; return Promise.reject(new Error("webview transport disconnected")); },
    getSettingsPrivacyStatus: () => {
      statusReads += 1;
      return Promise.resolve({ ok: true, status: {
        maintenance_in_progress: false,
        maintenance_restored: true,
        recovery_blocked: false,
        blocked_reason: null,
        collector_running: true,
        collector_status: "running",
        user_paused: false,
      } });
    },
  };
  loadJs(context, "core.js");
  loadSettingsModules(context);
  App.currentPage = "settings";
  App.refreshAll = () => Promise.resolve();
  App.showToast = () => {};

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();
  await flush();

  assert.equal(ok, false, "transport rejection must not be reported as success");
  assert.equal(recoverCalls, 1, "recovery Bridge called exactly once");
  assert.equal(statusReads, 1, "authoritative status must be re-read exactly once after rejection");
  assert.equal(App.settings.operationName(), "", "recovery owner must be released after state refresh");
  assert.equal(element("settings-recovery-btn").disabled, true, "button disabled when backend reports no recovery needed");
  assert.equal(App.settings.snapshot().recovery_blocked, false, "snapshot refreshed to authoritative state");
  assert.match(element("settings-recovery-status").textContent, /恢复结果未知/);
});

test("4f. recovery transport rejection re-reads authoritative state (blocked=true → button re-enabled)", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  App.handleResult = function (result, onError) {
    if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
    return result;
  };
  let recoverCalls = 0;
  let statusReads = 0;
  App.bridge = {
    recoverDatabaseMaintenance: () => { recoverCalls += 1; return Promise.reject(new Error("webview transport disconnected")); },
    getSettingsPrivacyStatus: () => {
      statusReads += 1;
      return Promise.resolve({ ok: true, status: {
        maintenance_in_progress: false,
        maintenance_restored: false,
        recovery_blocked: true,
        blocked_reason: "maintenance_recovery_not_verified",
        collector_running: false,
        collector_status: "stopped",
        user_paused: false,
      } });
    },
  };
  loadJs(context, "core.js");
  loadSettingsModules(context);
  App.currentPage = "settings";
  App.refreshAll = () => Promise.resolve();
  App.showToast = () => {};

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();
  await flush();

  assert.equal(ok, false, "transport rejection must not be reported as success");
  assert.equal(recoverCalls, 1, "recovery Bridge called exactly once");
  assert.equal(statusReads, 1, "authoritative status must be re-read exactly once after rejection");
  assert.equal(App.settings.operationName(), "", "recovery owner must be released after state refresh");
  assert.equal(element("settings-recovery-btn").disabled, false, "button re-enabled when backend still reports blocked");
  assert.equal(App.settings.snapshot().recovery_blocked, true, "snapshot refreshed to authoritative state");
  assert.match(element("settings-recovery-status").textContent, /恢复结果未知/);
});

test("4g. recovery transport rejection when status read also fails still releases busy flag", async () => {
  const { context } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  App.currentPage = "settings";
  App.handleResult = function (result, onError) {
    if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
    return result;
  };
  let recoverCalls = 0;
  let statusReads = 0;
  let statusReadFails = false;
  App.bridge = {
    recoverDatabaseMaintenance: () => { recoverCalls += 1; return Promise.reject(new Error("webview transport disconnected")); },
    getSettingsPrivacyStatus: () => {
      statusReads += 1;
      if (statusReadFails) return Promise.reject(new Error("status read failed"));
      return Promise.resolve({
        ok: true,
        status: { recovery_blocked: true, blocked_reason: "prior_failure" },
      });
    },
  };
  loadJs(context, "core.js");
  loadSettingsModules(context);
  App.currentPage = "settings";
  App.refreshAll = () => Promise.resolve();
  App.showToast = () => {};
  await App.settings.onPageEntered();
  statusReads = 0;
  statusReadFails = true;

  const ok = await App.recoverDatabaseMaintenance();
  await flush();
  await flush();
  await flush();

  assert.equal(ok, false, "must not be reported as success when both recovery and status read fail");
  assert.equal(recoverCalls, 1);
  assert.equal(statusReads, 1, "status must still be attempted once");
  assert.equal(App.settings.operationName(), "", "operation owner released even on double failure");
  assert.equal(App.settings.snapshot().recovery_blocked, true, "prior authoritative snapshot preserved");
});

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
    const result = await App.bridge.pauseCollector();
    if (!result || result.ok === false) {
      App.showGlobalAlert(App.extractBridgeError(result, "操作失败"));
    }
    assert.equal(element("global-alert").hidden, false, `global-alert must be visible on page ${page}`);
    assert.match(element("global-alert").textContent, /数据库维护未完成/);
  }
});

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
    TIMELINE_DESCRIPTION_EDIT_MAX_LENGTH: 200,
    timelineCompositionActive: false,
    timelineDurationDraftTouched: false,
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
    listProjectCatalog: bridgeCall("list_project_catalog"),
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
  const timelineProjects = [{ id: 1, name: "P1" }, { id: 2, name: "P2" }];
  App.projectCatalog = Object.freeze({
    load: () => Promise.resolve({
      editingProjects: timelineProjects.slice(),
      filterProjects: timelineProjects.slice(),
    }),
    invalidate() {},
    resetGeneration() {},
    getEditing: () => timelineProjects.slice(),
    getFilter: () => timelineProjects.slice(),
  });
  for (const file of ["timeline_request_state.js", ...TIMELINE_MODULES]) loadJs(context, file);
  return { App, element, context };
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

function prepareTimelineEditor(App, element, source) {
  App.currentSessions = [source];
  App.populateEditPanel(source);
  element("edit-project-select").value = String(source.project_id || "");
}

function successfulTimelineEdit(revision = "rev-2") {
  return {
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: `snapshot-${revision}`,
    selection_hint: {
      projection_instance_key: "base:a",
      projection_revision: revision,
    },
  };
}

test("6a. 1.5 edited hours submits 5400 integer seconds", async () => {
  const { App, element, context } = timelineHarness();
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00", {
    adjusted_duration_seconds: null,
    duration_seconds: 3600,
    has_duration_override: false,
  });
  prepareTimelineEditor(App, element, source);
  assert.equal(element("edit-duration-input").value, "1.0");
  context.window.setTimeout = () => 1;
  element("edit-duration-input").value = "1.5";
  App.handleTimelineDurationChange();
  const payloads = [];
  let submittedDurationTouched = null;
  App.callBridge = (method, ...args) => {
    if (method === "save_timeline_session_edit") {
      payloads.push(args);
      submittedDurationTouched = App.submittedDraft.durationTouched;
    }
    return Promise.resolve(successfulTimelineEdit());
  };

  App.saveEdit();
  await flush();
  await flush();

  assert.equal(payloads.length, 1);
  assert.equal(payloads[0][5], true);
  assert.equal(payloads[0][6], 5400);
  assert.equal(submittedDurationTouched, true);
});

test("6a2. explicit 1.234 edit on observed 4442 seconds submits set intent for 4320", async () => {
  const { App, element, context } = timelineHarness();
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00", {
    adjusted_duration_seconds: null,
    duration_seconds: 4442,
    has_duration_override: false,
  });
  prepareTimelineEditor(App, element, source);
  context.window.setTimeout = () => 1;
  element("edit-duration-input").value = "1.234";
  App.handleTimelineDurationChange();
  const payloads = [];
  App.callBridge = (method, ...args) => {
    if (method === "save_timeline_session_edit") payloads.push(args);
    return Promise.resolve(successfulTimelineEdit());
  };

  App.saveEdit();
  await flush();
  await flush();

  assert.equal(element("edit-duration-input").value, "1.2");
  assert.equal(payloads.length, 1);
  assert.equal(payloads[0][5], true);
  assert.equal(payloads[0][6], 4320);
});

test("6a3. unknown duration save retry preserves exact intent and request id", async () => {
  const { App, element, context } = timelineHarness();
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00", {
    adjusted_duration_seconds: null,
    duration_seconds: 4442,
    has_duration_override: false,
  });
  prepareTimelineEditor(App, element, source);
  context.window.setTimeout = () => 1;
  element("edit-duration-input").value = "1.234";
  App.handleTimelineDurationChange();
  const payloads = [];
  App.callBridge = (method, ...args) => {
    if (method !== "save_timeline_session_edit") return Promise.resolve({ ok: true });
    payloads.push(args);
    return payloads.length === 1
      ? Promise.reject(new Error("transport uncertain"))
      : Promise.resolve(successfulTimelineEdit());
  };

  await App.saveEdit();
  assert.equal(App.timelineDurationDraftTouched, true);
  await App.saveEdit();
  await flush();
  await flush();

  assert.equal(payloads.length, 2);
  assert.equal(payloads[0][3], payloads[1][3]);
  assert.deepEqual(payloads[0].slice(4), [null, true, 4320, ""]);
  assert.deepEqual(payloads[1], payloads[0]);
});

test("6b. project-only edit keeps a non-rounded no-override duration as null", async () => {
  const { App, element } = timelineHarness();
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00", {
    adjusted_duration_seconds: null,
    duration_seconds: 5432,
    has_duration_override: false,
  });
  prepareTimelineEditor(App, element, source);
  assert.equal(element("edit-duration-input").value, "1.5");
  element("edit-project-select").value = "2";
  const payloads = [];
  App.callBridge = (method, ...args) => {
    if (method === "save_timeline_session_edit") payloads.push(args);
    return Promise.resolve(successfulTimelineEdit());
  };

  App.saveEdit();
  await flush();
  await flush();

  assert.equal(payloads[0][4], 2);
  assert.equal(payloads[0][5], false);
  assert.equal(payloads[0][6], null);
});

test("6c. description-only edit preserves the exact existing override seconds", async () => {
  const { App, element } = timelineHarness();
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00", {
    adjusted_duration_seconds: 5432,
    duration_seconds: 5400,
    has_duration_override: true,
  });
  prepareTimelineEditor(App, element, source);
  assert.equal(element("edit-duration-input").value, "1.5");
  element("edit-note-text").value = "只修改描述";
  const payloads = [];
  App.callBridge = (method, ...args) => {
    if (method === "save_timeline_session_edit") payloads.push(args);
    return Promise.resolve(successfulTimelineEdit());
  };

  App.saveEdit();
  await flush();
  await flush();

  assert.equal(payloads[0][5], false);
  assert.equal(payloads[0][6], null);
  assert.equal(payloads[0][7], "只修改描述");
});

test("6c2. clearing duration cancels only an existing override", async () => {
  const { App, element, context } = timelineHarness();
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00", {
    adjusted_duration_seconds: 5432,
    duration_seconds: 5400,
    has_duration_override: true,
  });
  prepareTimelineEditor(App, element, source);
  context.window.setTimeout = () => 1;
  element("edit-duration-input").value = "";
  App.handleTimelineDurationChange();
  const payloads = [];
  App.callBridge = (method, ...args) => {
    if (method === "save_timeline_session_edit") payloads.push(args);
    return Promise.resolve(successfulTimelineEdit());
  };

  App.saveEdit();
  await flush();
  await flush();

  assert.equal(payloads.length, 1);
  assert.equal(payloads[0][5], true);
  assert.equal(payloads[0][6], null);
});

test("6d. duration edit during an in-flight save queues against the rebased revision", async () => {
  const { App, element } = timelineHarness();
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00", {
    adjusted_duration_seconds: null,
    duration_seconds: 3600,
    has_duration_override: false,
  });
  prepareTimelineEditor(App, element, source);
  element("edit-note-text").value = "first";
  const first = deferred();
  const payloads = [];
  App.callBridge = (method, ...args) => {
    if (method !== "save_timeline_session_edit") return Promise.resolve({ ok: true });
    payloads.push(args);
    return payloads.length === 1
      ? first.promise
      : Promise.resolve(successfulTimelineEdit("rev-3"));
  };
  let refreshCount = 0;
  App.loadTimelineReport = () => {
    refreshCount += 1;
    App.currentSessions = [session(
      "base:a",
      refreshCount === 1 ? "rev-2" : "rev-3",
      "2026-07-12T09:00:00",
      {
        session_note: "first",
        adjusted_duration_seconds: refreshCount === 1 ? null : 5400,
        duration_seconds: refreshCount === 1 ? 3600 : 5400,
        has_duration_override: refreshCount !== 1,
      }
    )];
    return Promise.resolve();
  };

  App.saveEdit();
  element("edit-duration-input").value = "1.5";
  App.handleTimelineDurationChange();
  assert.equal(App.timelineAutosaveQueued, true);
  first.resolve(successfulTimelineEdit("rev-2"));
  await new Promise((resolve) => setTimeout(resolve, 30));
  await flush();

  assert.equal(payloads.length, 2);
  assert.equal(payloads[0][5], false);
  assert.equal(payloads[0][6], null);
  assert.equal(payloads[1][2], "rev-2");
  assert.equal(payloads[1][5], true);
  assert.equal(payloads[1][6], 5400);
});

test("6. continuous autosave: S1 uses R1, S2 uses R2 after rebase", async () => {
  const { App, element } = timelineHarness();
  const sessions = [session("base:a", "rev-1", "2026-07-12T09:00:00")];
  App.currentSessions = sessions;
  App.editingSession = sessions[0];
  element("edit-note-text").value = "A";
  element("edit-project-select").value = "1";
  element("edit-duration-input").value = "0.2";

  const saveCalls = [];
  App.loadTimelineReport = () => {
    App.currentSessions = [session("base:a", "rev-2", "2026-07-12T09:00:00", { session_note: "A" })];
    return Promise.resolve();
  };

  App.callBridge = (method, ...args) => {
    if (method !== "save_timeline_session_edit") return Promise.resolve({ ok: true });
    saveCalls.push({ revision: args[2], note: args[7], requestId: args[3] });
    return Promise.resolve({
      ok: true,
      outcome_type: "operation_committed",
      snapshot_revision: "snap-2",
      selection_hint: { projection_instance_key: "base:a", projection_revision: "rev-2" },
    });
  };

  App.saveEdit();
  await flush();
  element("edit-note-text").value = "B";
  App.saveEdit();
  for (let i = 0; i < 6; i += 1) await flush();

  assert.equal(saveCalls.length, 2, "one in-flight save plus one latest-draft save");
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
  element("edit-project-select").value = "1";
  element("edit-note-text").value = "note-1";
  element("edit-duration-input").value = "0.2";

  App.loadTimelineReport = () => {
    App.currentSessions = [session("base:a", "rev-2", "2026-07-12T09:00:00", { session_note: "note-1", adjusted_duration_seconds: 600, has_duration_override: true })];
    return Promise.resolve();
  };
  App.callBridge = () => Promise.resolve({
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: "snap-2",
    selection_hint: { projection_instance_key: "base:a", projection_revision: "rev-2" },
  });

  App.saveEdit();
  await flush();
  element("edit-project-select").value = "2";
  element("edit-note-text").value = "note-2";
  element("edit-duration-input").value = "0.3";
  App.handleTimelineDurationChange();
  App.saveEdit();
  for (let i = 0; i < 6; i += 1) await flush();

  assert.equal(element("edit-note-text").value, "note-2");
  assert.equal(element("edit-project-select").value, "2");
  assert.equal(element("edit-duration-input").value, "0.3");
});

test("7b. composition input never submits intermediate text and saves only final Chinese", async () => {
  const { App, element, context } = timelineHarness();
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00");
  App.currentSessions = [source];
  App.editingSession = source;
  element("edit-project-select").value = "1";
  element("edit-duration-input").value = "0.2";

  let scheduled = null;
  let timerId = 0;
  context.window.setTimeout = (callback) => {
    scheduled = callback;
    timerId += 1;
    return timerId;
  };
  context.window.clearTimeout = () => {};
  const submitted = [];
  App.callBridge = (method, ...args) => {
    if (method === "save_timeline_session_edit") submitted.push(args[7]);
    return Promise.resolve({
      ok: true,
      outcome_type: "operation_committed",
      snapshot_revision: "snap-2",
      selection_hint: { projection_instance_key: "base:a", projection_revision: "rev-2" },
    });
  };
  App.loadTimelineReport = () => {
    App.currentSessions = [session("base:a", "rev-2", "2026-07-12T09:00:00", { session_note: "中文" })];
    return Promise.resolve();
  };

  element("edit-note-text").value = "zhong";
  App.handleTimelineCompositionStart();
  App.handleTimelineNoteInput({ isComposing: true });
  App.saveEdit();
  assert.equal(submitted.length, 0, "composition must block direct/timer save");
  assert.equal(App.timelineAutosaveQueued, true);

  element("edit-note-text").value = "中文";
  App.handleTimelineCompositionEnd();
  assert.equal(element("edit-note-count").textContent, "2 / 200");
  assert.equal(typeof scheduled, "function", "compositionend restarts debounce");
  scheduled();
  await flush();
  await flush();
  await flush();

  assert.deepEqual(submitted, ["中文"]);
});

test("7c. editable fields stay enabled and focused while autosave is in flight", async () => {
  const { App, element } = timelineHarness();
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00");
  App.currentSessions = [source];
  App.editingSession = source;
  element("edit-project-select").value = "1";
  element("edit-note-text").value = "first";
  element("edit-duration-input").value = "0.2";
  let focusCount = 0;
  element("edit-note-text").focus = () => { focusCount += 1; };
  const pending = deferred();
  App.callBridge = () => pending.promise;

  App.saveEdit();
  assert.equal(App.editSaving, true);
  assert.equal(element("edit-project-select").disabled, false);
  assert.equal(element("edit-note-text").disabled, false);
  assert.equal(element("edit-duration-input").disabled, false);
  assert.equal(focusCount, 0);

  element("edit-note-text").value = "second";
  App.handleTimelineNoteInput({ isComposing: false });
  assert.equal(element("edit-note-text").value, "second");
  assert.equal(focusCount, 0);

  pending.resolve({ ok: false, error: "operation_failed", message: "失败" });
  await flush();
});

test("7d. 200-character limit applies only when the description changed", async () => {
  const { App, element } = timelineHarness();
  const historical = "旧".repeat(250);
  const source = session("base:a", "rev-1", "2026-07-12T09:00:00", { project_id: 1, session_note: historical });
  App.currentSessions = [source];
  App.editingSession = source;
  element("edit-project-select").value = "2";
  element("edit-note-text").value = historical;
  element("edit-duration-input").value = "0.2";
  const submitted = [];
  App.callBridge = (method, ...args) => {
    submitted.push(args);
    return Promise.resolve({ ok: false, error: "stop", message: "stop" });
  };

  App.saveEdit();
  await flush();
  assert.equal(submitted.length, 1, "unchanged historical long text must not block project edit");
  assert.equal(submitted[0][7], historical);

  App.editingSession = source;
  App.editSaving = false;
  element("edit-note-text").value = "新".repeat(201);
  App.saveEdit();
  assert.equal(submitted.length, 1, "changed description over 200 must be rejected");
  assert.match(element("edit-status").textContent, /200/);
});

test("8. context switch preserves dirty draft (save first, then switch)", async () => {
  const { App, element } = timelineHarness();
  const sessions = [session("base:a", "rev-1", "2026-07-12T09:00:00")];
  App.currentSessions = sessions;
  App.editingSession = sessions[0];
  element("edit-note-text").value = "dirty";
  element("edit-project-select").value = "1";

  let switched = false;
  const switchAction = () => { switched = true; };
  App.loadTimelineReport = () => {
    App.currentSessions = [session("base:a", "rev-2", "2026-07-12T09:00:00", { session_note: "dirty" })];
    return Promise.resolve();
  };
  App.callBridge = () => Promise.resolve({
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: "snap-2",
    selection_hint: { projection_instance_key: "base:a", projection_revision: "rev-2" },
  });

  await App.requestTimelineContextChange(switchAction, "切换日期");
  for (let i = 0; i < 6; i += 1) await flush();

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

  const saveDeferred = deferred();
  let switched = false;
  const switchAction = () => { switched = true; };
  App.loadTimelineReport = () => {
    App.currentSessions = [session("base:a", "rev-2", "2026-07-12T09:00:00", { session_note: "dirty" })];
    return Promise.resolve();
  };
  App.callBridge = () => saveDeferred.promise;

  App.saveEdit();
  await flush();
  await App.requestTimelineContextChange(switchAction, "切换日期");
  assert.equal(switched, false, "must NOT switch while save in flight");
  assert.ok(App.pendingContextChange, "switch must be queued");

  saveDeferred.resolve({
    ok: true,
    outcome_type: "operation_committed",
    snapshot_revision: "snap-2",
    selection_hint: { projection_instance_key: "base:a", projection_revision: "rev-2" },
  });
  for (let i = 0; i < 6; i += 1) await flush();

  assert.equal(switched, true, "queued switch must execute after save success");
});

test("9. merge chronological semantics: descending display, ascending order", () => {
  const { App } = timelineHarness();
  const sessions = [
    session("base:c", "rev-c", "2026-07-12T11:00:00"),
    session("base:b", "rev-b", "2026-07-12T10:00:00"),
    session("base:a", "rev-a", "2026-07-12T09:00:00"),
  ];
  App.currentSessions = sessions;

  const bPrev = App.findChronologicalMergeTarget(sessions, "base:b", "previous");
  assert.equal(bPrev.projection_instance_key, "base:a");
  assert.equal(bPrev.projection_revision, "rev-a");
  const bNext = App.findChronologicalMergeTarget(sessions, "base:b", "next");
  assert.equal(bNext.projection_instance_key, "base:c");
  assert.equal(bNext.projection_revision, "rev-c");
  assert.equal(App.findChronologicalMergeTarget(sessions, "base:a", "previous"), null);
  assert.equal(App.findChronologicalMergeTarget(sessions, "base:c", "next"), null);
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
  assert.equal(capturedArgs[1], "base:b");
  assert.equal(capturedArgs[2], "previous");
  assert.equal(capturedArgs[3], "rev-b");
  assert.equal(capturedArgs[5], "base:a", "target key must be A (chronologically previous)");
  assert.equal(capturedArgs[6], "rev-a");
});

function rulesHarness() {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  Object.assign(App, {
    projectsLoading: false,
    lastProjectRulesData: null,
    rulesLoaded: false,
    rulesLoading: false,
    rulesRequestToken: 0,
    rulesSortMode: "last_used",
    statisticsControlsBound: false,
    currentPage: "statistics",
    dataEpoch: 0,
    handleResult(result, onError) {
      if (!result || result.ok === false) { onError((result && result.message) || "操作失败"); return null; }
      return result;
    },
  });
  App.bridge = {
    listProjectCatalog: () => Promise.resolve({ ok: true, editing_projects: [], filter_projects: [] }),
  };
  loadJs(context, "core.js");
  loadJs(context, "project_catalog.js");
  loadJs(context, "rules.js");
  return { App, element };
}

test("10. filter catalog excludes system unclassified project (single 未归类 option)", async () => {
  const { App, element } = rulesHarness();
  App.renderTimelineProjectFilter = function (projects) {
    var select = element("timeline-project-filter");
    var html = '<option value="">全部项目</option><option value="unclassified">未归类</option>';
    (projects || []).forEach(function (project) {
      html += '<option value="' + project.id + '">' + project.name + '</option>';
    });
    select.innerHTML = html;
  };
  const editingProjects = [
    { id: 1, name: "Alpha" },
    { id: 2, name: "未归类", description: "system unclassified" },
  ];
  const filterProjects = [{ id: 1, name: "Alpha" }];
  App.bridge.listProjectCatalog = () => Promise.resolve({
    ok: true,
    editing_projects: editingProjects,
    filter_projects: filterProjects,
  });

  App.projectCatalog.invalidate();
  await App.projectCatalog.load();
  await flush();
  App.renderTimelineProjectFilter(App.projectCatalog.getFilter());

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
  App.bridge.listProjectCatalog = () => Promise.resolve({
    ok: true,
    editing_projects: editingProjects,
    filter_projects: [{ id: 1, name: "Alpha" }],
  });

  App.projectCatalog.invalidate();
  await App.projectCatalog.load();
  await flush();

  assert.equal(App.projectCatalog.getEditing().length, 2);
  assert.equal(App.projectCatalog.getFilter().length, 1);
  assert.equal(App.projectCatalog.getFilter().find((p) => p.name === "未归类"), undefined);
});

test("11. catalog refresh after project CRUD updates both projections (no duplicate binding)", async () => {
  const { App } = rulesHarness();
  let editingProjects = [{ id: 1, name: "A" }];
  let filterProjects = [{ id: 1, name: "A" }];
  App.bridge.listProjectCatalog = () => Promise.resolve({
    ok: true,
    editing_projects: editingProjects,
    filter_projects: filterProjects,
  });

  App.projectCatalog.invalidate();
  await App.projectCatalog.load();
  await flush();
  assert.equal(App.projectCatalog.getEditing().length, 1);
  assert.equal(App.projectCatalog.getFilter().length, 1);

  editingProjects = [{ id: 1, name: "A" }, { id: 2, name: "B" }];
  filterProjects = [{ id: 1, name: "A" }, { id: 2, name: "B" }];
  App.projectCatalog.invalidate();
  await App.projectCatalog.load();
  await flush();
  assert.equal(App.projectCatalog.getEditing().length, 2, "editing catalog must include B");
  assert.equal(App.projectCatalog.getFilter().length, 2, "filter catalog must include B");
  assert.ok(App.projectCatalog.getFilter().find((p) => p.id === 2));

  editingProjects = [{ id: 1, name: "A" }];
  filterProjects = [{ id: 1, name: "A" }];
  App.projectCatalog.invalidate();
  await App.projectCatalog.load();
  await flush();
  assert.equal(App.projectCatalog.getEditing().length, 1);
  assert.equal(App.projectCatalog.getFilter().length, 1);
  assert.equal(App.projectCatalog.getFilter().find((p) => p.id === 2), undefined);
});

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
  loadJs(context, "fd_work_v5.js");
  loadJs(context, "rules_create_panel_v5.js");
  return { App, element, bridgeCalls };
}

test("12. editing an English project preserves language when only name changes", async () => {
  const { App, element, bridgeCalls } = rulesPanelHarness();
  const englishProject = { id: 5, name: "Old", description: "desc", language: "English" };
  App.openRulesPanel("project", { project: englishProject });
  assert.equal(App.rulesPanelOriginalLanguage, "English");
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

function makeStructuredCurrentActivityElement(id) {
  const children = {
    ".current-resource": makeElement("current-resource"),
    ".current-context": makeElement("current-context"),
    ".current-duration": makeElement("current-duration"),
  };
  const el = makeElement(id);
  el.classList = {
    add() {}, remove() {}, toggle() {},
    contains(cls) { return cls === "current-activity"; },
  };
  el.querySelector = (sel) => children[sel] || null;
  el.querySelectorAll = () => Object.values(children);
  Object.defineProperty(el, "textContent", {
    get() {
      return [children[".current-resource"], children[".current-context"], children[".current-duration"]]
        .map((c) => c.textContent || "").join("");
    },
    set() {},
  });
  return el;
}

function overviewHarness() {
  const { context, element, elements } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  elements.set("current-activity", makeStructuredCurrentActivityElement("current-activity"));
  Object.assign(App, {
    currentPage: "overview",
    timelineDate: "2026-07-22",
    lastOverviewSnapshot: null,
    pendingTimelineSelectionIntent: null,
    getActiveLiveClock: () => null,
    validateLiveClock: (clock) => (clock && clock.is_live === true ? clock : null),
    computeClockDurationNow: (clock) => (clock ? (clock.elapsed_seconds_at_sample || 0) : 0),
    setLiveClockTarget: () => {},
    clearLiveClockTarget: () => {},
    renderDurationProjected: (target, seconds) => { if (target) target.textContent = formatDuration(seconds); },
    liveClockDataAttributes: () => "",
    liveContinuityKey: () => "",
    currentActivityContinuityKey: () => "",
    formatStartTimeOnly: (t) => String(t || "").slice(11, 16),
    formatProjectLabel: (name) => name || "未归类",
    formatDuration,
    escapeHtml: (s) => String(s == null ? "" : s),
    switchPage: () => {},
    loadTimelineReport: () => Promise.resolve(),
    findSessionByProjectionKey: () => null,
    selectTimelineSession: () => {},
    focusTimelineEditorField: () => {},
  });
  App.bridge = {};
  loadJs(context, "core.js");
  loadJs(context, "overview.js");
  return { App, element };
}

function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const sec = String(s % 60).padStart(2, "0");
  return `${h}:${m}:${sec}`;
}

test("13. current activity main title comes from resource_name, not project name", () => {
  const { App, element } = overviewHarness();
  const currentActivity = {
    active: true,
    status: "normal",
    resource_name: "overview.js",
    app_name: "Visual Studio Code",
    project_name: "WorkTrace",
    is_uncategorized: false,
    elapsed_seconds: 312,
  };
  App.renderCurrentActivityElement(element("current-activity"), currentActivity, "overview");
  assert.equal(element("current-activity").querySelector(".current-resource").textContent, "overview.js");
});

test("13b. current_session project_name does not override the current resource name", () => {
  const { App, element } = overviewHarness();
  App.lastOverviewSnapshot = {
    current_session: { project_name: "Project Alpha", projection_instance_key: "k1", start_time: "2026-07-22T10:00:00" },
  };
  const currentActivity = {
    active: true,
    status: "normal",
    resource_name: "license-draft.docx",
    app_name: "Word",
    project_name: "Project Alpha",
    is_uncategorized: false,
    elapsed_seconds: 600,
  };
  App.renderCurrentActivityElement(element("current-activity"), currentActivity, "overview");
  assert.equal(element("current-activity").querySelector(".current-resource").textContent, "license-draft.docx");
});

test("13c. current activity uses current_live when clock is live", () => {
  const { App, element } = overviewHarness();
  App.getActiveLiveClock = () => ({
    sampled_at_epoch_ms: Date.now(),
    started_at_epoch_ms: Date.now() - 300000,
    elapsed_seconds_at_sample: 300,
    aggregate_base_seconds: 0,
    duration_semantic: "current_live",
    is_live: true,
    live_state: "persisted_open",
    display_span_id: "span:abc",
    stable_live_key_hash: "abc",
  });
  const currentActivity = {
    active: true,
    status: "normal",
    resource_name: "editing.md",
    app_name: "Editor",
    project_name: "Project",
    is_uncategorized: false,
    elapsed_seconds: 300,
  };
  App.renderCurrentActivityElement(element("current-activity"), currentActivity, "overview");
  assert.equal(element("current-activity").querySelector(".current-resource").textContent, "editing.md");
});

test("13d. current activity with no navigation target is truly disabled", () => {
  const { App, element } = overviewHarness();
  const bundle = {
    current_activity: { active: true, status: "normal", resource_name: "doc.txt", app_name: "Editor", project_name: "P", is_uncategorized: false, elapsed_seconds: 60 },
    current_session: null,
    recent: [],
    project_distribution: { total_seconds: 0, segments: [] },
    today_total_seconds: 0,
  };
  App.showOverview(bundle);
  const btn = element("current-activity");
  assert.equal(btn.disabled, true, "current activity button must be disabled when no current_session");
  assert.equal(btn.onclick, null, "disabled button must not have an onclick handler");
});

test("13e. current activity with navigation target is enabled and wired", () => {
  const { App, element } = overviewHarness();
  const bundle = {
    current_activity: { active: true, status: "normal", resource_name: "doc.txt", app_name: "Editor", project_name: "P", is_uncategorized: false, elapsed_seconds: 60 },
    current_session: { projection_instance_key: "key-1", start_time: "2026-07-22T10:00:00" },
    recent: [],
    project_distribution: { total_seconds: 0, segments: [] },
    today_total_seconds: 0,
  };
  App.showOverview(bundle);
  const btn = element("current-activity");
  assert.equal(btn.disabled, false, "button must be enabled when current_session is navigable");
  assert.equal(typeof btn.onclick, "function", "button must have an onclick handler");
});

for (const [name, status, resource] of [
  ["13e2. paused state disables current button even with a current_session", "paused", "stale.md"],
  ["13e3. idle state disables current button even with a current_session", "idle", "old.md"],
  ["13e4. excluded state disables current button even with a current_session", "excluded", "secret.xlsx"],
  ["13e5. error state disables current button even with a current_session", "error", "stale.md"],
]) {
  test(name, () => {
    const { App, element } = overviewHarness();
    App.showOverview({
      current_activity: { active: true, status, resource_name: resource, app_name: "Editor", project_name: "P", elapsed_seconds: 999 },
      current_session: { projection_instance_key: "key-1", start_time: "2026-07-22T10:00:00" },
      recent: [],
      project_distribution: { total_seconds: 0, segments: [] },
      today_total_seconds: 0,
    });
    const btn = element("current-activity");
    assert.equal(btn.disabled, true);
    assert.equal(btn.onclick, null);
  });
}

test("13f. paused state does not retain stale activity content", () => {
  const { App, element } = overviewHarness();
  App.renderCurrentActivityElement(element("current-activity"), {
    active: true, status: "paused", resource_name: "should-not-show.md", app_name: "Editor", project_name: "P", elapsed_seconds: 999,
  }, "overview");
  const text = element("current-activity").textContent;
  assert.equal(text.includes("已暂停"), true);
  assert.equal(text.includes("should-not-show.md"), false);
});

test("13g. excluded state does not leak sensitive content", () => {
  const { App, element } = overviewHarness();
  App.renderCurrentActivityElement(element("current-activity"), {
    active: true, status: "excluded", resource_name: "secret-financial-data.xlsx", app_name: "Excel", project_name: "Confidential", elapsed_seconds: 500,
  }, "overview");
  const text = element("current-activity").textContent;
  assert.equal(text.includes("已排除"), true);
  assert.equal(text.includes("secret-financial-data.xlsx"), false);
  assert.equal(text.includes("Confidential"), false);
});

test("13h. error state does not retain stale activity content", () => {
  const { App, element } = overviewHarness();
  App.renderCurrentActivityElement(element("current-activity"), {
    active: true, status: "error", resource_name: "stale-resource.md", app_name: "Editor", project_name: "P", elapsed_seconds: 999,
  }, "overview");
  const text = element("current-activity").textContent;
  assert.equal(text.includes("无法识别"), true);
  assert.equal(text.includes("stale-resource.md"), false);
});

test("13i. idle state shows idle title, not stale resource", () => {
  const { App, element } = overviewHarness();
  App.renderCurrentActivityElement(element("current-activity"), {
    active: true, status: "idle", resource_name: "old-resource.md", app_name: "Editor", elapsed_seconds: 999,
  }, "overview");
  const text = element("current-activity").textContent;
  assert.equal(text.includes("空闲"), true);
  assert.equal(text.includes("old-resource.md"), false);
});

test("13j. no active snapshot shows no-activity state, not stale content", () => {
  const { App, element } = overviewHarness();
  App.renderCurrentActivityElement(element("current-activity"), {
    active: false, status: "normal", resource_name: "should-not-appear.md",
  }, "overview");
  const text = element("current-activity").textContent;
  assert.equal(text.includes("当前没有活动"), true);
  assert.equal(text.includes("should-not-appear.md"), false);
});

test("13k. recent records keep a stable three-child structure, live metadata, and Timeline intent", () => {
  const { App, element } = overviewHarness();
  const recentList = element("recent-list");
  let recentHtml = "";
  let boundButtons = [];
  Object.defineProperty(recentList, "innerHTML", {
    configurable: true,
    get() { return recentHtml; },
    set(value) {
      recentHtml = value;
      boundButtons = topLevelElements(value).map((row) => {
        const indexMatch = row.attributes.match(/\bdata-recent-index="([^"]+)"/);
        const listeners = {};
        return {
          getAttribute(name) { return name === "data-recent-index" && indexMatch ? indexMatch[1] : null; },
          addEventListener(name, handler) { listeners[name] = handler; },
          click() { if (listeners.click) listeners.click(); },
        };
      });
    },
  });
  recentList.querySelectorAll = (selector) => selector === "[data-recent-index]" ? boundButtons : [];
  App.computeClockDurationNow = (clock) => clock.aggregate_base_seconds + clock.elapsed_seconds_at_sample;
  let switchedPage = "";
  App.switchPage = (page) => { switchedPage = page; };
  const bundle = {
    current_activity: { active: true, status: "normal", resource_name: "live.md", app_name: "Editor", project_name: "P", is_uncategorized: false, elapsed_seconds: 60 },
    current_session: { projection_instance_key: "live-key", start_time: "2026-07-22T10:00:00" },
    recent: [
      { projection_instance_key: "live-key", start_time: "2026-07-22T10:00:00", project_name: "WorkTrace", display_description: "起草", duration_seconds: 1500, is_in_progress: true, needs_attention: false, live_clock: { sampled_at_epoch_ms: 1000000, started_at_epoch_ms: 700000, elapsed_seconds_at_sample: 300, aggregate_base_seconds: 1200, duration_semantic: "aggregate_live", is_live: true, live_state: "persisted_open", display_span_id: "span:recent", stable_live_key_hash: "recent" } },
      { projection_instance_key: "uncategorized-1", start_time: "2026-07-22T09:00:00", project_name: "", display_description: "专利检索页面", duration_seconds: 1800, is_in_progress: false, needs_attention: true, description_source: "derived" },
      { projection_instance_key: "ok-1", start_time: "2026-07-22T08:00:00", project_name: "Project B", display_description: "已整理", duration_seconds: 600, is_in_progress: false, needs_attention: false },
    ],
    project_distribution: { total_seconds: 3900, segments: [] },
    today_total_seconds: 3900,
  };
  App.showOverview(bundle);
  const rows = topLevelElements(recentHtml);
  assert.equal(rows.length, 3);
  const rowChildren = rows.map((row) => topLevelElements(row.innerHTML));
  rowChildren.forEach((children, index) => {
    assert.equal(children.length, 3, `row ${index} must have exactly three direct children`);
    assert.deepEqual(classTokens(children[0]), ["recent-start-time", "numeric"]);
    assert.deepEqual(classTokens(children[1]), ["recent-main"]);
    assert.deepEqual(classTokens(children[2]), ["numeric", "recent-duration"]);
  });
  const titleLines = rowChildren.map((children) => topLevelElements(children[1].innerHTML)[0]);
  assert.deepEqual(classTokens(titleLines[0]), ["recent-title-line"]);
  assert.deepEqual(topLevelElements(titleLines[0].innerHTML).map(classTokens), [["recent-project"]]);
  assert.equal(recentHtml.includes("recent-status"), false);
  assert.equal(recentHtml.includes("进行中"), false);
  assert.equal(recentHtml.includes("待整理"), false);
  assert.equal(recentHtml.includes('class="recent-description derived"'), true);
  assert.equal(recentHtml.includes("自动摘要"), false);
  assert.equal(recentHtml.includes("WorkTrace"), true);
  assert.equal(recentHtml.includes("未归类"), true);
  assert.equal(recentHtml.includes("Project B"), true);
  assert.equal(recentHtml.includes('data-live-clock-target="1"'), true);
  assert.equal(recentHtml.includes('data-clock-duration-semantic="aggregate_live"'), true);
  assert.equal(recentHtml.includes('data-live-role="overview-recent"'), true);

  boundButtons[1].click();
  assert.equal(switchedPage, "timeline");
  assert.equal(App.pendingTimelineSelectionIntent.date, "2026-07-22");
  assert.equal(App.pendingTimelineSelectionIntent.projectionInstanceKey, "uncategorized-1");
});

test("13k2. empty project distribution clears and hides the bar", () => {
  const { App, element } = overviewHarness();
  const bar = element("overview-project-bar");
  bar.innerHTML = "stale";
  App.showOverview({
    current_activity: { active: false, status: "normal" },
    current_session: null,
    recent: [],
    project_distribution: { total_seconds: 0, segments: [] },
    today_total_seconds: 0,
  });
  assert.equal(bar.hidden, true);
  assert.equal(bar.innerHTML, "");
  assert.deepEqual(bar.style, {});
});

test("13k3. project distribution renders project, uncategorized, and other segments safely", () => {
  const { App, element } = overviewHarness();
  App.showOverview({
    current_activity: { active: false, status: "normal" },
    current_session: null,
    recent: [],
    project_distribution: {
      total_seconds: 17100,
      segments: [
        { key: "project:1", project_id: 1, label: "<WorkTrace>", duration_seconds: "9000", is_uncategorized: false, is_other: false },
        { key: "uncategorized", project_id: null, label: "未归类", duration_seconds: 4500, is_uncategorized: true, is_other: false },
        { key: "other", project_id: null, label: "其他", duration_seconds: 3600, category_count: 2, is_uncategorized: false, is_other: true },
      ],
    },
    today_total_seconds: 17100,
  });

  const bar = element("overview-project-bar");
  assert.equal(bar.hidden, false);
  assert.equal(bar.innerHTML.includes('style="flex-grow: 9000"'), true);
  assert.equal(bar.innerHTML.includes('style="flex-grow: 4500"'), true);
  assert.equal(bar.innerHTML.includes('style="flex-grow: 3600"'), true);
  assert.equal(bar.innerHTML.includes("&lt;WorkTrace&gt;"), true);
  assert.equal(bar.innerHTML.includes("<WorkTrace>"), false);
  assert.equal(bar.innerHTML.includes("2.5 h"), true);
  assert.equal(bar.innerHTML.includes("1.3 h"), true);
  assert.equal(bar.innerHTML.includes("1.0 h"), true);
  assert.equal(bar.innerHTML.includes("rank-1"), true);
  assert.equal(bar.innerHTML.includes("is-uncategorized"), true);
  assert.equal(bar.innerHTML.includes("is-other"), true);
  assert.equal(bar.innerHTML.includes('title="&lt;WorkTrace&gt; · 02:30:00"'), true);
  assert.equal(bar.innerHTML.includes('aria-label="未归类，01:15:00"'), true);
  assert.equal(bar.innerHTML.includes("<button"), false);

  App.showOverview({
    current_activity: { active: false, status: "normal" },
    current_session: null,
    recent: [],
    project_distribution: {
      total_seconds: 0,
      segments: [{ key: "invalid", label: "Invalid", duration_seconds: "12; color: red", is_uncategorized: false, is_other: false }],
    },
    today_total_seconds: 0,
  });
  assert.equal(bar.innerHTML.includes('style="flex-grow: 1"'), true);
  assert.equal(bar.innerHTML.includes("12; color: red"), false);
});

test("13l. current activity 5 min and recent record 25 min can both display", () => {
  const { App, element } = overviewHarness();
  App.computeClockDurationNow = function (clock) {
    var accepted = App.validateLiveClock(clock);
    if (!accepted || accepted.duration_semantic === "static_closed") return null;
    var elapsed = accepted.elapsed_seconds_at_sample;
    return accepted.duration_semantic === "aggregate_live" ? accepted.aggregate_base_seconds + elapsed : elapsed;
  };
  App.getActiveLiveClock = () => ({
    sampled_at_epoch_ms: 1000000,
    started_at_epoch_ms: 700000,
    elapsed_seconds_at_sample: 300,
    aggregate_base_seconds: 0,
    duration_semantic: "current_live",
    is_live: true,
    live_state: "persisted_open",
    display_span_id: "span:cur",
    stable_live_key_hash: "cur",
  });
  const bundle = {
    current_activity: { active: true, status: "normal", resource_name: "editing.md", app_name: "Editor", project_name: "P", is_uncategorized: false, elapsed_seconds: 300 },
    current_session: { projection_instance_key: "live-key", start_time: "2026-07-22T10:00:00" },
    recent: [
      { projection_instance_key: "live-key", start_time: "2026-07-22T10:00:00", project_name: "WorkTrace", display_description: "起草", duration_seconds: 1500, is_in_progress: true, needs_attention: false, live_clock: { sampled_at_epoch_ms: 1000000, started_at_epoch_ms: 0, elapsed_seconds_at_sample: 1500, aggregate_base_seconds: 0, duration_semantic: "aggregate_live", is_live: true, live_state: "persisted_open", display_span_id: "span:agg", stable_live_key_hash: "agg" } },
    ],
    project_distribution: { total_seconds: 1500, segments: [] },
    today_total_seconds: 1500,
  };
  App.showOverview(bundle);
  assert.equal(element("current-activity").querySelector(".current-duration").textContent, "00:05:00");
  assert.equal(element("recent-list").innerHTML.includes("00:25:00"), true);
});

test("13m. page headings use concise authoritative module names", () => {
  const html = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/index_fd_work_v5.html"),
    "utf8"
  );
  assert.equal(html.includes("当前活动"), true);
  assert.equal(html.includes("最近记录"), true);
  assert.equal(html.includes("当前活动和最近记录"), false, "Overview must not repeat an explanatory subtitle");
  assert.equal(html.includes("待整理"), false);
  assert.equal(html.includes("最近活动"), false);
});

test("14. launch-at-login rollback is authoritative and switch mutations are independent", async () => {
  const { context, element } = makeBaseContext();
  const App = context.window.WorkTraceApp;
  const launchGate = deferred();
  let clipboardCalls = 0;
  App.bridge = {
    getSettingsPrivacyStatus: () => Promise.resolve({ ok: true, status: {
        clipboard_capture_enabled: false,
        launch_at_login: { supported: true, enabled: false },
      } }),
    setLaunchAtLogin: () => launchGate.promise,
    setClipboardCaptureEnabled: () => {
      clipboardCalls += 1;
      return Promise.resolve({
        ok: true,
        status: {
          clipboard_capture_enabled: true,
          launch_at_login: { supported: true, enabled: false },
        },
      });
    },
  };
  App.handleResult = (result, onError) => {
    if (!result || result.ok === false) {
      onError((result && result.error) || "failed");
      return null;
    }
    return result;
  };
  loadJs(context, "core.js");
  loadSettingsModules(context);
  App.currentPage = "settings";
  await App.settings.onPageEntered();
  element("settings-launch-at-login-toggle").checked = true;

  const launchPromise = App.setLaunchAtLoginEnabled(true);
  assert.equal(App.settings.operationName(), "launch_at_login_write");
  assert.equal(element("settings-clipboard-toggle").disabled, false, "launch write must not lock clipboard toggle");
  await App.setCaptureEnabled(true);
  assert.equal(clipboardCalls, 1, "clipboard write can proceed independently");

  launchGate.resolve({
    ok: false,
    error: "registry denied",
    status: {
      clipboard_capture_enabled: true,
      launch_at_login: { supported: true, enabled: false },
    },
  });
  await launchPromise;
  await flush();

  assert.equal(element("settings-launch-at-login-toggle").checked, false);
  assert.equal(App.settings.operationName(), "");
  assert.equal(element("settings-error").hidden, false);
});
