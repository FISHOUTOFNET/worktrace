const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../worktrace/integrations/fd_work/fd_work_adapter.js"),
  "utf8"
);

function fieldHarness() {
  class Input {
    constructor() { this._value = ""; this.events = []; }
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
    dispatchEvent(event) { this.events.push(event.type); }
    getClientRects() { return [{}]; }
  }
  class Textarea extends Input {
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
  }
  const fields = new Map();
  const windowListeners = new Map();
  const actionResults = [];
  const context = {
    Promise, Object, String, Array,
    Event: class Event { constructor(type) { this.type = type; } },
    KeyboardEvent: class KeyboardEvent { constructor(type) { this.type = type; } },
    HTMLInputElement: Input,
    HTMLTextAreaElement: Textarea,
    MutationObserver: class { observe() {} disconnect() {} },
    setTimeout, clearTimeout,
    requestAnimationFrame(callback) { return setTimeout(callback, 0); },
    document: {
      visibilityState: "visible",
      documentElement: { setAttribute() {}, removeAttribute() {} },
      body: { firstElementChild: {}, appendChild() {}, insertBefore() {} },
      querySelector(selector) { return fields.get(selector) || null; },
      querySelectorAll() { return []; },
      getElementById() { return null; },
      createElement() {
        return {
          children: [], disabled: false, textContent: "", id: "",
          setAttribute() {}, addEventListener() {}, appendChild(child) { this.children.push(child); },
        };
      },
    },
    window: {
      innerWidth: 980, innerHeight: 760,
      location: {
        href: "https://work.fangdalaw.com/Works/WorkHourList?picker=day",
        origin: "https://work.fangdalaw.com",
      },
      getComputedStyle() { return { display: "block", visibility: "visible" }; },
      addEventListener(name, callback) { windowListeners.set(name, callback); },
      removeEventListener(name, callback) {
        if (windowListeners.get(name) === callback) windowListeners.delete(name);
      },
      pywebview: { api: {
        submit_adapter_action_result(nonce, action, result) {
          actionResults.push({ nonce, action, result });
          return Promise.resolve({ ok: true, accepted: true });
        },
      } },
    },
  };
  context.window.top = context.window;
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "fd_work_adapter.js" });
  return {
    adapter: context.window.WorkTraceFDWorkAdapter,
    fields,
    Input,
    Textarea,
    window: context.window,
    windowListeners,
    actionResults,
    context,
  };
}

test("adapter contract v5 exposes picker and fill modes without inline search handshake", () => {
  const { adapter } = fieldHarness();
  assert.equal(adapter.version, 5);
  for (const method of ["awaitStableWorkShell", "enterCasePicker", "leaveCasePicker", "readSelectedCase", "fillEntry"]) {
    assert.equal(typeof adapter[method], "function");
  }
  assert.equal(adapter.searchCases, undefined);
  assert.equal(adapter.interactiveHandshake, undefined);
});

test("picker entry is a synchronous DOM installation result", () => {
  const { adapter } = fieldHarness();
  const returned = adapter.enterCasePicker({
    version: 5,
    operation_nonce: "nonce",
    operation_generation: 2,
    fields: { case_number: { selector: "#missing" } },
  });

  assert.equal(typeof returned, "object");
  assert.equal(typeof returned?.then, "undefined");
  assert.equal(returned.ok, true);
  assert.equal(returned.status, "picker_ready");
});

test("picker observer is scoped to native selection DOM and toolbar writes are idempotent", () => {
  const enterStart = source.indexOf("function enterCasePicker");
  const leaveStart = source.indexOf("function leaveCasePicker", enterStart);
  const enterBody = source.slice(enterStart, leaveStart);
  const updateStart = source.indexOf("function updatePickerToolbar");
  const helperStart = source.indexOf("function helperApi", updateStart);
  const updateBody = source.slice(updateStart, helperStart);

  assert.match(source, /function observePickerSelectionDom/);
  assert.doesNotMatch(enterBody, /document\.body\s*\|\|\s*document\.documentElement/);
  assert.doesNotMatch(enterBody, /characterData:\s*true[\s\S]*document\.body/);
  assert.match(updateBody, /status\.textContent\s*!==\s*nextStatus/);
  assert.match(updateBody, /confirm\.disabled\s*!==\s*!proven/);
});

test("frame-hosted adapter uses the top-level pywebview bridge", () => {
  assert.match(source, /window\.top[\s\S]*pywebview[\s\S]*\.api/);
});

