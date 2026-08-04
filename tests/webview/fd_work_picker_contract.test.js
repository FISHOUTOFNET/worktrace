const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../worktrace/integrations/fd_work/fd_work_adapter.js"),
  "utf8"
);

function harness({ selectedLabel = "", inputValue = "", bridgeResponse = { ok: true, accepted: true } } = {}) {
  const mutations = { focus: 0, click: 0, input: 0, change: 0, escape: 0, blur: 0 };
  const bridgeCalls = [];
  const listeners = new Map();
  const attrs = new Map([["aria-controls", "case-list"]]);
  const selectionItem = {
    textContent: selectedLabel,
    title: selectedLabel,
    getAttribute(name) { return name === "title" ? this.title : null; },
    getClientRects() { return selectedLabel ? [{}] : []; },
    getBoundingClientRect() { return { width: selectedLabel ? 120 : 0, height: 24 }; },
  };
  const wrapper = {
    querySelector(selector) {
      if (selector.includes("selection-item")) return selectedLabel ? selectionItem : null;
      return null;
    },
  };
  const input = {
    value: inputValue,
    disabled: false,
    readOnly: false,
    parentElement: wrapper,
    getAttribute(name) { return attrs.get(name) || null; },
    getClientRects() { return [{}]; },
    getBoundingClientRect() { return { width: 180, height: 32, left: 10, top: 10 }; },
    closest() { return wrapper; },
    focus() { mutations.focus += 1; },
    click() { mutations.click += 1; },
    blur() { mutations.blur += 1; },
    dispatchEvent(event) {
      if (event.type === "input") mutations.input += 1;
      if (event.type === "change") mutations.change += 1;
    },
  };
  const popup = {
    getClientRects() { return [{}]; },
    getBoundingClientRect() { return { width: 300, height: 200 }; },
    querySelectorAll(selector) {
      if (selector.includes("aria-selected='true'") && selectedLabel) {
        return [{
          textContent: selectedLabel,
          innerText: selectedLabel,
          getAttribute() { return selectedLabel; },
          getClientRects() { return [{}]; },
        }];
      }
      return [];
    },
  };
  const form = {
    children: [],
    appendChild(node) { this.children.push(node); return node; },
    querySelectorAll() { return []; },
  };
  const nodesById = new Map([["case-list", popup]]);
  function createNode(tag) {
    const nodeListeners = new Map();
    const node = {
      tagName: tag.toUpperCase(), id: "", textContent: "", disabled: false,
      children: [], parentElement: null, style: {},
      classList: { add() {}, remove() {} },
      setAttribute() {}, removeAttribute() {},
      addEventListener(name, handler) { nodeListeners.set(name, handler); },
      appendChild(child) { child.parentElement = node; node.children.push(child); return child; },
      remove() { if (this.id) nodesById.delete(this.id); },
      click() { if (nodeListeners.has("click")) nodeListeners.get("click")({ preventDefault() {} }); },
    };
    return node;
  }
  const document = {
    visibilityState: "visible",
    body: { firstElementChild: {}, appendChild(node) { if (node.id) nodesById.set(node.id, node); } },
    documentElement: { setAttribute() {}, removeAttribute() {} },
    querySelector(selector) {
      if (selector === "#case") return input;
      if (selector === "#case-list") return popup;
      if (selector === "form#basic") return form;
      return null;
    },
    querySelectorAll() { return []; },
    getElementById(id) { return nodesById.get(id) || null; },
    createElement: createNode,
  };
  const context = {
    Promise, Object, String, Array,
    Event: class Event { constructor(type) { this.type = type; } },
    KeyboardEvent: class KeyboardEvent {
      constructor(type, options) {
        this.type = type;
        if (type === "keydown" && options && options.key === "Escape") mutations.escape += 1;
      }
    },
    HTMLInputElement: class {}, HTMLTextAreaElement: class {},
    MutationObserver: class { observe() {} disconnect() {} },
    clearTimeout, setTimeout, document,
    requestAnimationFrame(callback) { return setTimeout(callback, 0); },
    window: {
      innerWidth: 980, innerHeight: 760,
      location: { href: "https://work.fangdalaw.com/Works/WorkHourList?picker=day" },
      getComputedStyle() { return { display: "block", visibility: "visible" }; },
      addEventListener(name, handler) { listeners.set(name, handler); },
      pywebview: { api: {
        submit_case_picker_confirmation(...args) {
          bridgeCalls.push(["confirm", ...args]);
          return Promise.resolve(bridgeResponse);
        },
        submit_case_picker_cancellation(...args) {
          bridgeCalls.push(["cancel", ...args]);
          return Promise.resolve(bridgeResponse);
        },
      } },
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "fd_work_adapter.js" });
  return {
    adapter: context.window.WorkTraceFDWorkAdapter,
    input,
    popup,
    mutations,
    bridgeCalls,
    toolbar() { return nodesById.get("worktrace-fdwork-picker-toolbar"); },
    pagehide() { if (listeners.has("pagehide")) listeners.get("pagehide")(); },
    contract: {
      version: 5,
      operation_nonce: "picker-nonce",
      operation_generation: 7,
      field: { selector: "#case", listbox: "#case-list" },
      fields: { case_number: { selector: "#case", listbox: "#case-list" } },
      form_selector: "form#basic",
      max_label_length: 100,
      deadline_ms: 500,
    },
  };
}

