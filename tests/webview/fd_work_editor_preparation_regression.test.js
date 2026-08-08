const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const adapterSource = fs.readFileSync(
  path.join(__dirname, "../../worktrace/integrations/fd_work/fd_work_adapter.js"),
  "utf8"
);

const FILL_BLOCKER_ID = "worktrace-fdwork-fill-blocker";

function harness(options = {}) {
  const byId = new Map();
  let form = options.formInitiallyPresent ? makeNode() : null;
  let input = null;
  let wrapper = null;
  let frame = 0;
  let createClicks = 0;
  let blockerPresentAtCreateClick = false;
  const blockerFrames = [];

  function makeNode(overrides = {}) {
    const attributes = new Map();
    const node = {
      id: "",
      disabled: false,
      readOnly: false,
      value: "",
      textContent: "",
      innerText: "",
      parentElement: null,
      isConnected: true,
      style: {},
      classList: { contains() { return false; } },
      getAttribute(name) { return attributes.has(name) ? attributes.get(name) : null; },
      setAttribute(name, value) { attributes.set(name, String(value)); },
      removeAttribute(name) { attributes.delete(name); },
      getClientRects() { return [{}]; },
      getBoundingClientRect() {
        return { left: 0, top: 0, width: 100, height: 24, right: 100, bottom: 24 };
      },
      appendChild() {},
      insertBefore() {},
      querySelector() { return null; },
      querySelectorAll() { return []; },
      addEventListener() {},
      removeEventListener() {},
      contains(child) { return child === input; },
      closest() { return null; },
      remove() {
        node.isConnected = false;
        if (node.id) byId.delete(node.id);
      },
      ...overrides,
    };
    return node;
  }

  function mountEditor() {
    if (!form) form = makeNode();
    wrapper = makeNode();
    input = makeNode({
      closest(selector) { return selector === ".ant-select" ? wrapper : null; },
    });
    input.parentElement = wrapper;
    form.contains = (candidate) => candidate === input;
  }

  const createButton = options.createButton ? makeNode({
    innerText: "创建工时",
    textContent: "创建工时",
    click() {
      createClicks += 1;
      blockerPresentAtCreateClick = byId.has(FILL_BLOCKER_ID);
      if (options.mountEditorOnCreate !== false) mountEditor();
    },
  }) : null;

  const head = makeNode({
    appendChild(node) {
      node.isConnected = true;
      if (node.id) byId.set(node.id, node);
    },
  });
  const body = makeNode({
    firstChild: null,
    appendChild(node) {
      node.isConnected = true;
      if (node.id) byId.set(node.id, node);
    },
    insertBefore(node) {
      node.isConnected = true;
      if (node.id) byId.set(node.id, node);
    },
  });
  const documentElement = makeNode();

  const document = {
    visibilityState: "visible",
    head,
    body,
    documentElement,
    getElementById(id) { return byId.get(id) || null; },
    createElement() { return makeNode(); },
    querySelector(selector) {
      if (selector === "form#basic") return form;
      if (selector === "#basic_caseId") return input;
      return null;
    },
    querySelectorAll(selector) {
      if (selector === "button, [role='button'], input[type='button']") {
        return createButton ? [createButton] : [];
      }
      return [];
    },
    addEventListener() {},
    removeEventListener() {},
  };

  const window = {
    WorkTraceApp: {},
    WorkTraceFDWorkAdapter: null,
    innerWidth: 1200,
    innerHeight: 800,
    location: { origin: "https://work.fangdalaw.com" },
    getComputedStyle() { return { display: "block", visibility: "visible" }; },
    addEventListener() {},
    removeEventListener() {},
  };
  window.top = window;

  const context = {
    window,
    document,
    console,
    Promise,
    Date,
    Number,
    Object,
    Array,
    String,
    Math,
    setTimeout,
    clearTimeout,
    Event: class Event {},
    MouseEvent: class MouseEvent {},
    PointerEvent: class PointerEvent {},
    HTMLInputElement: class HTMLInputElement {},
    HTMLTextAreaElement: class HTMLTextAreaElement {},
    MutationObserver: class MutationObserver {
      observe() {}
      disconnect() {}
    },
    requestAnimationFrame(callback) {
      frame += 1;
      blockerFrames.push(byId.has(FILL_BLOCKER_ID));
      if (options.mountEditorAtFrame && frame === options.mountEditorAtFrame) mountEditor();
      Promise.resolve().then(() => callback(Date.now()));
      return frame;
    },
  };
  vm.createContext(context);
  vm.runInContext(adapterSource, context, { filename: "fd_work_adapter.js" });

  return {
    adapter: window.WorkTraceFDWorkAdapter,
    byId,
    blockerFrames,
    getCreateClicks: () => createClicks,
    blockerPresentAtCreateClick: () => blockerPresentAtCreateClick,
  };
}