test("frame action messages execute a whitelist locally and report through the bridge", () => {
  assert.match(source, /worktrace-fdwork-action-v5/);
  assert.match(source, /window\.addEventListener\("message"/);
  assert.match(source, /event\.source\s*!==\s*window\.top/);
  assert.match(source, /event\.origin\s*!==\s*window\.location\.origin/);
  assert.match(source, /submit_adapter_action_result/);
  assert.match(source, /awaitStableWorkShell[\s\S]*enterCasePicker[\s\S]*leaveCasePicker[\s\S]*readSelectedCase[\s\S]*fillEntry/);
});

test("frame message dispatch returns picker readiness without cross-frame evaluation", async () => {
  const { window, windowListeners, actionResults } = fieldHarness();
  const listener = windowListeners.get("message");
  assert.equal(typeof listener, "function");

  listener({
    source: window,
    origin: window.location.origin,
    data: {
      channel: "worktrace-fdwork-action-v5",
      version: 5,
      action_nonce: "action-nonce",
      action: "enterCasePicker",
      arguments: [{
        version: 5,
        operation_nonce: "operation-nonce",
        operation_generation: 2,
        fields: { case_number: { selector: "#missing" } },
      }],
    },
  });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(actionResults.length, 1);
  assert.equal(actionResults[0].nonce, "action-nonce");
  assert.equal(actionResults[0].action, "enterCasePicker");
  assert.equal(actionResults[0].result.ok, true);
  assert.equal(actionResults[0].result.status, "picker_ready");
});

test("adapter message listener is idempotent and removed on pagehide", () => {
  const { context, windowListeners } = fieldHarness();
  const originalMessageListener = windowListeners.get("message");
  vm.runInContext(source, context, { filename: "fd_work_adapter.js" });
  assert.equal(windowListeners.get("message"), originalMessageListener);

  const pagehide = windowListeners.get("pagehide");
  pagehide();
  assert.equal(windowListeners.has("message"), false);
});

test("date duration and narrative use native setters and verify readback", () => {
  const { adapter, fields, Input, Textarea } = fieldHarness();
  const date = new Input();
  const duration = new Input();
  const narrative = new Textarea();
  fields.set("#date", date);
  fields.set("#duration", duration);
  fields.set("#narrative", narrative);
  const contract = { fields: {
    work_date: { selector: "#date" },
    duration_hours: { selector: "#duration" },
    narrative: { selector: "#narrative" },
  } };

  assert.equal(adapter.fillWorkDate("2026-08-03", contract).ok, true);
  assert.equal(adapter.fillDuration("1.5", contract).ok, true);
  assert.equal(adapter.fillNarrative("Narrative", contract).ok, true);
  assert.deepEqual(date.events, ["input", "change", "blur"]);
  assert.deepEqual(duration.events, ["input", "change", "blur"]);
  assert.deepEqual(narrative.events, ["input", "change", "blur"]);
});

test("adapter never submits saves reads credentials or calls an FD Work API", () => {
  assert.doesNotMatch(source, /\bfetch\s*\(|XMLHttpRequest|axios/i);
  assert.doesNotMatch(source, /cookie|localStorage|sessionStorage/i);
  assert.doesNotMatch(source, /querySelector\([^)]*(?:password|token)/i);
  assert.doesNotMatch(source, /\.click\(\).*['"](?:保存|提交)['"]/s);
  assert.doesNotMatch(source, /(?:submit|requestSubmit)\s*\(/);
});

test("fill owns one case preparation and always removes its blocking layer", () => {
  const body = source.slice(
    source.indexOf("async function fillEntry"),
    source.lastIndexOf("window.WorkTraceFDWorkAdapter =")
  );
  assert.equal((body.match(/prepareCaseCombobox\s*\(/g) || []).length, 1);
  assert.match(body, /installFillBlockingLayer/);
  assert.match(body, /finally[\s\S]*removeFillBlockingLayer/);
  assert.doesNotMatch(body, /KeyboardEvent\([^)]*Escape/);
  assert.doesNotMatch(body, /prepared\.input\.blur|caseInput\([^)]*\)\.blur/);
});

test("picker does not focus click write clear escape or blur the native case input", () => {
  const body = source.slice(
    source.indexOf("function enterCasePicker"),
    source.indexOf("function nativeSet")
  );
  assert.doesNotMatch(body, /\.focus\s*\(|\.click\s*\(|setSearchValue|nativeSet/);
  assert.doesNotMatch(body, /KeyboardEvent|\.blur\s*\(/);
});

test("stable shell check only observes visibility viewport overlay and stable frames", () => {
  const body = source.slice(
    source.indexOf("async function awaitStableWorkShell"),
    source.indexOf("function clearPickerObserver")
  );
  assert.match(body, /document\.visibilityState/);
  assert.match(body, /window\.innerWidth/);
  assert.match(body, /blockingOverlayVisible/);
  assert.match(body, /sameRect\(first, second\)/);
  assert.doesNotMatch(body, /\.focus\s*\(|\.click\s*\(|nativeSet|setSearchValue|KeyboardEvent|\.blur\s*\(/);
});

test("pagehide invalidates generations and removes transient picker/fill state", () => {
  const body = source.slice(source.indexOf('window.addEventListener("pagehide"'));
  assert.match(body, /activeGeneration \+= 1/);
  assert.match(body, /clearPickerObserver/);
  assert.match(body, /removeFillBlockingLayer/);
  assert.match(body, /activeMode = "none"/);
});

test("picker keeps the native form intact and owns one idempotent style node", () => {
  assert.doesNotMatch(source, /data-worktrace-fdwork-hidden|data-worktrace-fdwork-compact/);
  assert.doesNotMatch(source, /querySelectorAll\(["']\.ant-form-item/);
  assert.doesNotMatch(source, /ignoredRequiredFieldsReady|installCompactMode/);
  assert.match(source, /worktrace-fdwork-style/);
  assert.match(source, /getElementById\(STYLE_ID\)/);
  assert.match(source, /positionPickerToolbar/);
  assert.match(source, /rectanglesOverlap/);
  assert.match(source, /#worktrace-fdwork-fill-blocker\{position:fixed;inset:0;/);
});

test("picker snapshots the old selection before observing new commit evidence", () => {
  const snapshot = source.indexOf("pickerInitialSelection = selectedCaseItem(input)");
  const observer = source.indexOf("observePickerSelectionDom(contract)", snapshot);
  assert.ok(snapshot >= 0 && observer > snapshot);
  assert.doesNotMatch(source, /pickerSelectionRevision\s*=\s*selected\.ok/);
  assert.match(source, /pickerSelectionRevision\s*>\s*0\s*&&\s*selected\.ok/);
  assert.match(source, /attributeName\s*!==\s*["']aria-selected["']/);
  assert.match(
    source,
    /document\.addEventListener\("click",\s*pickerDocumentClickListener,\s*true\)/,
    "Ant may stop option-click bubbling, so proof capture must run in capture phase"
  );
});