test("adapter v5 removes search and interactive handshake entry points", () => {
  const { adapter } = harness();
  assert.equal(adapter.version, 5);
  assert.equal(adapter.searchCases, undefined);
  assert.equal(adapter.interactiveHandshake, undefined);
  assert.equal(typeof adapter.awaitStableWorkShell, "function");
  assert.equal(typeof adapter.enterCasePicker, "function");
  assert.equal(typeof adapter.leaveCasePicker, "function");
  assert.equal(typeof adapter.readSelectedCase, "function");
});

test("stable shell readiness has no focus click input change escape or blur side effects", async () => {
  const h = harness();
  const result = await h.adapter.awaitStableWorkShell(h.contract);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.deepEqual(h.mutations, { focus: 0, click: 0, input: 0, change: 0, escape: 0, blur: 0 });
});

test("entering picker does not open or modify the native combobox", async () => {
  const h = harness({ inputValue: "user query" });
  const entered = await h.adapter.enterCasePicker(h.contract);
  assert.equal(entered.ok, true, JSON.stringify(entered));
  assert.equal(h.input.value, "user query");
  assert.deepEqual(h.mutations, { focus: 0, click: 0, input: 0, change: 0, escape: 0, blur: 0 });
});

test("free search text without committed Ant selection fails closed", () => {
  const h = harness({ inputValue: "CASE TYPED" });
  const selected = h.adapter.readSelectedCase(h.contract);
  assert.equal(selected.ok, false);
  assert.equal(selected.error, "case_selection_required");
});

test("committed Ant selection is canonical and confirmable", () => {
  const h = harness({ selectedLabel: "\u3000CASE A\u00a0", inputValue: "CASE A" });
  const selected = h.adapter.readSelectedCase(h.contract);
  assert.deepEqual(
    { ok: selected.ok, label: selected.label },
    { ok: true, label: "CASE A" }
  );
});

test("confirm submits proof asynchronously without a same-window read and stays disabled", async () => {
  const h = harness({ selectedLabel: "CASE A", inputValue: "CASE A" });
  await h.adapter.enterCasePicker(h.contract);
  const toolbar = h.toolbar();
  toolbar.children[1].click();
  await Promise.resolve();

  assert.deepEqual(h.bridgeCalls, [["confirm", "picker-nonce", "CASE A", 1]]);
  assert.equal(toolbar.children[1].disabled, true);
  assert.equal(toolbar.children[2].disabled, true);
  assert.equal(h.input.disabled, true);
});

test("explicit bridge rejection restores picker interaction", async () => {
  const h = harness({
    selectedLabel: "CASE A",
    inputValue: "CASE A",
    bridgeResponse: { ok: false, error: "picker_superseded" },
  });
  await h.adapter.enterCasePicker(h.contract);
  const toolbar = h.toolbar();
  toolbar.children[1].click();
  await Promise.resolve();

  assert.equal(toolbar.children[1].disabled, false);
  assert.equal(toolbar.children[2].disabled, false);
  assert.equal(h.input.disabled, false);
});

test("leaving or canceling picker does not clear query or close popup", async () => {
  const h = harness({ inputValue: "three keywords remain" });
  await h.adapter.enterCasePicker(h.contract);
  const left = h.adapter.leaveCasePicker();
  assert.equal(left.ok, true, JSON.stringify(left));
  assert.equal(h.input.value, "three keywords remain");
  assert.deepEqual(h.mutations, { focus: 0, click: 0, input: 0, change: 0, escape: 0, blur: 0 });
});

test("fill code prepares the case combobox once and has no unconditional cleanup escape or blur", () => {
  const fillBody = source.slice(source.indexOf("async function fillEntry"), source.lastIndexOf("window.WorkTraceFDWorkAdapter ="));
  assert.equal((fillBody.match(/prepareCaseCombobox\s*\(/g) || []).length, 1);
  assert.doesNotMatch(fillBody, /KeyboardEvent\([^)]*Escape/);
  assert.doesNotMatch(fillBody, /\.blur\s*\(/);
  assert.match(fillBody, /finally[\s\S]*removeFillBlockingLayer/);
});

test("picker and fill modes are explicitly mutually exclusive and navigation cancels old work", () => {
  assert.match(source, /activeMode\s*===\s*["']picker["']/);
  assert.match(source, /activeMode\s*===\s*["']fill["']/);
  assert.match(source, /pagehide/);
  assert.match(source, /lookup_superseded/);
});
