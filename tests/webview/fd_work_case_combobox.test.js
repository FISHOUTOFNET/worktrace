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
  const elements = new Map();
  function element(id) {
    if (elements.has(id)) return elements.get(id);
    const attributes = new Map();
    const listeners = new Map();
    const node = {
      id, hidden: false, disabled: false, value: "", textContent: "", children: [],
      className: "", tabIndex: 0, parentElement: null,
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      setAttribute(name, value) { attributes.set(name, String(value)); },
      getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
      removeAttribute(name) { attributes.delete(name); },
      addEventListener(name, handler) { listeners.set(name, handler); },
      appendChild(child) { child.parentElement = node; node.children.push(child); return child; },
      contains(target) { return target === node || node.children.includes(target); },
      closest(selector) {
        return selector === "[role='option']" && attributes.get("role") === "option" ? node : null;
      },
      fire(name, extra = {}) {
        const event = Object.assign({ target: node, key: "", preventDefault() {} }, extra);
        if (listeners.has(name)) listeners.get(name).call(node, event);
      },
    };
    Object.defineProperty(node, "innerHTML", {
      get() { return ""; },
      set() { node.children = []; },
    });
    elements.set(id, node);
    return node;
  }
  const documentListeners = new Map();
  const context = {
    Promise, setTimeout, clearTimeout,
    window: { WorkTraceApp: {} },
    document: {
      activeElement: null,
      getElementById: element,
      createElement() { return element(`created-${elements.size}`); },
      addEventListener(name, handler) { documentListeners.set(name, handler); },
    },
  };
  vm.createContext(context);
  for (const file of ["fd_work.js", "rules_create_panel.js"]) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
      context,
      { filename: file }
    );
  }
  const App = context.window.WorkTraceApp;
  App.safeText = (value, fallback) => String(value || fallback || "");
  App.rerenderProjectRulesList = () => {};
  App.bridge = {
    searchFDWorkCases: () => Promise.resolve({ ok: true, options: [] }),
    showFDWorkLogin: () => Promise.resolve({ ok: true }),
  };
  App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "ready", operation: "none",
    ready: true, login_required: false, error_code: null,
  });
  App.initRulesPanelEvents();
  App.rulesPanelSessionToken = 1;
  return { App, element, documentListeners };
}

test("shared status rejects malformed updates and synchronizes settings authority", () => {
  const { App } = harness();
  App.lastSettingsStatus = { fd_work: null };
  assert.equal(App.receiveFDWorkStatus("ready"), false);
  const status = {
    supported: true, enabled: true, session_state: "starting", operation: "none",
    ready: false, login_required: false, error_code: null,
  };
  assert.equal(App.receiveFDWorkStatus(status), true);
  assert.equal(App.fdWorkStatus.session_state, "starting");
  assert.equal(App.lastSettingsStatus.fd_work, App.fdWorkStatus);
});

test("login confirmation phase has distinct user-facing status", () => {
  const { App } = harness();
  const status = {
    supported: true, enabled: true, session_state: "login_required", operation: "none",
    ready: false, login_required: true, error_code: "login_required",
    page_phase: "login_confirmation", navigation_generation: 4,
  };

  assert.equal(App.receiveFDWorkStatus(status), true);
  assert.equal(App.fdWorkStatusText(App.fdWorkStatus), "请确认登录");
  assert.equal(App.fdWorkStatus.page_phase, "login_confirmation");
});

test("debounce uses latest response and editing invalidates the in-memory proof", async () => {
  const { App, element } = harness();
  const first = deferred();
  const second = deferred();
  const calls = [];
  App.bridge.searchFDWorkCases = (query, requestId) => {
    calls.push([query, requestId]);
    return calls.length === 1 ? first.promise : second.promise;
  };
  const input = element("rules-panel-project-name");
  input.value = "CA";
  input.fire("input");
  await new Promise((resolve) => setTimeout(resolve, 330));
  input.value = "CASE";
  input.fire("input");
  await new Promise((resolve) => setTimeout(resolve, 330));
  second.resolve({ ok: true, options: [{ label: "CASE NEW", selection_token: "opaque-new" }] });
  await Promise.resolve(); await Promise.resolve();
  first.resolve({ ok: true, options: [{ label: "CASE OLD", selection_token: "opaque-old" }] });
  await Promise.resolve(); await Promise.resolve();

  assert.equal(calls.length, 2);
  assert.equal(App.rulesFDWorkSearchOptions[0].label, "CASE NEW");
  const listbox = element("rules-panel-fd-work-options");
  listbox.fire("click", { target: listbox.children[0] });
  assert.equal(input.value, "CASE NEW");
  assert.equal(App.rulesFDWorkSelectionToken, "opaque-new");

  input.value = "CASE NEW edited";
  input.fire("input");
  assert.equal(App.rulesFDWorkSelectionToken, null);
});

