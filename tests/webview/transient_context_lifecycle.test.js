const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { TIMELINE_MODULES, loadTimelineModules } = require("./timeline_test_modules");
const { SETTINGS_MODULES } = require("./settings_test_helpers");

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
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
  const documentListeners = new Map();
  const windowListeners = new Map();
  let activeElement = null;

  function element(id) {
    if (!elements.has(id)) {
      const attrs = new Map();
      const listeners = new Map();
      const node = {
        id,
        hidden: false,
        disabled: false,
        checked: false,
        readOnly: false,
        open: false,
        type: "text",
        value: "",
        textContent: "",
        innerHTML: "",
        className: "",
        dataset: {},
        children: [],
        parentNode: null,
        classList: createClassList(),
        setAttribute(name, value) { attrs.set(name, String(value)); },
        getAttribute(name) { return attrs.has(name) ? attrs.get(name) : null; },
        removeAttribute(name) { attrs.delete(name); },
        contains(target) {
          let current = target;
          while (current) {
            if (current === node) return true;
            current = current.parentNode;
          }
          return false;
        },
        addEventListener(name, handler) {
          if (!listeners.has(name)) listeners.set(name, []);
          listeners.get(name).push(handler);
        },
        dispatch(name, event = {}) {
          for (const handler of listeners.get(name) || []) {
            handler.call(node, {
              target: node,
              currentTarget: node,
              preventDefault() {},
              stopPropagation() {},
              ...event,
            });
          }
        },
        focus() { activeElement = node; },
        appendChild(child) {
          child.parentNode = node;
          node.children.push(child);
        },
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

  const settingSections = ["general", "privacy", "data", "advanced"].map((section) => {
    const button = element(`settings-category-${section}`);
    button.setAttribute("data-settings-section", section);
    if (section === "general") button.setAttribute("aria-current", "true");
    return button;
  });

  const documentElement = element("html");
  documentElement.contains = () => true;
  const body = element("body");

  const document = {
    readyState: "loading",
    body,
    documentElement,
    get activeElement() { return activeElement; },
    getElementById: element,
    createElement(tag) { return element(`created-${tag}-${elements.size}`); },
    contains() { return true; },
    querySelectorAll(selector) {
      if (selector === "[data-settings-section]") return settingSections;
      if (selector === ".password-reveal-button") return [];
      if (selector === "#timeline-sessions-list .timeline-item") return [];
      return [];
    },
    querySelector(selector) {
      if (selector === "#settings-section-advanced details") {
        return element("settings-diagnostics");
      }
      if (selector.startsWith('#settings-status [data-settings-key="')) return null;
      return null;
    },
    addEventListener(name, handler) {
      if (!documentListeners.has(name)) documentListeners.set(name, []);
      documentListeners.get(name).push(handler);
    },
    removeEventListener() {},
  };

  const window = {
    WorkTraceApp: {},
    document,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    matchMedia: () => ({ matches: false }),
    addEventListener(name, handler) {
      if (!windowListeners.has(name)) windowListeners.set(name, []);
      windowListeners.get(name).push(handler);
    },
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

  function dispatchDocument(name, event = {}) {
    for (const handler of documentListeners.get(name) || []) {
      handler({
        target: event.target || element("document-event-target"),
        key: event.key || "",
        shiftKey: !!event.shiftKey,
        preventDefault() {},
        stopPropagation() {},
        ...event,
      });
    }
  }

  return {
    App: window.WorkTraceApp,
    document,
    element,
    settingSections,
    load,
    dispatchDocument,
    activeElement: () => activeElement,
  };
}

function prepareTimeline() {
  const h = createHarness();
  Object.assign(h.App, {
    mutationState: "idle",
    editSaving: false,
    editingSession: null,
    timelineDurationDraftTouched: false,
    timelineDurationDraftInvalid: false,
    timelineAutosaveQueued: false,
    detailsInFlight: {},
    currentSessions: [],
    timelineDate: "2026-08-18",
    selectedProjectionInstanceKey: "session-a",
    selectedProjectionRevision: "r1",
    projectCatalog: {
      getEditing: () => [],
      getFilter: () => [],
      load: () => Promise.resolve({ editingProjects: [], filterProjects: [] }),
    },
  });
  for (const file of TIMELINE_MODULES) h.load(file);
  h.element("timeline-session-actions").hidden = true;
  h.element("timeline-advanced-toggle").setAttribute("aria-expanded", "false");
  return h;
}

test("timeline context changes dismiss the advanced menu before the new action", async () => {
  const h = prepareTimeline();
  let ran = false;
  h.element("timeline-session-actions").hidden = false;
  h.element("timeline-advanced-toggle").setAttribute("aria-expanded", "true");

  const result = await h.App.requestTimelineContextChange(() => {
    ran = true;
  }, "切换日期");

  assert.equal(result, undefined);
  assert.equal(ran, true);
  assert.equal(h.element("timeline-session-actions").hidden, true);
  assert.equal(h.element("timeline-advanced-toggle").getAttribute("aria-expanded"), "false");
});

test("timeline menu dismisses immediately even when a context change waits for save", async () => {
  const h = prepareTimeline();
  h.App.editSaving = true;
  h.element("timeline-session-actions").hidden = false;
  h.element("timeline-advanced-toggle").setAttribute("aria-expanded", "true");

  const result = await h.App.requestTimelineContextChange(() => {}, "切换时间段");

  assert.equal(result, false);
  assert.equal(h.element("timeline-session-actions").hidden, true);
  assert.equal(h.App.pendingContextChange.reason, "切换时间段");
});

test("timeline advanced menu dismisses on outside pointer or focus but not inside interaction", () => {
  const h = prepareTimeline();
  const menu = h.element("timeline-session-actions");
  const toggle = h.element("timeline-advanced-toggle");
  const menuChild = h.element("timeline-menu-child");
  const toggleChild = h.element("timeline-toggle-child");
  const outside = h.element("timeline-outside");
  menu.appendChild(menuChild);
  toggle.appendChild(toggleChild);
  h.App.initTimelineAccessibility();

  menu.hidden = false;
  h.dispatchDocument("pointerdown", { target: menuChild });
  assert.equal(menu.hidden, false);
  h.dispatchDocument("pointerdown", { target: toggleChild });
  assert.equal(menu.hidden, false);
  h.dispatchDocument("pointerdown", { target: outside });
  assert.equal(menu.hidden, true);

  menu.hidden = false;
  h.dispatchDocument("focusin", { target: outside });
  assert.equal(menu.hidden, true);
});

test("timeline deletion confirmation dismisses the advanced menu before opening the dialog", async () => {
  const h = prepareTimeline();
  const trigger = h.element("timeline-hide-session");
  let menuWasClosedWhenDialogOpened = false;
  h.App.openDeleteDialog = () => {
    menuWasClosedWhenDialogOpened = h.element("timeline-session-actions").hidden;
    return Promise.resolve(false);
  };
  h.element("timeline-session-actions").hidden = false;

  await h.App.confirmTimelineDeletion("hide", {}, trigger);

  assert.equal(menuWasClosedWhenDialogOpened, true);
  assert.equal(h.element("timeline-session-actions").hidden, true);
});

function prepareSettings() {
  const h = createHarness();
  Object.assign(h.App, {
    currentPage: "settings",
    handleResult: (result) => result,
    extractBridgeError: (result, fallback) => result && result.error || fallback,
    clearGlobalAlert() {},
    clearSettingsError() {},
    trapFocus() {},
  });
  h.element("first-run-notice-overlay").hidden = true;
  h.element("first-run-notice-close-btn").hidden = true;
  SETTINGS_MODULES.forEach(h.load);
  h.App.initSettingsCategories();
  return h;
}

test("settings privacy notice view supports Escape, backdrop close, and focus restoration", async () => {
  const h = prepareSettings();
  const trigger = h.element("settings-privacy-notice-btn");
  const close = h.element("first-run-notice-close-btn");
  const overlay = h.element("first-run-notice-overlay");
  h.App.bridge = {
    getFirstRunNotice: () => Promise.resolve({
      ok: true,
      notice: { accepted: true, title: "隐私说明", text: "内容", highlights: [] },
    }),
  };

  assert.equal(await h.App.openPrivacyNoticeFromSettings(), true);
  assert.equal(overlay.hidden, false);
  assert.equal(h.activeElement(), close);
  h.dispatchDocument("keydown", { key: "Escape" });
  assert.equal(overlay.hidden, true);
  assert.equal(h.activeElement(), trigger);

  assert.equal(await h.App.openPrivacyNoticeFromSettings(), true);
  overlay.dispatch("click", { target: overlay });
  assert.equal(overlay.hidden, true);
  assert.equal(h.activeElement(), trigger);
});

test("startup privacy gate stays fail-closed under Escape and backdrop clicks", () => {
  const h = prepareSettings();
  const overlay = h.element("first-run-notice-overlay");

  h.App.showFirstRunNotice(
    { accepted: false, title: "隐私说明", text: "内容", highlights: [] },
    "gate"
  );
  assert.equal(h.App.settingsTransientUi.isNoticeViewOpen(), false);
  assert.equal(overlay.hidden, false);

  h.dispatchDocument("keydown", { key: "Escape" });
  overlay.dispatch("click", { target: overlay });

  assert.equal(overlay.hidden, false);
});

test("stale settings privacy notice completion cannot reopen after page reset", async () => {
  const h = prepareSettings();
  const pending = deferred();
  const overlay = h.element("first-run-notice-overlay");
  h.App.bridge = { getFirstRunNotice: () => pending.promise };

  const opening = h.App.openPrivacyNoticeFromSettings();
  h.App.resetSettingsTransientUi({ restoreFocus: false });
  pending.resolve({
    ok: true,
    notice: { accepted: true, title: "旧请求", text: "内容", highlights: [] },
  });

  assert.equal(await opening, false);
  assert.equal(overlay.hidden, true);
  assert.equal(h.App.settingsTransientUi.isNoticeViewOpen(), false);
});

test("leaving a settings category clears presentation state without discarding form drafts", () => {
  const h = prepareSettings();
  const categories = Object.fromEntries(
    h.settingSections.map((button) => [button.getAttribute("data-settings-section"), button])
  );
  categories.general.removeAttribute("aria-current");
  categories.data.setAttribute("aria-current", "true");
  const manifest = h.element("settings-backup-manifest");
  const passphrase = h.element("settings-backup-passphrase");
  manifest.hidden = false;
  passphrase.value = "draft stays";
  h.element("settings-backup-status").textContent = "temporary";
  h.element("settings-backup-status").hidden = false;

  categories.privacy.dispatch("click");

  assert.equal(manifest.hidden, true);
  assert.equal(passphrase.value, "draft stays");
  assert.equal(h.element("settings-backup-status").textContent, "");
});

test("leaving advanced settings collapses transient diagnostics", () => {
  const h = prepareSettings();
  const diagnostics = h.element("settings-diagnostics");
  diagnostics.open = true;

  h.App.resetSettingsSectionTransientUi("advanced");

  assert.equal(diagnostics.open, false);
});
