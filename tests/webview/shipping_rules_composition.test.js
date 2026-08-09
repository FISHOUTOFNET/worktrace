const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const uiRoot = path.join(__dirname, "../../worktrace/webview_ui");
const indexSource = fs.readFileSync(path.join(uiRoot, "index_fd_work_v5.html"), "utf8");
const shippingOrder = Array.from(indexSource.matchAll(/<script\s+src="js\/([^"?]+\.js)(?:\?v=[^"]+)?"/g), (match) => match[1]);
const ruleComposition = new Set([
  "core.js",
  "ui_components.js",
  "rules.js",
  "rules_render.js",
  "rules_create_panel_v5.js",
  "rules_rule_actions.js",
  "rules_keyword_actions.js",
  "rules_folder_actions.js",
]);

class FakeElement {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.value = "";
    this.name = "";
    this.type = "";
    this.parentNode = null;
    this.parentElement = null;
    this.children = [];
    this.listeners = new Map();
    this.attributes = new Map();
    this._classNames = new Set();
    this._textContent = "";
    this._innerHTML = "";
    this.offsetParent = {};
    this.style = {};
    this.dataset = {};
    this.classList = {
      add: (...names) => names.forEach((name) => this._classNames.add(name)),
      remove: (...names) => names.forEach((name) => this._classNames.delete(name)),
      contains: (name) => this._classNames.has(name),
      toggle: (name, force) => {
        if (force === true) this._classNames.add(name);
        else if (force === false) this._classNames.delete(name);
        else if (this._classNames.has(name)) this._classNames.delete(name);
        else this._classNames.add(name);
      },
    };
  }

  get className() { return Array.from(this._classNames).join(" "); }
  set className(value) { this._classNames = new Set(String(value || "").split(/\s+/).filter(Boolean)); }
  get textContent() {
    return this._textContent || this.children.map((child) => child.textContent).join("");
  }
  set textContent(value) { this._textContent = String(value || ""); this.children = []; }
  get innerHTML() { return this._innerHTML; }
  set innerHTML(value) { this._innerHTML = String(value || ""); this.children = []; this._textContent = ""; }
  getClientRects() { return [{ width: 10, height: 10 }]; }
  focus() { fakeDocument.activeElement = this; }
  appendChild(child) {
    child.parentNode = this;
    child.parentElement = this;
    this.children.push(child);
    return child;
  }
  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "class") this.className = value;
    if (name === "name") this.name = String(value);
  }
  getAttribute(name) {
    if (name === "class") return this.className || null;
    if (name === "name") return this.name || null;
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }
  removeAttribute(name) { this.attributes.delete(name); }
  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }
  dispatch(type, event = {}) {
    const handlers = this.listeners.get(type) || [];
    const payload = {
      target: this,
      preventDefault() {},
      stopPropagation() {},
      stopImmediatePropagation() {},
      ...event,
    };
    for (const handler of handlers) handler(payload);
  }
  matches(selector) {
    if (selector === "button") return this.tagName === "BUTTON";
    if (selector.startsWith(".")) return this.classList.contains(selector.slice(1));
    if (selector === 'input[name="confirm-dialog-choice"]') {
      return this.tagName === "INPUT" && this.name === "confirm-dialog-choice";
    }
    if (selector === '[role="radiogroup"]') return this.getAttribute("role") === "radiogroup";
    return false;
  }
  closest(selector) {
    let node = this;
    while (node) {
      if (node.matches && node.matches(selector)) return node;
      node = node.parentElement;
    }
    return null;
  }
  querySelectorAll(selector) {
    const found = [];
    const visit = (node) => {
      for (const child of node.children) {
        if (child.matches(selector)) found.push(child);
        visit(child);
      }
    };
    visit(this);
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const elements = new Map();
const buttonsByKind = { keyword: [], folder: [] };
function element(id) {
  if (!elements.has(id)) elements.set(id, new FakeElement("div", id));
  return elements.get(id);
}

const fakeDocument = {
  activeElement: null,
  body: new FakeElement("body", "body"),
  documentElement: { contains() { return true; } },
  listeners: new Map(),
  getElementById: element,
  createElement(tag) { return new FakeElement(tag); },
  addEventListener(type, handler) { this.listeners.set(type, handler); },
  querySelector() { return null; },
  querySelectorAll(selector) {
    if (selector === ".rules-keyword-delete-button") return buttonsByKind.keyword;
    if (selector === ".rules-folder-delete-button") return buttonsByKind.folder;
    return [];
  },
};
fakeDocument.body.contains = () => true;

const dialog = element("confirm-dialog");
const dialogBody = element("confirm-dialog-body");
const dialogPrimary = element("confirm-dialog-primary");
const dialogSecondary = element("confirm-dialog-secondary");
dialog.appendChild(dialogBody);
dialog.appendChild(dialogSecondary);
dialog.appendChild(dialogPrimary);
element("confirm-dialog-layer").appendChild(dialog);

const context = {
  Promise, Error, String, Number, Array, Date, Math, JSON, RegExp, Object,
  parseInt, setTimeout, clearTimeout,
  window: { WorkTraceApp: {} },
  document: fakeDocument,
};
vm.createContext(context);
for (const filename of shippingOrder.filter((name) => ruleComposition.has(name))) {
  vm.runInContext(
    fs.readFileSync(path.join(uiRoot, "js", filename), "utf8"),
    context,
    { filename },
  );
}

const App = context.window.WorkTraceApp;
App.refreshRulesPanelTargets = () => {};
App.requestCoordinator = { beginLatest() { return 1; }, isCurrent() { return true; } };
App.bridge = {};
App.loadProjectRules = () => Promise.resolve(true);

function materializeDeleteButton(kind, html) {
  const classMatch = html.match(new RegExp(`class="([^"]*rules-${kind}-delete-button[^"]*)"`));
  const idMatch = html.match(new RegExp(`data-rule-kind="${kind}" data-rule-id="(\\d+)"`));
  assert.ok(classMatch && idMatch, `rendered ${kind} delete button must exist`);
  const button = new FakeElement("button");
  button.className = classMatch[1];
  button.setAttribute("data-rule-kind", kind);
  button.setAttribute("data-rule-id", idMatch[1]);
  buttonsByKind[kind] = [button];
  return button;
}

function renderedRules() {
  App.showProjectRules({
    projects: [{
      id: 1,
      name: "Test project",
      description: "",
      last_used_at: "",
      rules: [
        { id: 7, kind: "keyword", kind_label: "关键词", target: "worktrace", enabled: true, detail: "已启用" },
        { id: 8, kind: "folder", kind_label: "文件夹", target: "C:/safe-fixture", enabled: false, recursive: true, detail: "包含子文件夹 | 已禁用" },
      ],
    }],
  });
  return element("rules-list").innerHTML;
}

function choose(mode) {
  const input = dialogBody.querySelectorAll('input[name="confirm-dialog-choice"]')
    .find((candidate) => candidate.value === mode);
  assert.ok(input, `dialog choice ${mode} must exist`);
  for (const candidate of dialogBody.querySelectorAll('input[name="confirm-dialog-choice"]')) {
    candidate.checked = candidate === input;
  }
  input.dispatch("change");
}

function flush() { return new Promise((resolve) => setImmediate(resolve)); }

test("shipping composition renders no enabled state and keyword delete opens both choices", async () => {
  const html = renderedRules();
  assert.match(html, />worktrace</);
  assert.doesNotMatch(html, /已启用|已禁用/);
  const button = materializeDeleteButton("keyword", html);
  element("rules-list").dispatch("click", { target: button });

  const group = dialogBody.querySelector('[role="radiogroup"]');
  assert.ok(group);
  const labels = group.children.map((row) => row.children[1].children[0].textContent);
  assert.deepEqual(labels, ["保留已有归类", "恢复原状"]);
  assert.doesNotMatch(dialogBody.textContent, /规则删除后不再参与后续自动归类；既有历史归属保持不变/);
  dialogSecondary.dispatch("click");
  await flush();
});

test("shipping composition dispatches explicit restore and preserve history modes", async () => {
  const calls = [];
  App.bridge.deleteProjectKeywordRule = (ruleId, applyToHistory) => {
    calls.push([ruleId, applyToHistory]);
    return Promise.resolve({ ok: true });
  };
  let html = renderedRules();
  let button = materializeDeleteButton("keyword", html);
  element("rules-list").dispatch("click", { target: button });
  choose("restore");
  dialogPrimary.dispatch("click");
  await flush();
  await flush();

  html = renderedRules();
  button = materializeDeleteButton("keyword", html);
  element("rules-list").dispatch("click", { target: button });
  choose("preserve");
  dialogPrimary.dispatch("click");
  await flush();
  await flush();

  assert.deepEqual(calls, [[7, true], [7, false]]);
});
