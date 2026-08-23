const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function createHarness() {
  const elements = new Map();
  const documentListeners = new Map();
  const windowListeners = new Map();
  const timers = new Map();
  let nextTimerId = 1;
  let activeElement = null;

  function classList() {
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

  function node(id) {
    if (elements.has(id)) return elements.get(id);
    const attributes = new Map();
    const listeners = new Map();
    const item = {
      id,
      hidden: false,
      disabled: false,
      textContent: "",
      innerHTML: "",
      className: "",
      style: {},
      parentNode: null,
      children: [],
      offsetWidth: 80,
      offsetHeight: 24,
      classList: classList(),
      setAttribute(name, value) { attributes.set(name, String(value)); },
      getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
      removeAttribute(name) { attributes.delete(name); },
      addEventListener(name, handler) {
        if (!listeners.has(name)) listeners.set(name, []);
        listeners.get(name).push(handler);
      },
      dispatch(name, event = {}) {
        for (const handler of listeners.get(name) || []) {
          handler.call(item, {
            target: item,
            currentTarget: item,
            preventDefault() {},
            stopPropagation() {},
            ...event,
          });
        }
      },
      appendChild(child) {
        child.parentNode = item;
        item.children.push(child);
      },
      removeChild(child) {
        item.children = item.children.filter((candidate) => candidate !== child);
        child.parentNode = null;
      },
      contains(target) {
        let current = target;
        while (current) {
          if (current === item) return true;
          current = current.parentNode;
        }
        return false;
      },
      closest(selector) {
        if (selector !== "[data-tooltip]") return null;
        let current = item;
        while (current) {
          if (typeof current.getAttribute === "function" && current.getAttribute("data-tooltip")) {
            return current;
          }
          current = current.parentNode;
        }
        return null;
      },
      focus() {
        activeElement = item;
        dispatchDocument("focusin", { target: item });
      },
      getClientRects() { return [1]; },
      getBoundingClientRect() {
        return { left: 20, top: 20, width: 30, height: 30, bottom: 50 };
      },
      querySelector() { return null; },
      querySelectorAll() { return []; },
    };
    Object.defineProperty(item, "firstChild", {
      get() { return item.children[0] || null; },
    });
    elements.set(id, item);
    return item;
  }

  const body = node("body");
  const documentElement = node("html");
  documentElement.contains = () => true;
  const document = {
    body,
    documentElement,
    get activeElement() { return activeElement; },
    getElementById: node,
    createElement(tag) { return node(`created-${tag}-${elements.size}`); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener(name, handler) {
      if (!documentListeners.has(name)) documentListeners.set(name, []);
      documentListeners.get(name).push(handler);
    },
  };

  function dispatchDocument(name, event = {}) {
    for (const handler of documentListeners.get(name) || []) {
      handler({
        target: event.target || node("event-target"),
        relatedTarget: event.relatedTarget || null,
        key: event.key || "",
        shiftKey: !!event.shiftKey,
        preventDefault() {},
        stopPropagation() {},
        ...event,
      });
    }
  }

  const window = {
    WorkTraceApp: { shellVisible: true },
    innerWidth: 1200,
    innerHeight: 800,
    addEventListener(name, handler) {
      if (!windowListeners.has(name)) windowListeners.set(name, []);
      windowListeners.get(name).push(handler);
    },
  };

  function setTimeoutStub(fn, ms) {
    const id = nextTimerId++;
    timers.set(id, { fn, ms, cleared: false });
    return id;
  }
  function clearTimeoutStub(id) {
    const timer = timers.get(id);
    if (timer) timer.cleared = true;
  }
  function runTimers() {
    for (const [id, timer] of Array.from(timers.entries())) {
      if (timer.cleared) continue;
      timer.cleared = true;
      timer.fn();
      timers.set(id, timer);
    }
  }

  const context = {
    window,
    document,
    Promise,
    Error,
    String,
    Number,
    Array,
    Object,
    Math,
    Date,
    setTimeout: setTimeoutStub,
    clearTimeout: clearTimeoutStub,
  };
  vm.createContext(context);
  const source = fs.readFileSync(
    path.join(__dirname, "../../worktrace/webview_ui/js/ui_components.js"),
    "utf8"
  );
  vm.runInContext(source, context, { filename: "ui_components.js" });

  return {
    App: window.WorkTraceApp,
    node,
    dispatchDocument,
    dispatchWindow(name, event = {}) {
      for (const handler of windowListeners.get(name) || []) handler(event);
    },
    runTimers,
    pendingTimers() {
      return Array.from(timers.values()).filter((timer) => !timer.cleared);
    },
  };
}

test("pointer hover requires dwell and click dismisses the tooltip", () => {
  const h = createHarness();
  const target = h.node("nav-settings");
  const tooltip = h.node("app-tooltip");
  target.setAttribute("data-tooltip", "设置与隐私");
  tooltip.hidden = true;

  h.dispatchDocument("mousemove", { target });
  assert.equal(tooltip.hidden, true);
  assert.equal(h.pendingTimers().length, 1);
  assert.equal(h.pendingTimers()[0].ms, 450);

  h.runTimers();
  assert.equal(tooltip.hidden, false);
  assert.equal(tooltip.textContent, "设置与隐私");

  h.dispatchDocument("pointerdown", { target });
  assert.equal(tooltip.hidden, true);
  assert.equal(tooltip.textContent, "");
});

test("disabled controls can still explain why an action is unavailable", () => {
  const h = createHarness();
  const target = h.node("delete-disabled");
  const tooltip = h.node("app-tooltip");
  target.disabled = true;
  target.setAttribute("data-tooltip", "不可删除");
  tooltip.hidden = true;

  h.dispatchDocument("mousemove", { target });
  h.runTimers();

  assert.equal(tooltip.hidden, false);
  assert.equal(tooltip.textContent, "不可删除");
});

test("keyboard focus may disclose a tooltip but quiet programmatic focus may not", () => {
  const h = createHarness();
  const target = h.node("advanced-toggle");
  const tooltip = h.node("app-tooltip");
  target.setAttribute("data-tooltip", "高级操作");
  tooltip.hidden = true;

  h.dispatchDocument("keydown", { key: "Tab" });
  target.focus();
  assert.equal(tooltip.hidden, false);
  assert.equal(tooltip.textContent, "高级操作");

  h.App.hideTooltip();
  h.dispatchDocument("keydown", { key: "Escape" });
  h.App.focusWithoutTransientUi(target);
  assert.equal(tooltip.hidden, true);
});

test("shell hide clears presentation-only UI and safely cancels confirmation", async () => {
  const h = createHarness();
  const target = h.node("delete-trigger");
  const tooltip = h.node("app-tooltip");
  const toast = h.node("app-toast");
  const dialogLayer = h.node("confirm-dialog-layer");
  target.setAttribute("data-tooltip", "删除时间段");
  tooltip.hidden = true;
  toast.hidden = true;
  dialogLayer.hidden = true;

  h.dispatchDocument("mousemove", { target });
  h.runTimers();
  h.App.showToast("已删除");
  const confirmation = h.App.openConfirmDialog({ trigger: target, title: "确认删除" });

  h.App.uiPrimitives.onShellHidden();

  assert.equal(tooltip.hidden, true);
  assert.equal(toast.hidden, true);
  assert.equal(toast.textContent, "");
  assert.equal(dialogLayer.hidden, true);
  assert.equal(await confirmation, false);
  assert.equal(h.App.transientInputModality(), "none");
});

test("window blur disarms restored focus until a new user input", () => {
  const h = createHarness();
  const target = h.node("nav-rules");
  const tooltip = h.node("app-tooltip");
  target.setAttribute("data-tooltip", "项目规则");
  tooltip.hidden = true;

  h.dispatchDocument("keydown", { key: "Tab" });
  h.dispatchWindow("blur");
  target.focus();
  assert.equal(tooltip.hidden, true);

  h.dispatchDocument("keydown", { key: "Tab" });
  target.focus();
  assert.equal(tooltip.hidden, false);
});
