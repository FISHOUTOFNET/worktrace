(function () {
    "use strict";

    var VERSION = 5;
    var CHANNEL = "worktrace-fdwork-action-v5";
    var TOOLBAR_ID = "worktrace-fdwork-picker-toolbar";
    var BLOCKER_ID = "worktrace-fdwork-picker-blocker";
    var FILL_BLOCKER_ID = "worktrace-fdwork-fill-blocker";
    var STYLE_ID = "worktrace-fdwork-picker-session-style";
    var session = null;
    var bindings = [];
    var blockerBindings = [];
    var submissionInput = null;
    var submissionInputWasDisabled = false;

    function result(ok, error, extra) {
        return Object.assign({ ok: !!ok, error: error || "" }, extra || {});
    }

    function text(value) {
        return String(value == null ? "" : value)
            .replace(/[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]/g, " ")
            .trim();
    }

    function visible(node) {
        if (!node) return false;
        var style = window.getComputedStyle ? window.getComputedStyle(node) : null;
        if (style && (style.display === "none" || style.visibility === "hidden")) return false;
        return typeof node.getClientRects !== "function" || node.getClientRects().length > 0;
    }

    function caseField(contract) {
        return contract && (contract.field || (contract.entry_fields && contract.entry_fields.case_number));
    }

    function caseInput(contract) {
        var field = caseField(contract);
        return field && field.selector && document.querySelector ? document.querySelector(field.selector) : null;
    }

    function wrapperFor(input) {
        if (!input) return null;
        return typeof input.closest === "function" ? (input.closest(".ant-select") || input.parentElement) : input.parentElement;
    }

    function popupFor(input, contract) {
        if (!input) return null;
        var controls = text(input.getAttribute && (input.getAttribute("aria-controls") || input.getAttribute("aria-owns")));
        if (controls && document.getElementById) {
            var ids = controls.split(/\s+/).filter(Boolean);
            for (var i = 0; i < ids.length; i += 1) {
                var controlled = document.getElementById(ids[i]);
                if (controlled) return typeof controlled.closest === "function"
                    ? (controlled.closest(".ant-select-dropdown") || controlled) : controlled;
            }
        }
        var field = caseField(contract);
        return field && field.listbox && document.querySelector ? document.querySelector(field.listbox) : null;
    }

    function selectedCase(contract) {
        var input = caseInput(contract);
        if (!input || !visible(input)) return result(false, "case_input_missing");
        var wrapper = wrapperFor(input);
        var item = wrapper && wrapper.querySelector ? wrapper.querySelector(
            ".ant-select-selection-item[title], .ant-select-selection-item, [data-selected-value]"
        ) : null;
        if (!item || !visible(item)) return result(false, "case_selection_required");
        var label = text((item.getAttribute && (item.getAttribute("title") || item.getAttribute("data-selected-value"))) || item.textContent);
        var maxLength = Math.max(1, Number(contract && contract.max_label_length) || 100);
        if (!label || label.length > maxLength) return result(false, "dom_contract_changed");
        var popup = popupFor(input, contract);
        if (popup && popup.querySelectorAll) {
            var committed = Array.prototype.filter.call(
                popup.querySelectorAll("[role='option'][aria-selected='true']"), visible
            ).map(function (option) {
                return text((option.getAttribute && option.getAttribute("title")) || option.innerText || option.textContent);
            }).filter(Boolean);
            if (committed.length && committed.indexOf(label) < 0) return result(false, "case_selection_mismatch");
        }
        return result(true, "", { label: label });
    }

    function optionNode(target) {
        if (!target) return null;
        if ((target.getAttribute && target.getAttribute("role") === "option")
            || (target.classList && target.classList.contains("ant-select-item-option"))) return target;
        return typeof target.closest === "function" ? target.closest(".ant-select-item-option, [role='option']") : null;
    }

    function optionBelongsToCase(option, contract) {
        var input = caseInput(contract);
        if (!input || !option) return false;
        var controls = text(input.getAttribute && (input.getAttribute("aria-controls") || input.getAttribute("aria-owns")));
        var listbox = typeof option.closest === "function" ? option.closest("[role='listbox']") : null;
        if (controls && listbox && controls.split(/\s+/).indexOf(String(listbox.id || "")) >= 0) return true;
        var popup = popupFor(input, contract);
        return !!(popup && popup.contains && popup.contains(option));
    }

    function optionLabel(option) {
        return text(option && ((option.getAttribute && option.getAttribute("title")) || option.innerText || option.textContent));
    }

    function frame() {
        return new Promise(function (resolve) {
            (typeof requestAnimationFrame === "function" ? requestAnimationFrame : function (cb) { setTimeout(cb, 16); })(resolve);
        });
    }

    function helperApi() {
        var owner = window;
        try { if (window.top && window.top.pywebview) owner = window.top; } catch (_error) {}
        return owner.pywebview && owner.pywebview.api ? owner.pywebview.api : null;
    }

    function ensureStyle() {
        if (document.getElementById && document.getElementById(STYLE_ID)) return;
        var style = document.createElement("style");
        style.id = STYLE_ID;
        style.textContent = "#" + TOOLBAR_ID + "{position:fixed;right:24px;bottom:24px;z-index:2147483647;display:flex;align-items:center;gap:12px;max-width:calc(100vw - 48px);padding:12px 16px;border:1px solid #d9d9d9;border-radius:8px;background:#fff;box-shadow:0 6px 20px rgba(0,0,0,.18);font:14px/1.5 sans-serif}#" + TOOLBAR_ID + " button{min-width:72px;padding:4px 12px}#" + BLOCKER_ID + "{position:fixed;inset:0;z-index:2147483646;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.84);font:16px/1.5 sans-serif}";
        var owner = document.head || document.documentElement;
        if (owner && owner.appendChild) owner.appendChild(style);
    }

    function toolbar() { return document.getElementById && document.getElementById(TOOLBAR_ID); }

    function currentCandidateValid() {
        if (!session || !session.candidate) return false;
        var selected = selectedCase(session.contract);
        return selected.ok && selected.label === session.candidate.label;
    }

    function renderToolbar() {
        var bar = toolbar();
        if (!bar || !session) return;
        var valid = currentCandidateValid();
        if (session.candidate && !valid && session.state !== "submitting") {
            session.candidate = null;
            session.state = "waiting";
        }
        var status = bar._status;
        var confirm = bar._confirm;
        var cancel = bar._cancel;
        if (session.state === "submitting") {
            status.textContent = session.submitKind === "cancel" ? "正在取消案件选择…" : "正在确认案件…";
            confirm.disabled = true;
            cancel.disabled = true;
        } else if (session.candidate) {
            status.textContent = "已选择：" + session.candidate.label;
            confirm.disabled = !currentCandidateValid();
            cancel.disabled = false;
        } else {
            status.textContent = "请在 FD Work 中选择案件";
            confirm.disabled = true;
            cancel.disabled = false;
        }
    }

    function removeBlocker() {
        blockerBindings.forEach(function (binding) {
            if (document.removeEventListener) document.removeEventListener(binding[0], binding[1], true);
        });
        blockerBindings = [];
        var blocker = document.getElementById && document.getElementById(BLOCKER_ID);
        if (blocker && blocker.remove) blocker.remove();
        if (submissionInput && submissionInput.isConnected !== false) {
            submissionInput.disabled = submissionInputWasDisabled;
        }
        submissionInput = null;
        submissionInputWasDisabled = false;
    }

    function installBlocker(message) {
        ensureStyle();
        removeBlocker();
        var blocker = document.createElement("div");
        blocker.id = BLOCKER_ID;
        blocker.setAttribute("role", "status");
        blocker.setAttribute("aria-live", "polite");
        blocker.textContent = message;
        if (document.body && document.body.appendChild) document.body.appendChild(blocker);
        function block(event) {
            var bar = toolbar();
            if (bar && bar.contains && bar.contains(event.target)) return;
            if (event.preventDefault) event.preventDefault();
            if (event.stopImmediatePropagation) event.stopImmediatePropagation();
            else if (event.stopPropagation) event.stopPropagation();
        }
        ["pointerdown", "mousedown", "click", "keydown", "submit"].forEach(function (name) {
            if (document.addEventListener) {
                document.addEventListener(name, block, true);
                blockerBindings.push([name, block]);
            }
        });
        submissionInput = session ? caseInput(session.contract) : null;
        submissionInputWasDisabled = !!(submissionInput && submissionInput.disabled);
        if (submissionInput) submissionInput.disabled = true;
    }

    async function reconcile(expectedLabel, sequence, generation, allowInitial) {
        var deadline = Date.now() + 1500;
        while (Date.now() <= deadline) {
            if (!session || session.generation !== generation || session.sequence !== sequence || session.state === "submitting") return;
            var selected = selectedCase(session.contract);
            if (selected.ok && (!expectedLabel || selected.label === expectedLabel)) {
                if (!allowInitial && session.initialLabel && selected.label === session.initialLabel) return;
                session.revision += 1;
                session.candidate = { label: selected.label, revision: session.revision, sequence: sequence };
                session.state = "candidate";
                renderToolbar();
                return;
            }
            await frame();
        }
        renderToolbar();
    }

    function startMouseCommit(label) {
        if (!session || !label || session.state === "submitting") return;
        if (session.candidate && session.candidate.label === label && currentCandidateValid()) return;
        var sequence = ++session.sequence;
        void reconcile(label, sequence, session.generation, true);
    }

    function startKeyboardCommit() {
        if (!session || session.state === "submitting") return;
        var input = caseInput(session.contract);
        var expanded = input && input.getAttribute && input.getAttribute("aria-expanded") === "true";
        if (!expanded && !popupFor(input, session.contract)) return;
        var sequence = ++session.sequence;
        void reconcile("", sequence, session.generation, false);
    }

    function bindDocument(name, handler) {
        if (document.addEventListener) {
            document.addEventListener(name, handler, true);
            bindings.push([name, handler]);
        }
    }

    function bindSessionEvents() {
        bindDocument("click", function (event) {
            if (!session || session.state === "submitting") return;
            var option = optionNode(event && event.target);
            if (option && visible(option) && optionBelongsToCase(option, session.contract)) {
                var label = optionLabel(option);
                if (label) startMouseCommit(label);
                return;
            }
            Promise.resolve().then(renderToolbar);
        });
        bindDocument("keydown", function (event) {
            if (!session || session.state === "submitting") return;
            if (event && event.key === "Enter" && event.target === caseInput(session.contract)) startKeyboardCommit();
        });
        ["input", "change"].forEach(function (name) {
            bindDocument(name, function (event) {
                if (!session || event.target !== caseInput(session.contract)) return;
                Promise.resolve().then(renderToolbar);
            });
        });
    }

    function unbindSessionEvents() {
        bindings.forEach(function (binding) {
            if (document.removeEventListener) document.removeEventListener(binding[0], binding[1], true);
        });
        bindings = [];
    }

    function submit(kind) {
        if (!session || session.state === "submitting") return;
        var api = helperApi();
        if (!api) return;
        var candidate = session.candidate;
        if (kind === "confirm") {
            if (!candidate || !currentCandidateValid() || typeof api.submit_case_picker_confirmation !== "function") {
                renderToolbar();
                return;
            }
        } else if (typeof api.submit_case_picker_cancellation !== "function") return;
        session.state = "submitting";
        session.submitKind = kind;
        installBlocker(kind === "confirm" ? "正在确认案件…" : "正在取消案件选择…");
        renderToolbar();
        var call = kind === "confirm"
            ? api.submit_case_picker_confirmation(String(session.contract.operation_nonce || ""), candidate.label, candidate.revision)
            : api.submit_case_picker_cancellation(String(session.contract.operation_nonce || ""));
        Promise.resolve(call).then(function (response) {
            if (response && response.ok === true && response.accepted === true) return;
            if (!session) return;
            removeBlocker();
            session.state = currentCandidateValid() ? "candidate" : "waiting";
            session.submitKind = "";
            renderToolbar();
        }, function () {
            if (!session) return;
            removeBlocker();
            session.state = currentCandidateValid() ? "candidate" : "waiting";
            session.submitKind = "";
            renderToolbar();
        });
    }

    function makeToolbar() {
        ensureStyle();
        var existing = toolbar();
        if (existing) return existing;
        var bar = document.createElement("div");
        bar.id = TOOLBAR_ID;
        bar.setAttribute("role", "toolbar");
        var status = document.createElement("span");
        var confirm = document.createElement("button");
        var cancel = document.createElement("button");
        confirm.type = cancel.type = "button";
        confirm.textContent = "确认选择";
        cancel.textContent = "取消";
        bar._status = status; bar._confirm = confirm; bar._cancel = cancel;
        bar.appendChild(status); bar.appendChild(confirm); bar.appendChild(cancel);
        confirm.addEventListener("click", function () { submit("confirm"); });
        cancel.addEventListener("click", function () { submit("cancel"); });
        if (document.body && document.body.appendChild) document.body.appendChild(bar);
        return bar;
    }

    function enter(contract) {
        if (!contract || Number(contract.version) !== VERSION || !text(contract.operation_nonce)) return result(false, "dom_contract_changed");
        leave();
        var selected = selectedCase(contract);
        session = {
            contract: contract,
            generation: Number(contract.operation_generation) || Date.now(),
            state: "waiting",
            submitKind: "",
            sequence: 0,
            revision: 0,
            candidate: null,
            initialLabel: selected.ok ? selected.label : ""
        };
        makeToolbar();
        bindSessionEvents();
        var fillBlocker = document.getElementById && document.getElementById(FILL_BLOCKER_ID);
        if (fillBlocker && fillBlocker.remove) fillBlocker.remove();
        renderToolbar();
        return result(true, "", { status: "picker_ready" });
    }

    function leave() {
        unbindSessionEvents();
        removeBlocker();
        var bar = toolbar();
        if (bar && bar.remove) bar.remove();
        session = null;
        return result(true);
    }

    function safe(value) {
        if (!value || typeof value !== "object" || typeof value.ok !== "boolean") return { ok: false, error: "non_mapping_result" };
        var payload = { ok: value.ok };
        ["error", "status", "label"].forEach(function (key) { if (typeof value[key] === "string") payload[key] = value[key]; });
        return payload;
    }

    function report(command, value) {
        var api = helperApi();
        if (!api || typeof api.submit_adapter_action_result !== "function") return;
        Promise.resolve(api.submit_adapter_action_result(command.action_nonce, command.action, safe(value))).catch(function () {});
    }

    function onMessage(event) {
        if (!event || event.source !== window.top || event.origin !== window.location.origin) return;
        var command = event.data;
        if (!command || command.channel !== CHANNEL || Number(command.version) !== VERSION) return;
        if (["enterCasePicker", "leaveCasePicker", "readSelectedCase"].indexOf(command.action) < 0) return;
        if (event.stopImmediatePropagation) event.stopImmediatePropagation();
        var value;
        try {
            value = command.action === "enterCasePicker"
                ? enter(command.arguments && command.arguments[0])
                : command.action === "leaveCasePicker"
                ? leave()
                : selectedCase(command.arguments && command.arguments[0]);
        } catch (_error) {
            value = result(false, "javascript_exception");
        }
        report(command, value);
    }

    window.addEventListener("message", onMessage, true);
    window.addEventListener("pagehide", leave);
    window.WorkTraceFDWorkPickerSession = Object.freeze({
        version: VERSION,
        enterCasePicker: enter,
        leaveCasePicker: leave,
        readSelectedCase: selectedCase,
        _test: Object.freeze({
            state: function () { return session; },
            renderToolbar: renderToolbar,
            startMouseCommit: startMouseCommit,
            startKeyboardCommit: startKeyboardCommit
        })
    });
})();