test("keyboard selection works and login readiness retries the current query once", async () => {
  const { App, element } = harness();
  let searches = 0;
  App.bridge.searchFDWorkCases = () => {
    searches += 1;
    return Promise.resolve({
      ok: true,
      options: [
        { label: "CASE A", selection_token: "token-a" },
        { label: "CASE B", selection_token: "token-b" },
      ],
    });
  };
  const input = element("rules-panel-project-name");
  input.value = "CA";
  input.fire("input");
  await new Promise((resolve) => setTimeout(resolve, 330));
  await Promise.resolve(); await Promise.resolve();
  input.fire("keydown", { key: "ArrowDown" });
  input.fire("keydown", { key: "Enter" });
  assert.equal(input.value, "CASE B");
  assert.equal(App.rulesFDWorkSelectionToken, "token-b");

  input.value = "CA";
  input.fire("input");
  App.rulesFDWorkLoginRetryPending = true;
  App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "ready", operation: "none",
    ready: true, login_required: false, error_code: null,
  });
  await Promise.resolve(); await Promise.resolve();
  const afterReady = searches;
  App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "ready", operation: "none",
    ready: true, login_required: false, error_code: null,
  });
  await Promise.resolve();
  assert.equal(searches, afterReady);
});

test("focus and click on empty input request native recent cases", async () => {
  const { App, element } = harness();
  const calls = [];
  App.bridge.searchFDWorkCases = (query) => {
    calls.push(query);
    return Promise.resolve({ ok: true, options: [] });
  };
  const input = element("rules-panel-project-name");
  input.value = "";

  input.fire("focus");
  await Promise.resolve(); await Promise.resolve();
  input.fire("click");
  await Promise.resolve(); await Promise.resolve();

  assert.deepEqual(calls, ["", ""]);
});

test("probing input foregrounds FD Work and retries the current query once when ready", async () => {
  const { App, element } = harness();
  let loginCalls = 0;
  let searchCalls = 0;
  App.bridge.showFDWorkLogin = () => { loginCalls += 1; return Promise.resolve({ ok: true }); };
  App.bridge.searchFDWorkCases = () => {
    searchCalls += 1;
    return Promise.resolve({ ok: true, options: [] });
  };
  App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "probing", operation: "none",
    ready: false, login_required: false, error_code: null,
    page_phase: "unknown", navigation_generation: 4,
  });
  const input = element("rules-panel-project-name");
  input.value = "A";
  input.fire("input");
  await new Promise((resolve) => setTimeout(resolve, 330));
  await Promise.resolve(); await Promise.resolve();

  assert.equal(loginCalls, 1);
  assert.equal(searchCalls, 0);
  App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "ready", operation: "none",
    ready: true, login_required: false, error_code: null,
    page_phase: "work_shell", navigation_generation: 4,
  });
  await Promise.resolve(); await Promise.resolve();
  assert.equal(searchCalls, 1);
  App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "ready", operation: "none",
    ready: true, login_required: false, error_code: null,
    page_phase: "work_shell", navigation_generation: 4,
  });
  await Promise.resolve();
  assert.equal(searchCalls, 1);
});

test("one character searches and an ordinary project remains saveable", async () => {
  const { App, element } = harness();
  const calls = [];
  App.bridge.searchFDWorkCases = (query) => {
    calls.push(query);
    return Promise.resolve({ ok: true, options: [] });
  };
  const input = element("rules-panel-project-name");
  const save = element("rules-panel-save-project");
  input.value = "A";
  input.fire("input");
  await new Promise((resolve) => setTimeout(resolve, 330));
  await Promise.resolve(); await Promise.resolve();

  assert.deepEqual(calls, ["A"]);
  assert.equal(save.disabled, false);
  assert.doesNotMatch(element("rules-panel-fd-work-status").textContent, /至少输入 2 个字符/);
});

test("specific interactive lookup errors keep actionable messages and retry at most once", async () => {
  const { App, element } = harness();
  let searches = 0;
  App.bridge.searchFDWorkCases = () => {
    searches += 1;
    return Promise.resolve({
      ok: false,
      error: "case_popup_not_created",
      message: "FD Work 案件下拉框未能打开",
    });
  };
  const input = element("rules-panel-project-name");
  input.value = "A";
  input.fire("input");
  await new Promise((resolve) => setTimeout(resolve, 330));
  await Promise.resolve(); await Promise.resolve();

  assert.equal(searches, 1);
  assert.equal(element("rules-panel-fd-work-status").textContent, "FD Work 案件下拉框未能打开");
  App.receiveFDWorkStatus({
    supported: true, enabled: true, session_state: "ready", operation: "none",
    ready: true, login_required: false, error_code: null,
    page_phase: "work_shell", navigation_generation: 5,
  });
  await Promise.resolve(); await Promise.resolve();
  assert.equal(searches, 1);
});

test("existing binding survives description-only edit and manual rename warns clearing", () => {
  const { App, element } = harness();
  App.lastProjectRulesData = { projects: [{
    id: 7, name: "CASE A", description: "old", language: "中文", fd_work_bound: true,
  }] };
  App.openRulesPanel("project", { project: App.lastProjectRulesData.projects[0] });
  assert.match(element("rules-panel-fd-work-status").textContent, /已关联 FD Work/);

  element("rules-panel-project-description").value = "new";
  assert.match(element("rules-panel-fd-work-status").textContent, /已关联 FD Work/);

  const input = element("rules-panel-project-name");
  input.value = "Manual";
  input.fire("input");
  assert.match(element("rules-panel-fd-work-status").textContent, /解除关联/);
});
