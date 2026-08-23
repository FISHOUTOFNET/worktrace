const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function harness() {
  const elements = new Map();
  const documentListeners = new Map();
  let activeElement = null;

  function makeClassList() {
    const values = new Set();
    return {
      add(...names) { names.forEach((name) => values.add(name)); },
      remove(...names) { names.forEach((name) => values.delete(name)); },
      contains(name) { return values.has(name); },
      toggle(name, force) {
        if (force === true) values.add(name);
        else if (force === false) values.delete(name);
        else if (values.has(name)) values.delete(name);
        else values.add(name);
      },
    };
  }

  function makeElement(id) {
    const listeners = new Map();
    const value = {
      id,
      hidden: false,
      disabled: false,
      textContent: "",
      innerHTML: "",
      parentNode: null,
      offsetParent: {},
      classList: makeClassList(),
      children: [],
      getClientRects() { return [{ width: 10, height: 10 }]; },
      getAttribute() { return null; },
      setAttribute() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
      appendChild(child) {
        child.parentNode = value;
        value.children.push(child);
      },
      addEventListener(type, handler) { listeners.set(type, handler); },
      focus() { activeElement = value; },
      dispatch(type, event = {}) {
        const handler = listeners.get(type);
        if (handler) handler({ target: value, preventDefault() {}, ...event });
      },
    };
    return value;
  }

  function element(id) {
    if (!elements.has(id)) elements.set(id, makeElement(id));
    return elements.get(id);
  }

  const layer = element("confirm-dialog-layer");
  const dialog = element("confirm-dialog");
  const primary = element("confirm-dialog-primary");
  const secondary = element("confirm-dialog-secondary");
  dialog.querySelectorAll = () => [secondary, primary];
  primary.parentNode = dialog;
  secondary.parentNode = dialog;
  dialog.parentNode = layer;

  const body = element("body");
  const documentElement = {
    contains() { return true; },
  };
  const context = {
    Promise, Error, String, Number, Array, Math, Date, setTimeout, clearTimeout,
    window: { WorkTraceApp: {} },
    document: {
      body,
      documentElement,
      get activeElement() { return activeElement; },
      getElementById: element,
      querySelector() { return null; },
      createElement(tag) { return makeElement(`created-${tag}-${elements.size}`); },
      addEventListener(type, handler) { documentListeners.set(type, handler); },
    },
  };
  vm.createContext(context);
  vm.runInContext(
    fs.readFileSync(
      path.join(__dirname, "../../worktrace/webview_ui/js/ui_components.js"),
      "utf8"
    ),
    context,
    { filename: "ui_components.js" }
  );

  return {
    App: context.window.WorkTraceApp,
    element,
    primary,
    secondary,
    layer,
    dialog,
    setActive(target) { activeElement = target; },
    activeElement() { return activeElement; },
    keydown(event) {
      documentListeners.get("keydown")({
        preventDefault() {},
        shiftKey: false,
        ...event,
      });
    },
  };
}

test("openConfirmDialog supports a one-step confirmation with generic defaults", async () => {
  const state = harness();
  const promise = state.App.openConfirmDialog({});

  assert.equal(state.layer.hidden, false);
  assert.equal(state.element("confirm-dialog-title").textContent, "确认操作");
  assert.equal(state.primary.textContent, "确认");
  state.primary.dispatch("click");

  assert.equal(await promise, true);
  assert.equal(state.layer.hidden, true);
});

test("openDeleteDialog preserves two-step safety without rewriting caller copy", async () => {
  const state = harness();
  const promise = state.App.openDeleteDialog({
    objectLabel: "时间段",
    confirmLabel: "删除时间段",
  });

  assert.equal(state.element("confirm-dialog-title").textContent, "确认删除");
  assert.equal(state.primary.textContent, "继续");
  state.primary.dispatch("click");
  assert.equal(state.element("confirm-dialog-title").textContent, "确认删除");
  assert.equal(state.secondary.textContent, "返回");
  assert.equal(state.primary.textContent, "删除时间段");
  assert.equal(state.primary.classList.contains("danger"), true);
  state.primary.dispatch("click");

  assert.equal(await promise, true);
});

test("Escape, overlay cancellation, focus trap, and focus restoration remain intact", async () => {
  const state = harness();
  let restored = 0;
  const trigger = { focus() { restored += 1; } };
  const escapePromise = state.App.openConfirmDialog({ trigger });
  state.keydown({ key: "Escape" });
  assert.equal(await escapePromise, false);
  assert.equal(restored, 1);

  const overlayPromise = state.App.openConfirmDialog({});
  state.layer.dispatch("click", { target: state.layer });
  assert.equal(await overlayPromise, false);

  const trapPromise = state.App.openConfirmDialog({});
  state.setActive(state.primary);
  state.keydown({ key: "Tab" });
  assert.equal(state.activeElement(), state.secondary);
  state.keydown({ key: "Escape" });
  assert.equal(await trapPromise, false);
});

test("only one confirm dialog can exist at a time", async () => {
  const state = harness();
  const first = state.App.openConfirmDialog({ title: "第一个" });
  const second = state.App.openConfirmDialog({ title: "第二个" });

  assert.equal(await second, false);
  assert.equal(state.element("confirm-dialog-title").textContent, "第一个");
  state.secondary.dispatch("click");
  assert.equal(await first, false);
});
