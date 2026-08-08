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

function exactCaseHarness({
  optionLabels,
  committedLabel,
  replaceOnPointerDown = false,
  replacePopupAfterQuery = true,
  hiddenAccessibilityDuplicate = false,
  antClassOnly = false,
  semanticClickNoop = false,
  virtualAntStructure = false,
} = {}) {
  class Input {
    constructor() { this._value = ""; }
    get value() { return this._value; }
    set value(value) { this._value = String(value); }
  }
  class Textarea extends Input {}
  let currentLabels = ["STALE RESULT"];
  let selectedLabel = "";
  let popupRevision = 0;
  let currentPopup = null;
  const queries = [];
  const clickedLabels = [];
  const staleClickLabels = [];
  const interactionEvents = [];
  const listeners = new Map();
  const selectionItem = {
    get textContent() { return selectedLabel; },
    getAttribute(name) { return name === "title" ? selectedLabel : null; },
    getClientRects() { return selectedLabel ? [{}] : []; },
  };
  const wrapper = {
    querySelector(selector) {
      return selector.includes("selection-item") && selectedLabel ? selectionItem : null;
    },
  };
  const input = new Input();
  Object.assign(input, {
    disabled: false,
    readOnly: false,
    getAttribute(name) {
      return name === "aria-controls" || name === "aria-owns" ? "case-list" : null;
    },
    getClientRects() { return [{}]; },
    closest(selector) { return selector === ".ant-select" ? wrapper : null; },
    dispatchEvent(event) {
      if (event.type === "input") {
        queries.push(this.value);
        currentLabels = optionLabels.slice();
        if (replacePopupAfterQuery) currentPopup = makePopup();
      }
      return true;
    },
  });
  function commit(label) {
    if (semanticClickNoop) return;
    clickedLabels.push(label);
    selectedLabel = committedLabel === undefined ? label : committedLabel;
  }
  function option(label, owner, {
    hidden = false,
    classOnly = antClassOnly,
    interactive = true,
  } = {}) {
    const node = {
      label,
      innerText: label,
      textContent: label,
      classList: {
        contains(name) { return name === "ant-select-item-option" && classOnly; },
      },
      getAttribute(name) {
        if (name === "title") return label;
        if (name === "role") return classOnly ? null : "option";
        if (name === "class") return classOnly ? "ant-select-item-option" : "";
        if (name === "aria-disabled") return "false";
        if (name === "aria-selected") return label === selectedLabel ? "true" : "false";
        return null;
      },
      get isConnected() { return currentPopup === owner; },
      getClientRects() { return hidden ? [] : [{}]; },
      dispatchEvent(event) {
        interactionEvents.push({ label, type: event.type, connected: this.isConnected });
        if (event.type === "pointerdown" && replaceOnPointerDown && this.isConnected) {
          currentPopup = makePopup();
        }
        if (event.type === "click" && interactive) {
          if (!this.isConnected) staleClickLabels.push(label);
          else commit(label);
        }
        return true;
      },
    };
    node.click = function () {
      interactionEvents.push({ label, type: "semantic-click", connected: node.isConnected });
      if (!node.isConnected) staleClickLabels.push(label);
      else if (interactive) commit(label);
    };
    return node;
  }
  function makePopup() {
    const popup = {
      revision: ++popupRevision,
      get isConnected() { return currentPopup === popup; },
      getClientRects() { return currentPopup === popup ? [{}] : []; },
      querySelectorAll(selector) {
        const options = currentLabels.map((label) => option(label, popup));
        if (virtualAntStructure) {
          const accessibilityOptions = currentLabels.map((label) => option(label, popup, {
            classOnly: false,
            interactive: false,
          }));
          if (selector.includes("aria-selected='true'")) {
            return accessibilityOptions.filter((item) => item.label === selectedLabel);
          }
          if (selector.includes("ant-select-item-option") && selector.includes("[role='option']")) {
            return accessibilityOptions.concat(options);
          }
          if (selector.includes("ant-select-item-option")) return options;
          if (selector.includes("[role='option']")) return accessibilityOptions;
          return [];
        }
        if (hiddenAccessibilityDuplicate && currentLabels.length) {
          options.unshift(option(currentLabels[0], popup, { hidden: true, classOnly: false }));
        }
        if (selector.includes("aria-selected='true'")) {
          return options.filter((item) => item.label === selectedLabel && item.getClientRects().length);
        }
        if (selector.includes("ant-select-item-option") && selector.includes("[role='option']")) {
          return options;
        }
        if (selector.includes("ant-select-item-option")) {
          return options.filter((item) => item.classList.contains("ant-select-item-option"));
        }
        if (selector.includes("[role='option']")) {
          return options.filter((item) => item.getAttribute("role") === "option");
        }
        return [];
      },
    };
    if (virtualAntStructure) {
      popup.controlledListbox = {
        getClientRects() { return [{}]; },
        closest(selector) { return selector === ".ant-select-dropdown" ? popup : null; },
        querySelectorAll(selector) {
          const accessibilityOptions = currentLabels.map((label) => option(label, popup, {
            classOnly: false,
            interactive: false,
          }));
          return selector.includes("[role='option']") ? accessibilityOptions : [];
        },
      };
    }
    return popup;
  }
  currentPopup = makePopup();
  const context = {
    Promise, Object, String, Array,
    Event: class Event { constructor(type) { this.type = type; } },
    MouseEvent: class MouseEvent { constructor(type) { this.type = type; } },
    PointerEvent: class PointerEvent { constructor(type) { this.type = type; } },
    HTMLInputElement: Input,
    HTMLTextAreaElement: Textarea,
    MutationObserver: class { observe() {} disconnect() {} },
    setTimeout, clearTimeout,
    requestAnimationFrame(callback) { return setTimeout(callback, 0); },
    document: {
      visibilityState: "visible",
      documentElement: { setAttribute() {}, removeAttribute() {} },
      body: { firstElementChild: {}, appendChild() {}, insertBefore() {} },
      querySelector(selector) { return selector === "#case" ? input : null; },
      querySelectorAll() { return []; },
      getElementById(id) {
        if (id !== "case-list") return null;
        return virtualAntStructure ? currentPopup.controlledListbox : currentPopup;
      },
      createElement() { return { setAttribute() {}, appendChild() {}, addEventListener() {} }; },
    },
    window: {
      innerWidth: 980,
      innerHeight: 760,
      location: {
        href: "https://work.fangdalaw.com/Works/WorkHourList?picker=day",
        origin: "https://work.fangdalaw.com",
      },
      getComputedStyle() { return { display: "block", visibility: "visible" }; },
      addEventListener(name, callback) { listeners.set(name, callback); },
      removeEventListener() {},
    },
  };
  context.window.top = context.window;
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "fd_work_adapter.js" });
  return {
    adapter: context.window.WorkTraceFDWorkAdapter,
    contract: {
      version: 5,
      operation_generation: 0,
      operation_deadline_ms: Date.now() + 80,
      max_label_length: 100,
      field: { selector: "#case", listbox: "#case-list" },
      entry_fields: { case_number: { selector: "#case", listbox: "#case-list" } },
    },
    queries,
    clickedLabels,
    staleClickLabels,
    interactionEvents,
    popupRevision() { return popupRevision; },
  };
}

