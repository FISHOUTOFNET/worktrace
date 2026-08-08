const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function flush() {
  return new Promise((resolve) => setImmediate(resolve));
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function createClassList() {
  const values = new Set();
  return {
    add(...names) { names.forEach((name) => values.add(name)); },
    remove(...names) { names.forEach((name) => values.delete(name)); },
    contains(name) { return values.has(name); },
    toggle(name, force) {
      const enabled = force === undefined ? !values.has(name) : !!force;
      if (enabled) values.add(name);
      else values.delete(name);
      return enabled;
    },
  };
}

function createHarness() {
  const elements = new Map();
  const documentListeners = {};
  let activeElement = null;

  function element(id) {
    if (!elements.has(id)) {
      const attrs = new Map();
      const listeners = {};
      const node = {
        id,
        hidden: false,
        disabled: false,
        checked: false,
        readOnly: false,
        value: "",
        textContent: "",
        innerHTML: "",
        className: "",
        classList: createClassList(),
        children: [],
        parentNode: null,
        setAttribute(name, value) { attrs.set(name, String(value)); },
        getAttribute(name) { return attrs.has(name) ? attrs.get(name) : null; },
        removeAttribute(name) { attrs.delete(name); },
        contains() { return true; },
        addEventListener(name, handler) {
          if (!listeners[name]) listeners[name] = [];
          listeners[name].push(handler);
        },
        dispatch(name, event = {}) {
          (listeners[name] || []).forEach((handler) => handler({
            target: node,
            currentTarget: node,
            preventDefault() {},
            ...event,
          }));
        },
        focus() { activeElement = node; },
        appendChild(child) { child.parentNode = node; node.children.push(child); },
        removeChild(child) {
          node.children = node.children.filter((candidate) => candidate !== child);
          child.parentNode = null;
        },
        querySelector(selector) {
          if (selector === "button:not([hidden]):not([disabled])") {
            return node.children.find((child) => !child.hidden && !child.disabled) || null;
          }
          if (selector === ".settings-backup-manifest-filename") {
            return element("settings-backup-manifest-filename");
          }
          if (selector === ".settings-backup-manifest-fields") {
            return element("settings-backup-manifest-fields");
          }
          return null;
        },
        querySelectorAll() { return []; },
      };
      Object.defineProperty(node, "firstChild", {
        get() { return node.children[0] || null; },
      });
      elements.set(id, node);
    }
    return elements.get(id);
  }

  const navItems = ["overview", "timeline", "statistics", "rules", "settings"].map((page) => {
    const node = element(`nav-${page}`);
    node.setAttribute("data-page", page);
    node.setAttribute("data-title", page);
    return node;
  });
  const pages = ["overview", "timeline", "statistics", "rules", "settings"].map((page) =>
    element(`page-${page}`)
  );

  const document = {
    readyState: "loading",
    body: element("body"),
    documentElement: element("html"),
    get activeElement() { return activeElement; },
    getElementById: element,
    contains() { return true; },
    createElement(tag) { return element(`created-${tag}-${elements.size}`); },
    querySelectorAll(selector) {
      if (selector === ".nav-item") return navItems;
      if (selector === ".page") return pages;
      if (selector === ".drawer-layer:not([hidden])") {
        const drawer = element("rules-create-panel");
        return drawer.hidden ? [] : [drawer];
      }
      return [];
    },
    querySelector(selector) {
      const navMatch = selector.match(/^\.nav-item\[data-page="([^"]+)"\]$/);
      if (navMatch) return navItems.find((item) => item.getAttribute("data-page") === navMatch[1]) || null;
      if (selector === ".drawer-layer:not([hidden])") {
        const drawer = element("rules-create-panel");
        return drawer.hidden ? null : drawer;
      }
      if (selector === "#settings-section-advanced details") return element("settings-diagnostics");
      return null;
    },
    addEventListener(name, handler) { documentListeners[name] = handler; },
  };

  const window = {
    WorkTraceApp: {},
    document,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    matchMedia: () => ({ matches: false }),
    addEventListener() {},
    removeEventListener() {},
  };
  const context = {
    window,
    document,
    Promise,
    Error,
    String,
    Number,
    Array,
    Object,
    Date,
    Math,
    JSON,
    RegExp,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    setImmediate,
  };
  vm.createContext(context);

  function load(file) {
    vm.runInContext(
      fs.readFileSync(path.join(__dirname, "../../worktrace/webview_ui/js", file), "utf8"),
      context,
      { filename: file }
    );
  }

  return {
    App: window.WorkTraceApp,
    document,
    documentListeners,
    element,
    load,
  };
}

test("page switch resets only the page actually being left", () => {
  const h = createHarness();
  const calls = [];
  Object.assign(h.App, {
    currentPage: "rules",
    rulesLoaded: true,
    settingsLoaded: true,
    timelineLoaded: true,
    statisticsLoaded: true,
    timelineDate: "2026-07-29",
    resetRulesTransientUi: () => calls.push("rules"),
    resetTimelineTransientUi: () => calls.push("timeline"),
    resetStatisticsTransientUi: () => calls.push("statistics"),
    resetSettingsTransientUi: () => calls.push("settings"),
  });
  h.load("init_fd_work_v5.js");
  h.element("app-toast").textContent = "keep toast";
  h.element("global-alert").textContent = "keep alert";
  h.App.switchPage("rules");
  assert.deepEqual(calls, []);
  h.App.switchPage("settings");
  assert.deepEqual(calls, ["rules"]);
  assert.equal(h.element("app-toast").textContent, "keep toast");
  assert.equal(h.element("global-alert").textContent, "keep alert");
});

test("client generation reset delegates transient ownership to fixed modules", () => {
  const h = createHarness();
  const calls = [];
  for (const name of ["overview", "timeline", "statistics", "rules", "settings", "fdWork"]) {
    h.App[name] = { resetGeneration: () => calls.push(name) };
  }
  h.App.requestCoordinator = { bumpDataEpoch: () => calls.push("runtime") };
  h.load("init_fd_work_v5.js");

  h.App.resetClientGeneration("replacement");

  assert.deepEqual(calls, [
    "runtime", "overview", "timeline", "statistics", "rules", "settings", "fdWork",
  ]);
  assert.equal(h.App.lastClientGenerationResetReason, "replacement");
});

test("FD Work generation reset discards the previous editor binding state", () => {
  const h = createHarness();
  h.App.safeText = (value, fallback) => value === undefined || value === null
    ? fallback : String(value);
  h.load("fd_work_v5.js");
  h.App.receiveFDWorkStatus({
    supported: true,
    enabled: true,
    session_state: "ready",
    operation: "none",
    ready: true,
    login_required: false,
    error_code: null,
  });
  h.App.projectIdentity.prepareEditor({ name: "CASE A", fd_work_bound: true });
  h.App.projectIdentity.updateControls(false);
  assert.equal(h.element("rules-panel-fd-work-clear").hidden, false);

  h.App.fdWork.resetGeneration();
  h.App.projectIdentity.updateControls(false);

  assert.equal(h.element("rules-panel-fd-work-clear").hidden, true);
  assert.equal(h.element("rules-panel-fd-work-selected-label").value, "");
});

test("rules panel presentation, rule tabs, folder picker, and Escape share one lifecycle", async () => {
  const h = createHarness();
  const App = h.App;
  h.element("rules-create-panel").hidden = true;
  h.element("rules-panel-folder-recursive").checked = true;
  h.element("rules-panel-backfill").checked = true;
  App.safeText = (value, fallback) => value === undefined || value === null ? fallback : String(value);
  App.lastProjectRulesData = {
    projects: [{ id: 7, name: "Alpha", description: "", enabled: true }],
  };
  App.loadProjectRules = () => Promise.resolve();
  App.showToast = () => {};
  App.bridge = {
    chooseProjectRuleFolder: () => Promise.resolve({
      ok: true, cancelled: false, folder_path: "D:\\Alpha",
    }),
    createProjectForRules: () => Promise.resolve({ ok: true, project: { id: 9, name: "New" } }),
    updateProjectForRules: () => Promise.resolve({ ok: true, project: { id: 7, name: "Alpha" } }),
    createProjectFolderRule: () => Promise.resolve({ ok: true, rule: { id: 1 } }),
    createProjectKeywordRule: () => Promise.resolve({ ok: true, rule: { id: 2 } }),
  };
  h.load("fd_work_v5.js");
  h.load("ui_components.js");
  h.load("rules_create_panel_v5.js");
  App.initRulesPanelEvents();

  App.openRulesPanel("project", {});
  assert.equal(h.element("rules-create-panel-title").textContent, "新建项目");
  assert.equal(h.element("rules-panel-save-project").textContent, "新建项目");

  App.openRulesPanel("project", { project: { id: 7, name: "Alpha", description: "" } });
  assert.equal(h.element("rules-create-panel-title").textContent, "编辑项目");
  assert.equal(h.element("rules-panel-save-project").textContent, "保存修改");

  h.element("rules-panel-keyword-type").dispatch("click");
  assert.equal(h.element("rules-panel-keyword-type").getAttribute("aria-selected"), "true");
  assert.equal(h.element("rules-panel-keyword-type").tabIndex, 0);
  assert.equal(h.element("rules-panel-folder-type").getAttribute("aria-selected"), "false");
  assert.equal(h.element("rules-panel-folder-type").tabIndex, -1);
  assert.equal(h.element("rules-panel-keyword-type").classList.contains("is-active"), true);
  assert.equal(h.element("rules-panel-folder-type").classList.contains("is-active"), false);

  App.openRulesPanel("rule", { projectId: 7 });
  h.element("rules-panel-choose-folder").dispatch("click");
  await flush();
  assert.equal(h.element("rules-panel-folder-path").value, "D:\\Alpha");

  h.element("rules-panel-project-name").value = "discard me";
  h.element("rules-panel-keyword").value = "discard me";
  h.documentListeners.keydown({ key: "Escape", preventDefault() {} });
  assert.equal(h.element("rules-create-panel").hidden, true);
  assert.equal(h.element("rules-panel-project-name").value, "");
  assert.equal(h.element("rules-panel-folder-path").value, "");
  assert.equal(h.element("rules-panel-keyword").value, "");
});

test("stale project completion refreshes data but cannot overwrite a newer rules drawer", async () => {
  const h = createHarness();
  const App = h.App;
  const pending = deferred();
  let refreshes = 0;
  h.element("rules-create-panel").hidden = true;
  h.element("rules-panel-backfill").checked = true;
  App.safeText = (value, fallback) => value === undefined || value === null ? fallback : String(value);
  App.lastProjectRulesData = {
    projects: [{ id: 7, name: "Alpha", enabled: true }, { id: 8, name: "Beta", enabled: true }],
  };
  App.loadProjectRules = () => { refreshes += 1; return Promise.resolve(); };
  App.bridge = {
    createProjectForRules: () => pending.promise,
    updateProjectForRules: () => pending.promise,
  };
  h.load("fd_work_v5.js");
  h.load("ui_components.js");
  h.load("rules_create_panel_v5.js");

  App.openRulesPanel("project", {});
  h.element("rules-panel-project-name").value = "Old request";
  App.savePanelProject();
  App.closeRulesPanel();
  App.openRulesPanel("rule", { projectId: 8 });
  pending.resolve({ ok: true, project: { id: 9, name: "Old request" } });
  await flush();
  await flush();

  assert.equal(refreshes, 1);
  assert.equal(App.rulesPanelMode, "rule");
  assert.equal(h.element("rules-panel-target-project").value, "8");
  assert.notEqual(h.element("rules-panel-project-context").textContent.includes("Old request"), true);
});

test("project create and edit keep distinct busy and success outcomes", async () => {
  const edit = createHarness();
  const editPending = deferred();
  const editToasts = [];
  edit.element("rules-create-panel").hidden = true;
  edit.App.safeText = (value, fallback) => value === undefined || value === null ? fallback : String(value);
  edit.App.lastProjectRulesData = {
    projects: [{ id: 7, name: "Alpha", description: "", language: "中文", enabled: true }],
  };
  edit.App.loadProjectRules = () => Promise.resolve();
  edit.App.bridge = { updateProjectForRules: () => editPending.promise };
  edit.load("fd_work_v5.js");
  edit.load("ui_components.js");
  edit.load("rules_create_panel_v5.js");
  edit.App.showToast = (message) => editToasts.push(message);
  edit.App.openRulesPanel("project", {
    project: { id: 7, name: "Alpha", description: "", language: "中文" },
  });
  edit.element("rules-panel-project-name").value = "Alpha saved";
  edit.App.savePanelProject();
  assert.equal(edit.element("rules-panel-save-project").textContent, "正在保存…");
  editPending.resolve({ ok: true, project: { id: 7, name: "Alpha saved" } });
  await flush();
  await flush();
  assert.equal(edit.element("rules-create-panel").hidden, true);
  assert.deepEqual(editToasts, ["项目已保存"]);

  const create = createHarness();
  const createPending = deferred();
  create.element("rules-create-panel").hidden = true;
  create.App.safeText = (value, fallback) => value === undefined || value === null ? fallback : String(value);
  create.App.lastProjectRulesData = { projects: [] };
  create.App.loadProjectRules = () => {
    create.App.lastProjectRulesData = {
      projects: [{ id: 9, name: "New project", enabled: true }],
    };
    return Promise.resolve();
  };
  create.App.bridge = { createProjectForRules: () => createPending.promise };
  create.load("fd_work_v5.js");
  create.load("ui_components.js");
  create.load("rules_create_panel_v5.js");
  create.App.openRulesPanel("project", {});
  create.element("rules-panel-project-name").value = "New project";
  create.App.savePanelProject();
  assert.equal(create.element("rules-panel-save-project").textContent, "正在新建…");
  createPending.resolve({ ok: true, project: { id: 9, name: "New project" } });
  await flush();
  await flush();
  assert.equal(create.element("rules-create-panel").hidden, false);
  assert.equal(create.App.rulesPanelMode, "rule");
  assert.equal(create.element("rules-panel-target-project").value, "9");
  assert.equal(
    create.element("rules-panel-project-context").textContent,
    "项目已新增：“New project”。请继续添加自动归类规则。"
  );
  assert.equal(create.element("rules-panel-project-context").classList.contains("is-success"), true);
});

test("folder picker cancellation preserves the path and failure uses the panel error", async () => {
  const h = createHarness();
  h.element("rules-create-panel").hidden = true;
  h.App.safeText = (value, fallback) => value === undefined || value === null ? fallback : String(value);
  h.App.lastProjectRulesData = { projects: [{ id: 7, name: "Alpha", enabled: true }] };
  const results = [
    { ok: true, cancelled: true, folder_path: "" },
    { ok: false, error: "internal detail must not render" },
  ];
  h.App.bridge = { chooseProjectRuleFolder: () => Promise.resolve(results.shift()) };
  h.load("fd_work_v5.js");
  h.load("ui_components.js");
  h.load("rules_create_panel_v5.js");
  h.App.openRulesPanel("rule", { projectId: 7 });
  h.element("rules-panel-folder-path").value = "D:\\Keep";

  h.App.chooseProjectRuleFolder();
  await flush();
  assert.equal(h.element("rules-panel-folder-path").value, "D:\\Keep");
  assert.equal(h.element("rules-panel-status").hidden, true);

  h.App.chooseProjectRuleFolder();
  await flush();
  assert.equal(h.element("rules-panel-status").textContent, "选择文件夹失败");
  assert.equal(h.element("rules-panel-status").className.includes("is-error"), true);
});

test("page resetters clear only transient page UI and preserve authoritative state", () => {
  const timeline = createHarness();
  Object.assign(timeline.App, {
    selectedProjectionInstanceKey: "selection",
    timelineAutosaveTimer: { live: true },
    timelineAutosaveQueued: true,
    submittedDraft: { note: "draft" },
    editSaving: false,
  });
  timeline.element("timeline-session-actions").hidden = false;
  timeline.element("timeline-advanced-toggle").setAttribute("aria-expanded", "true");
  timeline.element("timeline-details-pane").classList.add("drawer-open");
  timeline.element("timeline-drawer-backdrop").hidden = false;
  timeline.element("edit-status").textContent = "saved";
  timeline.load("timeline.js");
  timeline.App.resetTimelineTransientUi();
  assert.equal(timeline.element("timeline-session-actions").hidden, true);
  assert.equal(timeline.element("timeline-details-pane").classList.contains("drawer-open"), false);
  assert.equal(timeline.App.selectedProjectionInstanceKey, "selection");
  assert.deepEqual(timeline.App.timelineAutosaveTimer, { live: true });
  assert.equal(timeline.App.timelineAutosaveQueued, true);
  assert.deepEqual(timeline.App.submittedDraft, { note: "draft" });
  timeline.App.editSaving = true;
  timeline.element("edit-status").textContent = "正在保存…";
  timeline.App.resetTimelineTransientUi();
  assert.equal(timeline.element("edit-status").textContent, "正在保存…");

  const settings = createHarness();
  Object.assign(settings.App, {
    settingsLoaded: true,
    lastSettingsStatus: { recovery_blocked: true },
    settingsBackupExportInProgress: true,
    recoveryInProgress: false,
    firstRunNoticeViewingFromSettings: true,
    firstRunNoticeRequired: false,
  });
  settings.element("settings-backup-passphrase").value = "secret";
  settings.element("settings-clear-confirm").value = "clear";
  settings.element("settings-backup-status").textContent = "temporary";
  settings.element("settings-diagnostics").open = true;
  settings.element("first-run-notice-overlay").hidden = false;
  settings.load("settings.js");
  settings.App.resetSettingsTransientUi();
  assert.equal(settings.element("settings-backup-passphrase").value, "");
  assert.equal(settings.element("settings-clear-confirm").value, "");
  assert.equal(settings.element("settings-backup-status").textContent, "");
  assert.equal(settings.element("settings-diagnostics").open, false);
  assert.equal(settings.element("first-run-notice-overlay").hidden, true);
  assert.equal(settings.App.settingsLoaded, true);
  assert.deepEqual(settings.App.lastSettingsStatus, { recovery_blocked: true });
  assert.equal(settings.App.settingsBackupExportInProgress, true);

  const forcedPrivacy = createHarness();
  Object.assign(forcedPrivacy.App, {
    firstRunNoticeViewingFromSettings: false,
    firstRunNoticeRequired: true,
    privacyGateState: "acceptance_required",
    recoveryInProgress: true,
  });
  forcedPrivacy.element("first-run-notice-overlay").hidden = false;
  forcedPrivacy.element("settings-recovery-status").textContent = "正在恢复…";
  forcedPrivacy.load("settings.js");
  forcedPrivacy.App.resetSettingsTransientUi();
  assert.equal(forcedPrivacy.element("first-run-notice-overlay").hidden, false);
  assert.equal(forcedPrivacy.App.firstRunNoticeRequired, true);
  assert.equal(forcedPrivacy.App.privacyGateState, "acceptance_required");
  assert.equal(forcedPrivacy.element("settings-recovery-status").textContent, "正在恢复…");

  const statistics = createHarness();
  let timerFired = false;
  statistics.App.statisticsAcceptedPayload = { summary: { total: 1 } };
  statistics.App.statisticsSelection = {
    allTime: false, dateFrom: "2026-07-01", dateTo: "2026-07-29",
  };
  statistics.App.statisticsDraftSelection = {
    allTime: false, dateFrom: "2026-07-12", dateTo: "2026-07-20",
  };
  statistics.App.statisticsDraftDirty = true;
  statistics.App.statisticsQueryTimer = setTimeout(() => { timerFired = true; }, 1000);
  statistics.element("stats-export-status").textContent = "temporary";
  statistics.load("statistics.js");
  statistics.App.resetStatisticsTransientUi();
  assert.equal(statistics.App.statisticsQueryTimer, null);
  assert.equal(statistics.element("stats-export-status").textContent, "");
  assert.deepEqual(statistics.App.statisticsAcceptedPayload, { summary: { total: 1 } });
  assert.deepEqual(statistics.App.statisticsSelection, {
    allTime: false, dateFrom: "2026-07-01", dateTo: "2026-07-29",
  });
  assert.deepEqual(JSON.parse(JSON.stringify(statistics.App.statisticsDraftSelection)), {
    allTime: false, dateFrom: "2026-07-01", dateTo: "2026-07-29",
  });
  assert.equal(statistics.App.statisticsDraftDirty, false);
  assert.equal(statistics.element("statistics-date-from").value, "2026-07-01");
  assert.equal(statistics.element("statistics-date-to").value, "2026-07-29");
  clearTimeout(statistics.App.statisticsQueryTimer);
  assert.equal(timerFired, false);
});