function contract(deadline = Date.now() + 1000) {
  return {
    version: 5,
    operation_generation: 1,
    operation_deadline_ms: deadline,
    form_selector: "form#basic",
    entry_fields: {
      case_number: { selector: "#basic_caseId" },
    },
  };
}

test("existing editor shell waits for delayed Ant case mount instead of clicking create", async () => {
  const h = harness({ formInitiallyPresent: true, mountEditorAtFrame: 2 });

  const result = await h.adapter.ensureEntryEditor(contract());

  assert.equal(result.ok, true);
  assert.equal(result.create_click_count, 0);
  assert.equal(h.getCreateClicks(), 0);
  assert.equal(h.blockerFrames[0], true);
  assert.equal(h.byId.has(FILL_BLOCKER_ID), true);
});

test("true existing-hours page installs blocker before clicking create exactly once", async () => {
  const h = harness({ createButton: true });

  const result = await h.adapter.ensureEntryEditor(contract());

  assert.equal(result.ok, true);
  assert.equal(result.create_click_count, 1);
  assert.equal(h.getCreateClicks(), 1);
  assert.equal(h.blockerPresentAtCreateClick(), true);
  assert.equal(h.byId.has(FILL_BLOCKER_ID), true);
});

test("failed rendering releases preparation blocker and never falls through to create", async () => {
  const h = harness({ formInitiallyPresent: true, createButton: true });

  const result = await h.adapter.ensureEntryEditor(contract(Date.now() - 1));

  assert.equal(result.ok, false);
  assert.equal(result.error, "entry_editor_not_rendered");
  assert.equal(result.create_click_count, 0);
  assert.equal(h.getCreateClicks(), 0);
  assert.equal(h.byId.has(FILL_BLOCKER_ID), false);
});

test("source keeps rendering state ahead of create action and hands blocker to picker or fill", () => {
  const ensureStart = adapterSource.indexOf("async function ensureEntryEditor");
  const ensureEnd = adapterSource.indexOf("async function awaitStableWorkShell", ensureStart);
  const ensureBody = adapterSource.slice(ensureStart, ensureEnd);
  assert.ok(ensureStart >= 0 && ensureEnd > ensureStart);
  assert.ok(ensureBody.indexOf("state.form || state.input || state.wrapper") >= 0);
  assert.ok(
    ensureBody.indexOf("state.form || state.input || state.wrapper")
      < ensureBody.indexOf("document.querySelectorAll")
  );
  assert.ok(ensureBody.indexOf("installFillBlockingLayer()") < ensureBody.indexOf("action.click()"));

  const pickerStart = adapterSource.indexOf("function enterCasePicker");
  const pickerEnd = adapterSource.indexOf("function leaveCasePicker", pickerStart);
  const pickerBody = adapterSource.slice(pickerStart, pickerEnd);
  assert.match(pickerBody, /updatePickerToolbar\(\);[\s\S]*removeFillBlockingLayer\(\);/);

  const fillStart = adapterSource.indexOf("async function fillEntry");
  const fillEnd = adapterSource.indexOf("function actionHandler", fillStart);
  const fillBody = adapterSource.slice(fillStart, fillEnd);
  assert.match(fillBody, /installFillBlockingLayer\(\);/);
  assert.match(fillBody, /setFillBlockingMessage\("正在填入，请勿操作"\);/);
  assert.match(fillBody, /selectExactCase/);
  assert.match(fillBody, /fillDuration/);
  assert.match(fillBody, /fillNarrative/);
  assert.match(fillBody, /saveEntry/);
});
