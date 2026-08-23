const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { loadSettingsModules } = require("./settings_test_helpers");

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
  loadSettingsModules(context);
  return { App, element };
}

function fdWorkStatus(sessionState, overrides = {}) {
  return {
    supported: true,
    enabled: true,
    session_state: sessionState,
    operation: "none",
    ready: sessionState === "ready",
    login_required: sessionState === "login_required",
    error_code: null,
    navigation_generation: 7,
    ...overrides,
  };
}

test("FD Work settings status renders disabled by default", () => {
  const { App, element } = harness();
  App.renderSettingsStatus({ fd_work: { supported: true, enabled: false } });
  assert.equal(element("settings-fd-work-toggle").checked, false);
  assert.equal(element("settings-fd-work-toggle-status").textContent, "关闭");
});

test("first Settings load recomputes reconnect after loading settles", async () => {
  const { App, element } = harness();
  App.bridge = {
    getSettingsPrivacyStatus: () => Promise.resolve({
      ok: true,
      status: {
        fd_work: fdWorkStatus("login_required"),
        launch_at_login: { supported: true, enabled: false },
      },
    }),
  };

  await App.settings.onPageEntered();

  assert.equal(element("settings-fd-work-reconnect").hidden, false);
  assert.equal(element("settings-fd-work-reconnect").disabled, false);
  assert.equal(element("settings-fd-work-reconnect").textContent, "登录 FD Work");
});

test("idle Settings state offers an explicit connect action", () => {
  const { App, element } = harness();
  App.receiveFDWorkStatus(fdWorkStatus("idle"));
  App.renderSettingsStatus(
    { fd_work: App.fdWorkStatus },
    { loaded: true, fdWorkStatus: App.fdWorkStatus, operations: [] },
  );

  assert.equal(element("settings-fd-work-toggle-status").textContent, "尚未连接");
  assert.equal(element("settings-fd-work-reconnect").hidden, false);
  assert.equal(element("settings-fd-work-reconnect").disabled, false);
  assert.equal(element("settings-fd-work-reconnect").textContent, "连接 FD Work");
});

test("probing Settings state does not expose a duplicate login action", () => {
  const { App, element } = harness();
  App.receiveFDWorkStatus(fdWorkStatus("probing"));
  App.renderSettingsStatus(
    { fd_work: App.fdWorkStatus },
    { loaded: true, fdWorkStatus: App.fdWorkStatus, operations: [] },
  );

  assert.equal(element("settings-fd-work-toggle-status").textContent, "正在检查登录状态");
  assert.equal(element("settings-fd-work-reconnect").hidden, true);
});

test("renderer unavailable Settings state does not offer a futile reconnect", () => {
  const { App, element } = harness();
  App.receiveFDWorkStatus(fdWorkStatus("error", { error_code: "renderer_unavailable" }));
  App.renderSettingsStatus(
    { fd_work: App.fdWorkStatus },
    { loaded: true, fdWorkStatus: App.fdWorkStatus, operations: [] },
  );

  assert.equal(element("settings-fd-work-toggle-status").textContent, "WebView2 不可用");
  assert.equal(element("settings-fd-work-reconnect").hidden, true);
});

test("recoverable Settings error offers reconnect", () => {
  const { App, element } = harness();
  App.receiveFDWorkStatus(fdWorkStatus("error", { error_code: "session_start_timeout" }));
  App.renderSettingsStatus(
    { fd_work: App.fdWorkStatus },
    { loaded: true, fdWorkStatus: App.fdWorkStatus, operations: [] },
  );

  assert.equal(element("settings-fd-work-toggle-status").textContent, "连接超时");
  assert.equal(element("settings-fd-work-reconnect").hidden, false);
  assert.equal(element("settings-fd-work-reconnect").textContent, "重新连接");
});

test("live ready status replaces login-required Settings presentation", () => {
  const { App, element } = harness();
  App.receiveFDWorkStatus(fdWorkStatus("login_required"));
  App.settings.onFDWorkStatusChanged(App.fdWorkStatus);
  assert.equal(element("settings-fd-work-reconnect").hidden, false);

  App.receiveFDWorkStatus(fdWorkStatus("ready", { navigation_generation: 8 }));
  App.settings.onFDWorkStatusChanged(App.fdWorkStatus);

  assert.equal(element("settings-fd-work-toggle-status").textContent, "已连接");
  assert.equal(element("settings-fd-work-reconnect").hidden, true);
});

test("FD Work reconnect error clears on later authoritative recovery", async () => {
  const { App, element } = harness();
  App.bridge = {
    showFDWorkLogin: () => Promise.resolve({ ok: false, message: "临时连接失败" }),
  };

  assert.equal(await App.reconnectFDWork(), false);
  assert.equal(element("settings-error").textContent, "临时连接失败");

  App.receiveFDWorkStatus(fdWorkStatus("ready", { navigation_generation: 8 }));
  App.settings.onFDWorkStatusChanged(App.fdWorkStatus);

  assert.equal(element("settings-error").hidden, true);
  assert.equal(element("settings-error").textContent, "");
});

test("FD Work recovery never clears a newer unrelated Settings error", async () => {
  const { App, element } = harness();
  App.bridge = {
    showFDWorkLogin: () => Promise.resolve({ ok: false, message: "临时连接失败" }),
  };

  assert.equal(await App.reconnectFDWork(), false);
  App.showSettingsError("备份失败");
  App.receiveFDWorkStatus(fdWorkStatus("ready", { navigation_generation: 8 }));
  App.settings.onFDWorkStatusChanged(App.fdWorkStatus);

  assert.equal(element("settings-error").hidden, false);
  assert.equal(element("settings-error").textContent, "备份失败");
});

test("FD Work settings write failure restores authoritative backend state", async () => {
  const { App, element } = harness();
  let acceptedStatuses = 0;
  App.receiveFDWorkStatus = () => { acceptedStatuses += 1; };
  App.renderSettingsStatus({ fd_work: { supported: true, enabled: false } });
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
  assert.equal(acceptedStatuses, 1, "authoritative failure status is accepted once");
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