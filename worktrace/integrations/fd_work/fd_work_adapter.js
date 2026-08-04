(function () {
    "use strict";
    if (window.WorkTraceFDWorkAdapter && window.WorkTraceFDWorkAdapter.version === 5) return;

    var VERSION = 5;
    var PICKER_ROOT_ATTRIBUTE = "data-worktrace-fdwork-picker";
    var STYLE_ID = "worktrace-fdwork-style";
    var PICKER_TOOLBAR_ID = "worktrace-fdwork-picker-toolbar";
    var FILL_TOOLBAR_ID = "worktrace-fdwork-fill-toolbar";
    var FILL_BLOCKER_ID = "worktrace-fdwork-fill-blocker";
    var activeMode = "none";
    var activeGeneration = 0;
    var activePickerContract = null;
    var pickerObserver = null;
    var pickerSelectionRevision = 0;
    var pickerInitialSelection = null;
    var pickerInput = null;
    var pickerInputInitiallyDisabled = false;
    var pickerInputListener = null;
    var pickerDocumentClickListener = null;
    var pickerOptionClickSequence = 0;
    var pickerAcceptedClickSequence = 0;
    var lastPayload = null;
    var lastContract = null;

    function result(ok, error, extra) {
        return Object.assign({ ok: !!ok, error: error || "" }, extra || {});
    }

    function normalizeExactText(value) {
        return String(value == null ? "" : value)
            .replace(/[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]/g, " ")
            .trim();
    }

    function visible(element) {
        if (!element) return false;
        var style = window.getComputedStyle ? window.getComputedStyle(element) : null;
        if (style && (style.display === "none" || style.visibility === "hidden")) return false;
        return typeof element.getClientRects !== "function" || element.getClientRects().length > 0;
    }

    function field(contract, name) {
        var item = contract && contract.fields && contract.fields[name];
        return item && item.selector ? document.querySelector(item.selector) : null;
    }

    function caseInput(contract) {
        var item = contract && (contract.field || (contract.fields && contract.fields.case_number));
        return item && item.selector ? document.querySelector(item.selector) : null;
    }

    function selectWrapperFor(input) {
        if (!input) return null;
        if (typeof input.closest === "function") {
            return input.closest(".ant-select") || input.parentElement;
        }
        return input.parentElement;
    }

    function ensureStyle() {
        var existing = document.getElementById && document.getElementById(STYLE_ID);
        if (existing) return existing;
        var style = document.createElement("style");
        style.id = STYLE_ID;
        style.textContent = [
            "#worktrace-fdwork-picker-toolbar,#worktrace-fdwork-fill-toolbar{position:fixed;right:24px;bottom:24px;z-index:1000;display:flex;align-items:center;gap:12px;max-width:calc(100vw - 48px);padding:12px 16px;border:1px solid #d9d9d9;border-radius:8px;background:#fff;box-shadow:0 6px 20px rgba(0,0,0,.18);font:14px/1.5 sans-serif}",
            "#worktrace-fdwork-picker-toolbar button{min-width:72px;padding:4px 12px}",
            "#worktrace-fdwork-fill-blocker{position:fixed;inset:0;z-index:2147483646;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.82);font:16px/1.5 sans-serif}"
        ].join("");
        var owner = document.head || document.documentElement;
        if (owner && typeof owner.appendChild === "function") owner.appendChild(style);
        return style;
    }

    function popupForInput(input, contract) {
        if (!input) return null;
        var controls = normalizeExactText(input.getAttribute && input.getAttribute("aria-controls"));
        var configured = contract && (contract.field || (contract.fields && contract.fields.case_number));
        var configuredSelector = configured && configured.listbox;
        if (controls && document.getElementById) {
            var controlled = document.getElementById(controls);
            if (controlled) return controlled;
        }
        return configuredSelector ? document.querySelector(configuredSelector) : null;
    }

    function blockingOverlayVisible() {
        return Array.prototype.some.call(
            document.querySelectorAll ? document.querySelectorAll(
                ".ant-modal-mask, .ant-spin-spinning, [aria-busy='true'], [data-loading='true']"
            ) : [],
            visible
        );
    }

    function requestFrame() {
        return new Promise(function (resolve) {
            var callback = typeof requestAnimationFrame === "function"
                ? requestAnimationFrame
                : function (done) { setTimeout(done, 16); };
            callback(resolve);
        });
    }

    function deadlineAt(contract) {
        var existing = Number(contract && contract.operation_deadline_ms);
        if (existing > Date.now()) return existing;
        return Date.now() + Math.max(1, Number(contract && contract.deadline_ms) || 5000);
    }

    function canceled(generation) {
        return generation !== activeGeneration;
    }

    function sameRect(left, right) {
        if (!left || !right) return false;
        return ["left", "top", "width", "height"].every(function (key) {
            return Math.abs(Number(left[key] || 0) - Number(right[key] || 0)) < 0.5;
        });
    }

    async function awaitStableWorkShell(contract) {
        var generation = Number(contract && contract.operation_generation) || activeGeneration;
        if (activeMode === "none" && generation > activeGeneration) {
            activeGeneration = generation;
        }
        var deadline = deadlineAt(contract);
        while (Date.now() <= deadline) {
            if (canceled(generation)) return result(false, "lookup_superseded");
            var input = caseInput(contract);
            var visibilityReady = document.visibilityState === "visible";
            var viewportReady = Number(window.innerWidth) > 0 && Number(window.innerHeight) > 0;
            var interactive = !!(
                input && visible(input) && !input.disabled && !input.readOnly
                && !blockingOverlayVisible()
            );
            if (visibilityReady && viewportReady && interactive) {
                var first = input.getBoundingClientRect ? input.getBoundingClientRect() : null;
                await requestFrame();
                if (canceled(generation)) return result(false, "lookup_superseded");
                var second = input.getBoundingClientRect ? input.getBoundingClientRect() : null;
                await requestFrame();
                if (canceled(generation)) return result(false, "lookup_superseded");
                var third = input.getBoundingClientRect ? input.getBoundingClientRect() : null;
                if (sameRect(first, second) && sameRect(second, third)) {
                    return result(true, "", {
                        status: "stable",
                        document_visibility: document.visibilityState,
                        viewport_available: true,
                        input_exists: true,
                        input_interactive: true
                    });
                }
            }
            await new Promise(function (resolve) { setTimeout(resolve, 25); });
        }
        var finalInput = caseInput(contract);
        return result(false, finalInput ? "case_input_not_interactive" : "case_input_missing", {
            document_visibility: document.visibilityState,
            viewport_available: Number(window.innerWidth) > 0 && Number(window.innerHeight) > 0,
            input_exists: !!finalInput,
            input_interactive: !!(finalInput && !finalInput.disabled && !finalInput.readOnly)
        });
    }

    function clearPickerObserver() {
        if (pickerObserver) {
            pickerObserver.disconnect();
            pickerObserver = null;
        }
    }

    function clearPickerListeners() {
        if (pickerInput && pickerInputListener && typeof pickerInput.removeEventListener === "function") {
            pickerInput.removeEventListener("input", pickerInputListener);
            pickerInput.removeEventListener("change", pickerInputListener);
        }
        if (pickerDocumentClickListener && typeof document.removeEventListener === "function") {
            document.removeEventListener("click", pickerDocumentClickListener, true);
        }
        if (pickerInput) pickerInput.disabled = pickerInputInitiallyDisabled;
        pickerInput = null;
        pickerInputInitiallyDisabled = false;
        pickerInputListener = null;
        pickerDocumentClickListener = null;
        pickerOptionClickSequence = 0;
        pickerAcceptedClickSequence = 0;
        pickerInitialSelection = null;
    }

    function removeFillToolbar() {
        var toolbar = document.getElementById && document.getElementById(FILL_TOOLBAR_ID);
        if (toolbar && toolbar.remove) toolbar.remove();
        return result(true);
    }

    function selectedCaseItem(input) {
        var wrapper = selectWrapperFor(input);
        if (!wrapper || typeof wrapper.querySelector !== "function") return null;
        var item = wrapper.querySelector(
            ".ant-select-selection-item[title], .ant-select-selection-item, [data-selected-value]"
        );
        if (!item || !visible(item)) return null;
        var label = normalizeExactText(
            (item.getAttribute && (item.getAttribute("title") || item.getAttribute("data-selected-value")))
            || item.textContent
        );
        return label ? { node: item, label: label } : null;
    }

    function readSelectedCase(contract) {
        var input = caseInput(contract);
        if (!input || !visible(input)) return result(false, "case_input_missing");
        var selected = selectedCaseItem(input);
        if (!selected) return result(false, "case_selection_required");
        var maxLength = Math.max(1, Number(contract && contract.max_label_length) || 100);
        if (selected.label.length > maxLength) return result(false, "dom_contract_changed");
        var popup = popupForInput(input, contract);
        if (popup && typeof popup.querySelectorAll === "function") {
            var committedOptions = Array.prototype.filter.call(
                popup.querySelectorAll("[role='option'][aria-selected='true']"),
                visible
            ).map(function (option) {
                return normalizeExactText(
                    (option.getAttribute && option.getAttribute("title"))
                    || option.innerText || option.textContent
                );
            }).filter(Boolean);
            if (committedOptions.length && committedOptions.indexOf(selected.label) < 0) {
                return result(false, "case_selection_mismatch");
            }
        }
        return result(true, "", { label: selected.label });
    }

    function optionNodeForTarget(target) {
        if (!target) return null;
        if (target.getAttribute && target.getAttribute("role") === "option") return target;
        if (typeof target.closest === "function") return target.closest("[role='option']");
        return null;
    }

    function optionLabel(option) {
        return normalizeExactText(
            option && option.getAttribute && option.getAttribute("title")
            || option && (option.innerText || option.textContent)
        );
    }

    function optionBelongsToCasePopup(option, contract) {
        var input = caseInput(contract);
        var controls = normalizeExactText(input && input.getAttribute && input.getAttribute("aria-controls"));
        var listbox = option && typeof option.closest === "function"
            ? option.closest("[role='listbox']") : null;
        if (listbox && controls && String(listbox.id || "") === controls) return true;
        var popup = popupForInput(input, contract);
        return !!(popup && typeof popup.contains === "function" && popup.contains(option));
    }

    function acceptPickerCommit(clickSequence, expectedLabel) {
        if (activeMode !== "picker" || !activePickerContract) return false;
        if (clickSequence > 0 && clickSequence <= pickerAcceptedClickSequence) return false;
        var selected = readSelectedCase(activePickerContract);
        if (!selected.ok || (expectedLabel && selected.label !== expectedLabel)) {
            updatePickerToolbar();
            return false;
        }
        var selectedItem = selectedCaseItem(pickerInput);
        if (
            clickSequence <= 0
            && pickerInitialSelection
            && selectedItem
            && selectedItem.node === pickerInitialSelection.node
            && selectedItem.label === pickerInitialSelection.label
        ) {
            updatePickerToolbar();
            return false;
        }
        pickerSelectionRevision += 1;
        if (clickSequence > 0) pickerAcceptedClickSequence = clickSequence;
        updatePickerToolbar();
        return true;
    }

    function mutationContainsOptionCommit(records) {
        return Array.prototype.some.call(records || [], function (record) {
            if (!record || record.type !== "attributes" || record.attributeName !== "aria-selected") {
                return false;
            }
            var option = optionNodeForTarget(record.target);
            return !!(option && option.getAttribute
                && optionBelongsToCasePopup(option, activePickerContract)
                && option.getAttribute("aria-selected") === "true"
                && record.oldValue !== "true");
        });
    }

    function handlePickerMutations(records) {
        if (mutationContainsOptionCommit(records)) {
            var pendingClick = pickerOptionClickSequence > pickerAcceptedClickSequence
                ? pickerOptionClickSequence : 0;
            acceptPickerCommit(pendingClick, "");
            return;
        }
        updatePickerToolbar();
    }

    function rectanglesOverlap(left, right) {
        return !!(left && right
            && left.left < right.right && left.right > right.left
            && left.top < right.bottom && left.bottom > right.top);
    }

    function positionPickerToolbar(toolbar, contract) {
        if (!toolbar || typeof toolbar.getBoundingClientRect !== "function") return;
        var toolbarRect = toolbar.getBoundingClientRect();
        var width = Number(toolbarRect.width) || Number(toolbar.offsetWidth) || 360;
        var height = Number(toolbarRect.height) || Number(toolbar.offsetHeight) || 64;
        var gap = 16;
        var blockers = [];
        var input = caseInput(contract);
        var popup = popupForInput(input, contract);
        [input, popup].forEach(function (node) {
            if (node && visible(node) && typeof node.getBoundingClientRect === "function") {
                blockers.push(node.getBoundingClientRect());
            }
        });
        var candidates = [
            { left: Number(window.innerWidth) - width - gap, top: gap },
            { left: Number(window.innerWidth) - width - gap, top: Number(window.innerHeight) - height - gap },
            { left: gap, top: gap },
            { left: gap, top: Number(window.innerHeight) - height - gap }
        ];
        var selected = candidates.find(function (candidate) {
            var rect = {
                left: candidate.left,
                right: candidate.left + width,
                top: candidate.top,
                bottom: candidate.top + height
            };
            return candidate.left >= gap && candidate.top >= gap
                && blockers.every(function (blocker) { return !rectanglesOverlap(rect, blocker); });
        });
        if (!selected) return;
        toolbar.style.left = selected.left + "px";
        toolbar.style.top = selected.top + "px";
        toolbar.style.right = "auto";
        toolbar.style.bottom = "auto";
    }

    function updatePickerToolbar() {
        var toolbar = document.getElementById && document.getElementById(PICKER_TOOLBAR_ID);
        if (!toolbar || !activePickerContract) return;
        var status = toolbar._worktraceStatus;
        var confirm = toolbar._worktraceConfirm;
        var selected = readSelectedCase(activePickerContract);
        var proven = pickerSelectionRevision > 0 && selected.ok;
        if (status) status.textContent = proven
            ? "已选择案件，可以确认"
            : "请在本轮从 FD Work 原生案件列表中选择一个结果";
        if (confirm) confirm.disabled = !proven;
        positionPickerToolbar(toolbar, activePickerContract);
    }

    function helperApi() {
        var bridgeWindow = window;
        try {
            if (window.top && window.top.pywebview) bridgeWindow = window.top;
        } catch (_error) {}
        return bridgeWindow.pywebview && bridgeWindow.pywebview.api
            ? bridgeWindow.pywebview.api : null;
    }

    function makePickerToolbar(contract) {
        ensureStyle();
        var existing = document.getElementById && document.getElementById(PICKER_TOOLBAR_ID);
        if (existing) return existing;
        var toolbar = document.createElement("div");
        toolbar.id = PICKER_TOOLBAR_ID;
        toolbar.setAttribute("role", "toolbar");
        var status = document.createElement("span");
        status.textContent = "请在 FD Work 原生案件框中选择一个联想结果";
        var confirm = document.createElement("button");
        confirm.type = "button";
        confirm.textContent = "确认选择";
        confirm.disabled = true;
        var cancel = document.createElement("button");
        cancel.type = "button";
        cancel.textContent = "取消";
        toolbar._worktraceStatus = status;
        toolbar._worktraceConfirm = confirm;
        toolbar._worktraceCancel = cancel;
        toolbar.appendChild(status);
        toolbar.appendChild(confirm);
        toolbar.appendChild(cancel);
        confirm.addEventListener("click", function () {
            if (activeMode !== "picker" || activePickerContract !== contract) return;
            var selected = readSelectedCase(contract);
            if (pickerSelectionRevision <= 0 || !selected.ok) {
                updatePickerToolbar();
                return;
            }
            var api = helperApi();
            if (!api || typeof api.submit_case_picker_confirmation !== "function") return;
            var input = caseInput(contract);
            confirm.disabled = true;
            cancel.disabled = true;
            if (input) input.disabled = true;
            Promise.resolve(api.submit_case_picker_confirmation(
                String(contract.operation_nonce || ""),
                selected.label,
                pickerSelectionRevision
            )).then(function (response) {
                if (response && response.ok === true && response.accepted === true) return;
                confirm.disabled = false;
                cancel.disabled = false;
                if (input) input.disabled = pickerInputInitiallyDisabled;
            }, function () {
                confirm.disabled = false;
                cancel.disabled = false;
                if (input) input.disabled = pickerInputInitiallyDisabled;
            });
        });
        cancel.addEventListener("click", function () {
            if (activeMode !== "picker" || activePickerContract !== contract) return;
            var api = helperApi();
            if (!api || typeof api.submit_case_picker_cancellation !== "function") return;
            var input = caseInput(contract);
            confirm.disabled = true;
            cancel.disabled = true;
            if (input) input.disabled = true;
            Promise.resolve(api.submit_case_picker_cancellation(
                String(contract.operation_nonce || "")
            )).then(function (response) {
                if (response && response.ok === true && response.accepted === true) return;
                updatePickerToolbar();
                cancel.disabled = false;
                if (input) input.disabled = pickerInputInitiallyDisabled;
            }, function () {
                updatePickerToolbar();
                cancel.disabled = false;
                if (input) input.disabled = pickerInputInitiallyDisabled;
            });
        });
        if (document.body && typeof document.body.insertBefore === "function") {
            document.body.insertBefore(toolbar, document.body.firstChild || null);
        } else if (document.body && typeof document.body.appendChild === "function") {
            document.body.appendChild(toolbar);
        }
        positionPickerToolbar(toolbar, contract);
        return toolbar;
    }

    async function enterCasePicker(contract) {
        if (!contract || Number(contract.version) !== VERSION || !normalizeExactText(contract.operation_nonce)) {
            return result(false, "dom_contract_changed");
        }
        if (activeMode === "fill") return result(false, "fd_work_busy");
        removeFillToolbar();
        leaveCasePicker();
        activeMode = "picker";
        activeGeneration = Number(contract.operation_generation) || (activeGeneration + 1);
        activePickerContract = contract;
        pickerSelectionRevision = 0;
        if (document.documentElement && document.documentElement.setAttribute) {
            document.documentElement.setAttribute(PICKER_ROOT_ATTRIBUTE, "true");
        }
        var input = caseInput(contract);
        makePickerToolbar(contract);
        pickerInput = input;
        pickerInputInitiallyDisabled = !!(input && input.disabled);
        pickerInitialSelection = selectedCaseItem(input);
        pickerInputListener = updatePickerToolbar;
        pickerDocumentClickListener = function (event) {
            var option = optionNodeForTarget(event && event.target);
            if (!option || !visible(option) || !optionBelongsToCasePopup(option, contract)) return;
            var label = optionLabel(option);
            if (!label) return;
            var clickSequence = ++pickerOptionClickSequence;
            Promise.resolve().then(function () {
                acceptPickerCommit(clickSequence, label);
            });
        };
        clearPickerObserver();
        pickerObserver = new MutationObserver(handlePickerMutations);
        var observeRoot = document.body || document.documentElement;
        if (observeRoot) {
            pickerObserver.observe(observeRoot, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeOldValue: true,
                characterData: true
            });
        }
        if (input && typeof input.addEventListener === "function") {
            input.addEventListener("input", pickerInputListener);
            input.addEventListener("change", pickerInputListener);
        }
        if (typeof document.addEventListener === "function") {
            document.addEventListener("click", pickerDocumentClickListener, true);
        }
        updatePickerToolbar();
        return result(true, "", { status: "picker_ready" });
    }

    function leaveCasePicker() {
        clearPickerObserver();
        clearPickerListeners();
        var toolbar = document.getElementById && document.getElementById(PICKER_TOOLBAR_ID);
        if (toolbar && toolbar.remove) toolbar.remove();
        if (document.documentElement && document.documentElement.removeAttribute) {
            document.documentElement.removeAttribute(PICKER_ROOT_ATTRIBUTE);
        }
        activePickerContract = null;
        pickerSelectionRevision = 0;
        if (activeMode === "picker") activeMode = "none";
        return result(true);
    }

    function nativeSet(element, value) {
        if (!element) return result(false, "dom_contract_changed");
        var prototype = element instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : HTMLInputElement.prototype;
        var descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
        if (!descriptor || typeof descriptor.set !== "function") return result(false, "dom_contract_changed");
        descriptor.set.call(element, String(value));
        ["input", "change", "blur"].forEach(function (name) {
            element.dispatchEvent(new Event(name, { bubbles: true }));
        });
        return String(element.value) === String(value)
            ? result(true)
            : result(false, "dom_contract_changed");
    }

    function setSearchValue(input, value) {
        var descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
        if (!descriptor || typeof descriptor.set !== "function") return result(false, "dom_contract_changed");
        descriptor.set.call(input, String(value));
        ["input", "change"].forEach(function (name) {
            input.dispatchEvent(new Event(name, { bubbles: true }));
        });
        return result(true);
    }

    async function prepareCaseCombobox(contract, generation) {
        if (canceled(generation)) return result(false, "lookup_superseded");
        var input = caseInput(contract);
        if (!input) return result(false, "case_input_missing");
        if (!visible(input)) return result(false, "case_input_not_rendered");
        if (input.disabled || input.readOnly) return result(false, "case_input_not_interactive");
        input.focus();
        input.click();
        var deadline = deadlineAt(contract);
        while (Date.now() <= deadline) {
            if (canceled(generation)) return result(false, "lookup_superseded");
            var popup = popupForInput(input, contract);
            if (popup && visible(popup)) return result(true, "", { input: input, popup: popup });
            await new Promise(function (resolve) { setTimeout(resolve, 25); });
        }
        return result(false, "case_popup_not_created");
    }

    function optionLabels(popup) {
        return Array.prototype.filter.call(
            popup && popup.querySelectorAll ? popup.querySelectorAll("[role='option']") : [],
            visible
        ).map(function (option) {
            return {
                node: option,
                label: normalizeExactText(
                    (option.getAttribute && option.getAttribute("title"))
                    || option.innerText || option.textContent
                )
            };
        }).filter(function (item) { return !!item.label; });
    }

    async function selectExactCase(input, popup, expected, contract, generation) {
        var before = optionLabels(popup).map(function (item) { return item.label; }).join("\u0000");
        var applied = setSearchValue(input, expected);
        if (!applied.ok) return applied;
        var deadline = deadlineAt(contract);
        while (Date.now() <= deadline) {
            if (canceled(generation)) return result(false, "lookup_superseded");
            popup = popupForInput(input, contract) || popup;
            var options = optionLabels(popup);
            var signature = options.map(function (item) { return item.label; }).join("\u0000");
            var matches = options.filter(function (item) { return item.label === expected; });
            if ((signature !== before || matches.length) && matches.length === 1) {
                matches[0].node.click();
                await requestFrame();
                var selected = readSelectedCase(contract);
                if (selected.ok && selected.label === expected) return result(true);
                return result(false, "case_selection_mismatch");
            }
            if (matches.length > 1) return result(false, "case_ambiguous");
            await new Promise(function (resolve) { setTimeout(resolve, 25); });
        }
        return result(false, "case_not_found");
    }

    function fillAndVerify(name, value, contract) {
        var input = field(contract, name);
        if (!input || !visible(input)) return result(false, "dom_contract_changed");
        return nativeSet(input, value);
    }

    function installFillBlockingLayer() {
        ensureStyle();
        var existing = document.getElementById && document.getElementById(FILL_BLOCKER_ID);
        if (existing) return existing;
        var blocker = document.createElement("div");
        blocker.id = FILL_BLOCKER_ID;
        blocker.setAttribute("role", "status");
        blocker.setAttribute("aria-live", "assertive");
        blocker.textContent = "正在填入，请勿操作";
        if (document.body && typeof document.body.appendChild === "function") document.body.appendChild(blocker);
        return blocker;
    }

    function removeFillBlockingLayer() {
        var blocker = document.getElementById && document.getElementById(FILL_BLOCKER_ID);
        if (blocker && blocker.remove) blocker.remove();
    }

    function makeFillToolbar() {
        ensureStyle();
        var existing = document.getElementById && document.getElementById(FILL_TOOLBAR_ID);
        if (existing) return existing;
        var toolbar = document.createElement("div");
        toolbar.id = FILL_TOOLBAR_ID;
        toolbar.setAttribute("role", "toolbar");
        var label = document.createElement("span");
        label.textContent = "已从 WorkTrace 填入，请检查后在 FD Work 中手工保存";
        toolbar.appendChild(label);
        if (document.body && typeof document.body.insertBefore === "function") {
            document.body.insertBefore(toolbar, document.body.firstChild || null);
        }
        return toolbar;
    }

    function verifyEntry(payload, contract) {
        var selected = readSelectedCase(contract);
        if (!selected.ok || selected.label !== normalizeExactText(payload.case_number)) {
            return result(false, "case_selection_mismatch");
        }
        for (var name of ["work_date", "duration_hours", "narrative"]) {
            var input = field(contract, name);
            if (!input || String(input.value) !== String(payload[name])) {
                return result(false, name + "_verification_failed");
            }
        }
        return result(true);
    }

    async function fillEntry(payload, contract) {
        if (!payload || !contract || Number(contract.version) !== VERSION) {
            return result(false, "dom_contract_changed");
        }
        if (activeMode === "picker") return result(false, "fd_work_busy");
        leaveCasePicker();
        removeFillToolbar();
        activeMode = "fill";
        activeGeneration = Number(contract.operation_generation) || (activeGeneration + 1);
        var generation = activeGeneration;
        lastPayload = Object.assign({}, payload);
        lastContract = contract;
        installFillBlockingLayer();
        try {
            var stable = await awaitStableWorkShell(contract);
            if (!stable.ok) return stable;
            var prepared = await prepareCaseCombobox(contract, generation);
            if (!prepared.ok) return prepared;
            var chosen = await selectExactCase(
                prepared.input,
                prepared.popup,
                normalizeExactText(payload.case_number),
                contract,
                generation
            );
            if (!chosen.ok) return chosen;
            for (var name of ["work_date", "duration_hours", "narrative"]) {
                var filled = fillAndVerify(name, payload[name], contract);
                if (!filled.ok) return filled;
            }
            var verified = verifyEntry(payload, contract);
            if (!verified.ok) return verified;
            makeFillToolbar();
            activeMode = "review";
            return result(true, "", { status: "filled" });
        } catch (_error) {
            return result(false, canceled(generation) ? "lookup_superseded" : "dom_contract_changed");
        } finally {
            removeFillBlockingLayer();
            if (activeMode === "fill") activeMode = "none";
        }
    }

    window.addEventListener("pagehide", function () {
        activeGeneration += 1;
        clearPickerObserver();
        clearPickerListeners();
        removeFillBlockingLayer();
        activePickerContract = null;
        pickerSelectionRevision = 0;
        activeMode = "none";
    });

    window.WorkTraceFDWorkAdapter = Object.freeze({
        version: VERSION,
        awaitStableWorkShell: awaitStableWorkShell,
        enterCasePicker: enterCasePicker,
        leaveCasePicker: leaveCasePicker,
        readSelectedCase: readSelectedCase,
        fillEntry: fillEntry,
        fillWorkDate: function (value, contract) { return fillAndVerify("work_date", value, contract); },
        fillDuration: function (value, contract) { return fillAndVerify("duration_hours", value, contract); },
        fillNarrative: function (value, contract) { return fillAndVerify("narrative", value, contract); },
        _test: Object.freeze({
            normalizeExactText: normalizeExactText,
            visible: visible,
            readSelectedCase: readSelectedCase,
            activeMode: function () { return activeMode; }
        })
    });
})();