test("adapter contract v5 exposes picker and fill modes without inline search handshake", () => {
  const { adapter } = fieldHarness();
  assert.equal(adapter.version, 5);
  for (const method of [
    "awaitStableWorkPage", "ensureEntryEditor", "awaitStableEntryEditor",
    "enterCasePicker", "leaveCasePicker", "readSelectedCase", "fillEntry"
  ]) {
    assert.equal(typeof adapter[method], "function");
  }
  assert.equal(adapter.searchCases, undefined);
  assert.equal(adapter.interactiveHandshake, undefined);
});

test("work page readiness is independent from entry editor readiness", () => {
  const workStart = source.indexOf("async function awaitStableWorkPage");
  const stableEditorStart = source.indexOf("async function awaitStableEntryEditor", workStart);
  const editorStart = source.indexOf("async function ensureEntryEditor", stableEditorStart);
  assert.ok(workStart >= 0 && stableEditorStart > workStart && editorStart > stableEditorStart);
  const workBody = source.slice(workStart, source.indexOf("function entryEditorState", workStart));
  assert.doesNotMatch(workBody, /form#basic|basic_caseId/);
  const editorBody = source.slice(editorStart, source.indexOf("async function awaitStableWorkShell", editorStart));
  assert.match(editorBody, /创建工时/);
  assert.match(editorBody, /awaitStableEntryEditor/);
  const stableEditorBody = source.slice(stableEditorStart, editorStart);
  assert.match(stableEditorBody, /requestFrame/);
  assert.match(editorBody, /entry_create_action_missing/);
  assert.match(editorBody, /entry_create_action_ambiguous/);
  assert.match(editorBody, /entry_create_action_disabled/);
  assert.match(editorBody, /entry_editor_not_rendered/);
});

test("picker commit reconciles on RAF and installs a cleaned interaction blocker", () => {
  assert.match(source, /async function reconcilePickerCommit/);
  assert.match(source, /expectedLabel/);
  assert.match(source, /await requestFrame\(\)/);
  assert.match(source, /installPickerInteractionBlocker/);
  assert.match(source, /removePickerInteractionBlocker/);
  const leaveStart = source.indexOf("function leaveCasePicker");
  const nativeSetStart = source.indexOf("function nativeSet", leaveStart);
  assert.match(source.slice(leaveStart, nativeSetStart), /removePickerInteractionBlocker/);
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

test("date is a page-context state transition and never a native-set form field", () => {
  const start = source.indexOf("function readEntryDate");
  const end = source.indexOf("async function prepareCaseCombobox", start);
  const body = source.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.match(body, /readEntryDate/);
  assert.match(body, /previous_button_icon/);
  assert.match(body, /next_button_icon/);
  assert.match(body, /date_change_failed/);
  assert.match(body, /date_verification_failed/);
  assert.doesNotMatch(body, /nativeSet|\.value\s*=(?!=)/);
});

test("duration and narrative have separate controlled-component reconciliation paths", () => {
  const durationStart = source.indexOf("async function fillDuration");
  const narrativeStart = source.indexOf("async function fillNarrative", durationStart);
  const verifyStart = source.indexOf("async function verifyEntry", narrativeStart);
  const durationBody = source.slice(durationStart, narrativeStart);
  const narrativeBody = source.slice(narrativeStart, verifyStart);
  assert.ok(durationStart >= 0 && narrativeStart > durationStart && verifyStart > narrativeStart);
  assert.match(durationBody, /duration_verification_failed/);
  assert.match(narrativeBody, /narrative_verification_failed/);
  assert.match(durationBody, /nativeSet/);
  assert.match(narrativeBody, /nativeSet/);
  assert.doesNotMatch(source, /function fillAndVerify/);
});

test("adapter never reads credentials or calls an FD Work private API", () => {
  assert.doesNotMatch(source, /\bfetch\s*\(|XMLHttpRequest|axios/i);
  assert.doesNotMatch(source, /cookie|localStorage|sessionStorage/i);
  assert.doesNotMatch(source, /querySelector\([^)]*(?:password|token)/i);
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

test("fill golden path is linear date then rerender-safe case and controlled fields", () => {
  const start = source.indexOf("async function fillEntry");
  const end = source.indexOf("function actionHandler", start);
  const body = source.slice(start, end);
  const stable = body.indexOf("awaitStableEntryEditor");
  const date = body.indexOf("ensureEntryDate");
  const stableAgain = body.indexOf("awaitStableEntryEditor", stable + 1);
  const caseControl = body.indexOf("prepareCaseCombobox");
  const exactCase = body.indexOf("selectExactCase");
  const duration = body.indexOf("fillDuration");
  const narrative = body.indexOf("fillNarrative");
  const verify = body.indexOf("verifyEntry");
  const save = body.indexOf("saveEntry");
  assert.ok(stable >= 0 && date > stable && stableAgain > date);
  assert.ok(caseControl > stableAgain && exactCase > caseControl);
  assert.ok(duration > exactCase && narrative > duration && verify > narrative && save > verify);
});

test("save action is scoped to form#basic and ignores matching buttons outside it", () => {
  const { adapter, fields } = fieldHarness();
  const inside = {
    textContent: "保存", disabled: false,
    getAttribute() { return null; },
    getClientRects() { return [{}]; },
  };
  const outside = {
    textContent: "保存", disabled: false,
    getAttribute() { return null; },
    getClientRects() { return [{}]; },
  };
  const form = {
    querySelectorAll() { return [inside]; },
    getClientRects() { return [{}]; },
  };
  fields.set("form#basic", form);
  fields.set("#outside-save", outside);

  const located = adapter._test.locateSaveAction({
    form_selector: "form#basic",
    save_action_label: "保存",
  });

  assert.equal(located.ok, true);
  assert.equal(located.node, inside);
});

test("save requires completion evidence, resets active mode, and can run twice", async () => {
  const { adapter, fields, context } = fieldHarness();
  let clicks = 0;
  let successVisible = false;
  const success = { textContent: "保存成功", getClientRects() { return [{}]; } };
  const button = {
    textContent: "保存", disabled: false, isConnected: true,
    getAttribute() { return null; },
    getClientRects() { return [{}]; },
    focus() {},
    dispatchEvent() { return true; },
    click() { clicks += 1; successVisible = true; },
  };
  const form = {
    isConnected: true,
    querySelectorAll() { return [button]; },
    getClientRects() { return [{}]; },
  };
  fields.set("form#basic", form);
  context.document.querySelectorAll = function (selector) {
    return successVisible && selector.includes("message-success") ? [success] : [];
  };
  const contract = {
    form_selector: "form#basic",
    save_action_label: "保存",
    save_success_selector: ".ant-message-success",
    operation_deadline_ms: Date.now() + 500,
  };

  const first = await adapter._test.saveEntry(contract, 0);
  successVisible = false;
  contract.operation_deadline_ms = Date.now() + 500;
  const second = await adapter._test.saveEntry(contract, 0);

  assert.equal(first.ok, true);
  assert.equal(second.ok, true);
  assert.equal(clicks, 2);
  assert.equal(adapter._test.activeMode(), "none");
});

test("fill success does not leave the adapter in review mode", () => {
  const start = source.indexOf("async function fillEntry");
  const end = source.indexOf("function actionHandler", start);
  const body = source.slice(start, end);
  assert.doesNotMatch(body, /activeMode\s*=\s*["']review["']/);
  assert.match(body, /finally[\s\S]*activeMode\s*=\s*["']none["']/);
});

test("automatic Ant Select path validates every dynamic popup stage", () => {
  const start = source.indexOf("async function prepareCaseCombobox");
  const end = source.indexOf("async function fillDuration", start);
  const body = source.slice(start, end);
  for (const stage of [
    "case_open", "case_query", "case_results", "case_commit", "case_verified",
  ]) assert.match(body, new RegExp(stage));
  assert.match(body, /aria-controls/);
  assert.match(body, /aria-owns/);
  assert.match(body, /dispatchPointerMouseSequence/);
  assert.match(body, /popupForInput/);
  assert.match(body, /readSelectedCase/);
  assert.doesNotMatch(body, /popup\s*=\s*popupForInput\([^)]*\)\s*\|\|\s*popup/);
});

test("case commit has a separate live-option resolver and never reuses the open-selector sequence", () => {
  const start = source.indexOf("function optionLabels");
  const end = source.indexOf("async function fillDuration", start);
  const body = source.slice(start, end);
  assert.match(body, /function findExactLiveCaseOption/);
  assert.match(body, /function commitExactCaseOption/);
  assert.match(body, /\.ant-select-item-option:not\(\.ant-select-item-option-disabled\)/);
  assert.match(body, /\[role=['"]option['"]\]:not\(\[aria-disabled=['"]true['"]\]\)/);
  assert.doesNotMatch(body, /dispatchPointerMouseSequence\(match,\s*null\)/);
});

test("canonical 26IP0111 query commits only the exact bound full label", async () => {
  const expectedLabel = "#26IP0111 长飞光纤IP问题分析";
  const h = exactCaseHarness({
    optionLabels: [expectedLabel, "#26IP0111 相似但不同的案件"],
  });

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0111",
    h.contract,
    0
  );

  assert.equal(selected.ok, true, JSON.stringify(selected));
  assert.equal(selected.stage, "case_verified");
  assert.deepEqual(h.queries, ["26IP0111"]);
  assert.deepEqual(h.clickedLabels, [expectedLabel]);
});

test("automatic case selection writes canonical query but matches the full label", async () => {
  const expectedLabel = "#26IP0165 IPDD_Miragene";
  const h = exactCaseHarness({ optionLabels: [expectedLabel] });

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0165",
    h.contract,
    0
  );

  assert.equal(selected.ok, true, JSON.stringify(selected));
  assert.deepEqual(h.queries, ["26IP0165"]);
  assert.notEqual(h.queries[0], expectedLabel);
  assert.deepEqual(h.clickedLabels, [expectedLabel]);
});

test("controlled option replacement after pointerdown cannot commit a detached stale node", async () => {
  const expectedLabel = "#26IP0111 长飞光纤IP问题分析";
  const h = exactCaseHarness({
    optionLabels: [expectedLabel],
    replaceOnPointerDown: true,
  });

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0111",
    h.contract,
    0
  );

  assert.equal(selected.ok, true, JSON.stringify(selected));
  assert.equal(selected.stage, "case_verified");
  assert.deepEqual(h.staleClickLabels, []);
  assert.deepEqual(h.clickedLabels, [expectedLabel]);
  assert.equal(selected.commit_method, "semantic_click");
  assert.equal(selected.commit_attempt_count, 1);
});

test("query-time popup replacement is re-resolved before exact commit", async () => {
  const expectedLabel = "#26IP0165 IPDD_Miragene";
  const h = exactCaseHarness({ optionLabels: [expectedLabel], replacePopupAfterQuery: true });
  const initialRevision = h.popupRevision();

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0165",
    h.contract,
    0
  );

  assert.equal(selected.ok, true, JSON.stringify(selected));
  assert.ok(h.popupRevision() > initialRevision);
  assert.equal(selected.popup_replaced, true);
  assert.equal(selected.live_option_reacquired, true);
});

test("virtual Ant Select commits the visible interactive option instead of the aria mirror", async () => {
  const expectedLabel = "#26IP0111 长飞光纤IP问题分析";
  const h = exactCaseHarness({
    optionLabels: [expectedLabel],
    antClassOnly: true,
    virtualAntStructure: true,
  });

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0111",
    h.contract,
    0
  );

  assert.equal(selected.ok, true, JSON.stringify(selected));
  assert.equal(selected.stage, "case_verified");
  assert.deepEqual(h.clickedLabels, [expectedLabel]);
});

test("hidden accessibility option is ignored in favor of one visible Ant option", async () => {
  const expectedLabel = "#26IP0165 IPDD_Miragene";
  const h = exactCaseHarness({
    optionLabels: [expectedLabel],
    hiddenAccessibilityDuplicate: true,
    antClassOnly: true,
  });

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0165",
    h.contract,
    0
  );

  assert.equal(selected.ok, true, JSON.stringify(selected));
  assert.equal(selected.option_count, 1);
  assert.deepEqual(h.clickedLabels, [expectedLabel]);
});

test("canonical query candidates are disambiguated by exact full label", async () => {
  const expectedLabel = "#26IP0165 IPDD_Miragene";
  const otherLabel = "#26IP0165 Another Matter";
  const h = exactCaseHarness({ optionLabels: [expectedLabel, otherLabel] });

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0165",
    h.contract,
    0
  );

  assert.equal(selected.ok, true, JSON.stringify(selected));
  assert.deepEqual(h.clickedLabels, [expectedLabel]);
});

test("duplicate exact full labels fail closed as ambiguous", async () => {
  const expectedLabel = "#26IP0165 IPDD_Miragene";
  const h = exactCaseHarness({ optionLabels: [expectedLabel, expectedLabel] });

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0165",
    h.contract,
    0
  );

  assert.equal(selected.ok, false);
  assert.equal(selected.error, "case_ambiguous");
  assert.deepEqual(h.clickedLabels, []);
});

test("similar canonical-query result never substitutes for expected full label", async () => {
  const h = exactCaseHarness({ optionLabels: ["#26IP0165 Another Matter"] });

  const selected = await h.adapter._test.selectExactCase(
    "#26IP0165 IPDD_Miragene",
    "26IP0165",
    h.contract,
    0
  );

  assert.equal(selected.ok, false);
  assert.equal(selected.error, "case_not_found");
  assert.deepEqual(h.clickedLabels, []);
});

test("post-click selected full-label mismatch fails closed", async () => {
  const expectedLabel = "#26IP0165 IPDD_Miragene";
  const h = exactCaseHarness({
    optionLabels: [expectedLabel],
    committedLabel: "#21IP0201 Other Matter",
  });

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0165",
    h.contract,
    0
  );

  assert.equal(selected.ok, false);
  assert.equal(selected.error, "case_selection_mismatch");
  assert.deepEqual(h.clickedLabels, [expectedLabel]);
});

test("semantic click no-op fails closed at case verification", async () => {
  const expectedLabel = "#26IP0165 IPDD_Miragene";
  const h = exactCaseHarness({
    optionLabels: [expectedLabel],
    semanticClickNoop: true,
  });

  const selected = await h.adapter._test.selectExactCase(
    expectedLabel,
    "26IP0165",
    h.contract,
    0
  );

  assert.equal(selected.ok, false);
  assert.equal(selected.stage, "case_verified");
  assert.equal(selected.error, "case_selection_mismatch");
  assert.equal(selected.commit_attempt_count, 1);
});

test("anonymous CASE A fixture remains supported when label and query are equal", async () => {
  const h = exactCaseHarness({ optionLabels: ["CASE A"] });

  const selected = await h.adapter._test.selectExactCase(
    "CASE A",
    "CASE A",
    h.contract,
    0
  );

  assert.equal(selected.ok, true, JSON.stringify(selected));
  assert.deepEqual(h.queries, ["CASE A"]);
  assert.deepEqual(h.clickedLabels, ["CASE A"]);
});

test("verifyEntry validates the selected full label and never the search query", () => {
  const start = source.indexOf("async function verifyEntry");
  const end = source.indexOf("async function fillEntry", start);
  const body = source.slice(start, end);
  assert.match(body, /payload\.case_label/);
  assert.doesNotMatch(body, /payload\.case_query/);
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
    source.indexOf("async function awaitStableEntryEditor"),
    source.indexOf("function createEntryActionText")
  );
  assert.match(body, /blockingOverlayVisible/);
  assert.match(body, /stableFrames/);
  assert.match(body, /entryEditorState/);
  assert.doesNotMatch(body, /\.focus\s*\(|\.click\s*\(|nativeSet|setSearchValue|KeyboardEvent|\.blur\s*\(/);
});

test("pagehide invalidates generations and removes transient picker/fill state", () => {
  const body = source.slice(source.indexOf('window.addEventListener("pagehide"'));
  assert.match(body, /activeGeneration \+= 1/);
  assert.match(body, /clearPickerObserver/);
  assert.match(body, /removeFillBlockingLayer/);
  assert.match(body, /activeMode = "none"/);
});

test("fill diagnostics are staged and privacy-safe", () => {
  for (const stage of [
    "page_stable", "date_read", "date_change", "date_verified",
    "case_open", "case_query", "case_results", "case_commit", "case_verified",
    "duration_write", "duration_verified", "narrative_write",
    "narrative_verified", "entry_verified", "save_action", "save_click", "save_completed",
  ]) assert.match(source, new RegExp(`['\"]${stage}['\"]`));
  assert.match(source, /internal_error_kind/);
  assert.match(source, /option_count/);
  for (const key of [
    "commit_method", "commit_attempt_count", "option_connected_before_action",
    "option_connected_after_action", "popup_replaced", "live_option_reacquired",
  ]) assert.match(source, new RegExp(key));
  assert.doesNotMatch(source, /diagnostic[^\n]*(?:case_number|narrative)/i);
});

test("case-commit diagnostics are restricted to non-sensitive structured values", () => {
  const start = source.indexOf("function safeActionResult");
  const end = source.indexOf("function reportActionResult", start);
  const body = source.slice(start, end);
  assert.match(body, /semantic_click/);
  assert.match(body, /commit_attempt_count/);
  assert.match(body, /option_connected_before_action/);
  assert.match(body, /option_connected_after_action/);
  assert.match(body, /popup_replaced/);
  assert.match(body, /live_option_reacquired/);
  assert.doesNotMatch(body, /case_label|case_query|narrative|innerText|textContent/);
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
