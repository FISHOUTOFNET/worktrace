(function () {
    "use strict";
    if (window.WorkTraceFDWorkAdapter && window.WorkTraceFDWorkAdapter.version === 5) return;

    var VERSION = 5;
    var PICKER_ROOT_ATTRIBUTE = "data-worktrace-fdwork-picker";
    var STYLE_ID = "worktrace-fdwork-style";
    var PICKER_TOOLBAR_ID = "worktrace-fdwork-picker-toolbar";
    var FILL_TOOLBAR_ID = "worktrace-fdwork-fill-toolbar";
    var FILL_BLOCKER_ID = "worktrace-fdwork-fill-blocker";
    var ACTION_MESSAGE_CHANNEL = "worktrace-fdwork-action-v5";
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
    var actionQueue = Promise.resolve();

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

    function entryField(contract, name) {
        var item = contract && contract.entry_fields && contract.entry_fields[name];
        return item && item.selector ? document.querySelector(item.selector) : null;
    }

    function caseInput(contract) {
        var item = contract && (
            contract.field || (contract.entry_fields && contract.entry_fields.case_number)
        );
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
        var controls = normalizeExactText(input.getAttribute && (
            input.getAttribute("aria-controls") || input.getAttribute("aria-owns")
        ));
        var configured = contract && (
            contract.field || (contract.entry_fields && contract.entry_fields.case_number)
        );
        var configuredSelector = configured && configured.listbox;
        if (controls && document.getElementById) {
            var ids = controls.split(/\s+/).filter(Boolean);
            for (var index = 0; index < ids.length; index += 1) {
                var controlled = document.getElementById(ids[index]);
                if (controlled) return controlled;
            }
            return null;
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
        if (Number.isFinite(existing) && existing > 0) return existing;
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
                var firstInput = input;
                var first = firstInput.getBoundingClientRect ? firstInput.getBoundingClientRect() : null;
                await requestFrame();
                if (canceled(generation)) return result(false, "lookup_superseded");
                var secondInput = caseInput(contract);
                if (secondInput !== firstInput) continue;
                var second = secondInput.getBoundingClientRect ? secondInput.getBoundingClientRect() : null;
                await requestFrame();
                if (canceled(generation)) return result(false, "lookup_superseded");
                var thirdInput = caseInput(contract);
                if (thirdInput !== firstInput) continue;
                var third = thirdInput.getBoundingClientRect ? thirdInput.getBoundingClientRect() : null;
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

    function nodeContainsSelectionItem(node) {
        if (!node || node.nodeType !== 1) return false;
        if (typeof node.matches === "function" && node.matches(
            ".ant-select-selection-item, [data-selected-value]"
        )) return true;
        return !!(typeof node.querySelector === "function" && node.querySelector(
            ".ant-select-selection-item, [data-selected-value]"
        ));
    }

    function mutationContainsSelectionCommit(records) {
        var wrapper = selectWrapperFor(pickerInput);
        if (!wrapper) return false;
        return Array.prototype.some.call(records || [], function (record) {
            if (!record || !record.target) return false;
            var targetInsideWrapper = record.target === wrapper
                || (typeof wrapper.contains === "function" && wrapper.contains(record.target));
            if (!targetInsideWrapper) return false;
            if (nodeContainsSelectionItem(record.target)) return true;
            return Array.prototype.some.call(record.addedNodes || [], nodeContainsSelectionItem)
                || Array.prototype.some.call(record.removedNodes || [], nodeContainsSelectionItem);
        });
    }

    function handlePickerMutations(records) {
        if (!mutationContainsOptionCommit(records) && !mutationContainsSelectionCommit(records)) return;
        var pendingClick = pickerOptionClickSequence > pickerAcceptedClickSequence
            ? pickerOptionClickSequence : 0;
        acceptPickerCommit(pendingClick, "");
    }

    function observePickerSelectionDom(contract) {
        clearPickerObserver();
        pickerObserver = new MutationObserver(handlePickerMutations);
        var wrapper = selectWrapperFor(pickerInput);
        if (wrapper) {
            pickerObserver.observe(wrapper, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeOldValue: true,
                attributeFilter: ["title", "data-selected-value", "aria-label"],
                characterData: true
            });
        }
        var popup = popupForInput(pickerInput, contract);
        if (popup && popup !== wrapper) {
            pickerObserver.observe(popup, {
                subtree: true,
                attributes: true,
                attributeOldValue: true,
                attributeFilter: ["aria-selected"]
            });
        }
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
        var nextLeft = selected.left + "px";
        var nextTop = selected.top + "px";
        if (toolbar.style.left !== nextLeft) toolbar.style.left = nextLeft;
        if (toolbar.style.top !== nextTop) toolbar.style.top = nextTop;
        if (toolbar.style.right !== "auto") toolbar.style.right = "auto";
        if (toolbar.style.bottom !== "auto") toolbar.style.bottom = "auto";
    }

    function updatePickerToolbar() {
        var toolbar = document.getElementById && document.getElementById(PICKER_TOOLBAR_ID);
        if (!toolbar || !activePickerContract) return;
        var status = toolbar._worktraceStatus;
        var confirm = toolbar._worktraceConfirm;
        var selected = readSelectedCase(activePickerContract);
        var proven = pickerSelectionRevision > 0 && selected.ok;
        var nextStatus = proven
            ? "已选择案件，可以确认"
            : "请在本轮从 FD Work 原生案件列表中选择一个结果";
        if (status && status.textContent !== nextStatus) status.textContent = nextStatus;
        if (confirm && confirm.disabled !== !proven) confirm.disabled = !proven;
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

    function enterCasePicker(contract) {
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
        observePickerSelectionDom(contract);
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
        return result(true);
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

    function stageFailure(stage, error, extra) {
        return result(false, error, Object.assign({
            stage: stage,
            internal_error_kind: error
        }, extra || {}));
    }

    function stageResult(value, stage) {
        if (value && value.ok) return value;
        var error = value && value.error ? value.error : "dom_contract_changed";
        return stageFailure(stage, error, value || {});
    }

    function strictDateValue(value) {
        var text = String(value == null ? "" : value);
        if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return null;
        var parts = text.split("-").map(Number);
        var timestamp = Date.UTC(parts[0], parts[1] - 1, parts[2]);
        var parsed = new Date(timestamp);
        if (
            parsed.getUTCFullYear() !== parts[0]
            || parsed.getUTCMonth() !== parts[1] - 1
            || parsed.getUTCDate() !== parts[2]
        ) return null;
        return { text: text, timestamp: timestamp };
    }

    function dateTextFromTimestamp(timestamp) {
        return new Date(timestamp).toISOString().slice(0, 10);
    }

    function pageDateInput(contract) {
        var item = contract && contract.page_context && contract.page_context.work_date;
        if (!item || !item.selector || !document.querySelectorAll) return null;
        var excluded = item.outside_form_selector
            ? document.querySelector(item.outside_form_selector) : null;
        var matches = Array.prototype.filter.call(
            document.querySelectorAll(item.selector),
            function (candidate) {
                return visible(candidate) && !(excluded && excluded.contains(candidate));
            }
        );
        return matches.length === 1 ? matches[0] : null;
    }

    function readEntryDate(contract) {
        var input = pageDateInput(contract);
        if (!input) return stageFailure("date_read", "date_control_missing");
        var parsed = strictDateValue(input.value);
        if (!parsed) return stageFailure("date_read", "date_verification_failed");
        return result(true, "", { value: parsed.text, timestamp: parsed.timestamp });
    }

    function dateNavigationButton(input, contract, direction) {
        var item = contract && contract.page_context && contract.page_context.work_date;
        if (!input || !item || typeof input.closest !== "function") return null;
        var root = input.closest(item.navigation_container_selector || ".ant-space-compact");
        if (!root || typeof root.querySelector !== "function") return null;
        var iconName = direction < 0 ? item.previous_button_icon : item.next_button_icon;
        if (iconName !== "left" && iconName !== "right") return null;
        var icon = root.querySelector(
            "[aria-label='" + iconName + "'], [data-icon='" + iconName + "']"
        );
        return icon && typeof icon.closest === "function" ? icon.closest("button") : null;
    }

    function dispatchDomEvent(node, type, pointer) {
        if (!node || typeof node.dispatchEvent !== "function") return false;
        var Constructor = pointer && typeof PointerEvent === "function"
            ? PointerEvent : (typeof MouseEvent === "function" ? MouseEvent : Event);
        try {
            return node.dispatchEvent(new Constructor(type, {
                bubbles: true,
                cancelable: true,
                composed: true,
                button: 0,
                buttons: type === "mousedown" || type === "pointerdown" ? 1 : 0,
                pointerType: pointer ? "mouse" : undefined
            }));
        } catch (_error) {
            return false;
        }
    }

    function dispatchPointerMouseSequence(node, focusTarget) {
        if (!node) return false;
        dispatchDomEvent(node, "pointerdown", true);
        dispatchDomEvent(node, "mousedown", false);
        if (focusTarget && typeof focusTarget.focus === "function") {
            try { focusTarget.focus({ preventScroll: true }); }
            catch (_error) { try { focusTarget.focus(); } catch (_ignored) {} }
        }
        dispatchDomEvent(node, "mouseup", false);
        dispatchDomEvent(node, "click", false);
        return true;
    }

    async function ensureEntryDate(targetDate, contract, generation) {
        var target = strictDateValue(targetDate);
        if (!target) return stageFailure("date_read", "date_verification_failed");
        var current = readEntryDate(contract);
        if (!current.ok) return current;
        if (current.value === target.text) {
            return result(true, "", { stage: "date_verified", date_step_count: 0 });
        }
        var totalSteps = Math.round((target.timestamp - current.timestamp) / 86400000);
        var maxSteps = Math.max(1, Number(contract && contract.max_date_steps) || 366);
        if (!Number.isInteger(totalSteps) || Math.abs(totalSteps) > maxSteps) {
            return stageFailure("date_change", "date_change_failed", { date_step_count: 0 });
        }
        var direction = totalSteps < 0 ? -1 : 1;
        var steps = 0;
        var deadline = deadlineAt(contract);
        while (current.value !== target.text && steps < Math.abs(totalSteps)) {
            if (canceled(generation)) return stageFailure("date_change", "lookup_superseded", {
                date_step_count: steps
            });
            if (Date.now() > deadline) return stageFailure("date_change", "date_change_failed", {
                date_step_count: steps
            });
            var input = pageDateInput(contract);
            var button = dateNavigationButton(input, contract, direction);
            if (!button || !visible(button)) return stageFailure(
                "date_change", "date_control_missing", { date_step_count: steps }
            );
            var before = current.value;
            var expected = dateTextFromTimestamp(current.timestamp + direction * 86400000);
            dispatchPointerMouseSequence(button, null);
            var changed = null;
            while (Date.now() <= deadline) {
                if (canceled(generation)) return stageFailure("date_change", "lookup_superseded", {
                    date_step_count: steps
                });
                var observed = readEntryDate(contract);
                if (!observed.ok) return observed;
                if (observed.value !== before) {
                    changed = observed;
                    break;
                }
                await requestFrame();
            }
            if (!changed) return stageFailure("date_change", "date_change_failed", {
                date_step_count: steps
            });
            steps += 1;
            if (changed.value !== expected) return stageFailure(
                "date_change", "date_change_failed", { date_step_count: steps }
            );
            current = changed;
        }
        var verified = readEntryDate(contract);
        if (!verified.ok || verified.value !== target.text) return stageFailure(
            "date_verified", "date_verification_failed", { date_step_count: steps }
        );
        return result(true, "", { stage: "date_verified", date_step_count: steps });
    }

    async function prepareCaseCombobox(contract, generation) {
        if (canceled(generation)) return stageFailure("case_open", "lookup_superseded");
        var input = caseInput(contract);
        if (!input) return stageFailure("case_open", "case_input_missing");
        if (!visible(input)) return stageFailure("case_open", "case_input_not_rendered");
        if (input.disabled || input.readOnly) return stageFailure("case_open", "case_input_not_interactive");
        var controls = normalizeExactText(input.getAttribute && (
            input.getAttribute("aria-controls") || input.getAttribute("aria-owns")
        ));
        if (!controls) return stageFailure("case_open", "case_aria_controls_missing");
        var wrapper = selectWrapperFor(input);
        var selector = wrapper && wrapper.querySelector
            ? wrapper.querySelector(".ant-select-selector") : null;
        if (!selector || !dispatchPointerMouseSequence(selector, input)) {
            return stageFailure("case_open", "case_input_not_interactive");
        }
        var deadline = deadlineAt(contract);
        while (Date.now() <= deadline) {
            if (canceled(generation)) return stageFailure("case_open", "lookup_superseded");
            input = caseInput(contract);
            var popup = popupForInput(input, contract);
            if (popup && visible(popup)) return result(true, "", { stage: "case_open" });
            await requestFrame();
        }
        return stageFailure("case_open", "case_popup_not_created");
    }

    function optionLabels(popup) {
        var candidates = popup && popup.querySelectorAll ? popup.querySelectorAll(
            ".ant-select-item-option:not(.ant-select-item-option-disabled), "
            + "[role='option']:not([aria-disabled='true'])"
        ) : [];
        var unique = [];
        Array.prototype.forEach.call(candidates, function (option) {
            if (unique.indexOf(option) < 0) unique.push(option);
        });
        return unique.filter(function (option) {
            var classDisabled = option.classList
                && option.classList.contains("ant-select-item-option-disabled");
            var ariaDisabled = option.getAttribute
                && option.getAttribute("aria-disabled") === "true";
            return !classDisabled && !ariaDisabled && visible(option);
        }).map(function (option) {
            return {
                node: option,
                label: normalizeExactText(
                    (option.getAttribute && option.getAttribute("title"))
                    || option.innerText || option.textContent
                )
            };
        }).filter(function (item) { return !!item.label; });
    }

    function optionIsConnected(option) {
        if (!option) return false;
        return typeof option.isConnected === "boolean" ? option.isConnected : true;
    }

    function caseCommitDiagnostics(extra) {
        var diagnostic = {
            option_count: 0,
            commit_method: "none",
            commit_attempt_count: 0,
            option_connected_before_action: false,
            option_connected_after_action: false,
            popup_replaced: false,
            live_option_reacquired: false
        };
        extra = extra || {};
        if (["none", "semantic_click", "semantic_click_event"].indexOf(extra.commit_method) >= 0) {
            diagnostic.commit_method = extra.commit_method;
        }
        ["option_count", "commit_attempt_count"].forEach(function (key) {
            if (Number.isInteger(extra[key]) && extra[key] >= 0 && extra[key] <= 10000) {
                diagnostic[key] = extra[key];
            }
        });
        [
            "option_connected_before_action", "option_connected_after_action",
            "popup_replaced", "live_option_reacquired"
        ].forEach(function (key) {
            if (typeof extra[key] === "boolean") diagnostic[key] = extra[key];
        });
        return diagnostic;
    }

    function findExactLiveCaseOption(expectedLabel, contract) {
        var input = caseInput(contract);
        var popup = popupForInput(input, contract);
        if (!input || !popup || !visible(popup)) return result(
            false,
            "case_popup_not_interactive",
            { input: input, popup: popup, option_count: 0 }
        );
        var options = optionLabels(popup);
        var matches = options.filter(function (item) {
            return item.label === expectedLabel;
        });
        if (matches.length > 1) return result(false, "case_ambiguous", {
            input: input,
            popup: popup,
            option_count: options.length
        });
        if (matches.length === 0) return result(false, "case_not_found", {
            input: input,
            popup: popup,
            option_count: options.length
        });
        return result(true, "", {
            input: input,
            popup: popup,
            node: matches[0].node,
            option_count: options.length
        });
    }

    function commitExactCaseOption(expectedLabel, contract, diagnostic) {
        var live = findExactLiveCaseOption(expectedLabel, contract);
        var details = caseCommitDiagnostics(Object.assign({}, diagnostic || {}, {
            option_count: live.option_count || 0,
            live_option_reacquired: true
        }));
        if (!live.ok) return stageFailure("case_commit", live.error, details);

        var option = live.node;
        details.option_connected_before_action = optionIsConnected(option);
        if (!details.option_connected_before_action) {
            return stageFailure("case_commit", "case_selection_mismatch", details);
        }

        var actionSucceeded = false;
        if (typeof option.click === "function") {
            details.commit_method = "semantic_click";
            details.commit_attempt_count = 1;
            try {
                option.click();
                actionSucceeded = true;
            } catch (_error) {}
        }
        if (!actionSucceeded) {
            live = findExactLiveCaseOption(expectedLabel, contract);
            details.option_count = live.option_count || 0;
            details.live_option_reacquired = true;
            if (!live.ok) return stageFailure("case_commit", live.error, details);
            option = live.node;
            details.option_connected_before_action = optionIsConnected(option);
            if (!details.option_connected_before_action) {
                return stageFailure("case_commit", "case_selection_mismatch", details);
            }
            details.commit_method = "semantic_click_event";
            details.commit_attempt_count += 1;
            actionSucceeded = dispatchDomEvent(option, "click", false);
        }
        details.option_connected_after_action = optionIsConnected(option);
        return actionSucceeded ? result(true, "", details)
            : stageFailure("case_commit", "case_selection_mismatch", details);
    }

    async function selectExactCase(expectedLabel, searchQuery, contract, generation) {
        var input = caseInput(contract);
        var popup = popupForInput(input, contract);
        if (!input || !popup || !visible(popup)) return stageFailure(
            "case_query", "case_popup_not_interactive"
        );
        var beforePopup = popup;
        var before = optionLabels(popup).map(function (item) { return item.label; }).join("\u0000");
        var applied = setSearchValue(input, searchQuery);
        if (!applied.ok) return stageResult(applied, "case_query");
        var deadline = deadlineAt(contract);
        var queryAccepted = false;
        while (Date.now() <= deadline) {
            if (canceled(generation)) return stageFailure("case_query", "lookup_superseded");
            input = caseInput(contract);
            if (input && String(input.value) === String(searchQuery)) {
                queryAccepted = true;
                break;
            }
            await requestFrame();
        }
        if (!queryAccepted) return stageFailure("case_query", "case_query_not_applied");
        var optionCount = 0;
        var commitResult = null;
        while (Date.now() <= deadline) {
            if (canceled(generation)) return stageFailure("case_results", "lookup_superseded");
            var live = findExactLiveCaseOption(expectedLabel, contract);
            optionCount = live.option_count || 0;
            if (live.error === "case_ambiguous") return stageFailure(
                "case_results", "case_ambiguous", caseCommitDiagnostics({
                    option_count: optionCount,
                    popup_replaced: live.popup !== beforePopup
                })
            );
            var signature = live.popup
                ? optionLabels(live.popup).map(function (item) { return item.label; }).join("\u0000")
                : "";
            if (live.ok && (live.popup !== beforePopup || signature !== before)) {
                commitResult = commitExactCaseOption(expectedLabel, contract, {
                    option_count: optionCount,
                    popup_replaced: live.popup !== beforePopup,
                    live_option_reacquired: true
                });
                break;
            }
            await requestFrame();
        }
        if (!commitResult) return stageFailure(
            "case_results", "case_not_found", caseCommitDiagnostics({
                option_count: optionCount,
                popup_replaced: popupForInput(caseInput(contract), contract) !== beforePopup
            })
        );
        if (!commitResult.ok) return commitResult;
        while (Date.now() <= deadline) {
            if (canceled(generation)) return stageFailure("case_commit", "lookup_superseded", {
                option_count: optionCount,
                commit_method: commitResult.commit_method,
                commit_attempt_count: commitResult.commit_attempt_count
            });
            var selected = readSelectedCase(contract);
            if (selected.ok && selected.label === expectedLabel) return result(true, "", {
                stage: "case_verified",
                option_count: optionCount,
                commit_method: commitResult.commit_method,
                commit_attempt_count: commitResult.commit_attempt_count,
                option_connected_before_action: commitResult.option_connected_before_action,
                option_connected_after_action: commitResult.option_connected_after_action,
                popup_replaced: commitResult.popup_replaced,
                live_option_reacquired: commitResult.live_option_reacquired
            });
            await requestFrame();
        }
        return stageFailure(
            "case_verified",
            "case_selection_mismatch",
            caseCommitDiagnostics(commitResult)
        );
    }

    async function awaitStableEntryValue(name, expected, contract, generation) {
        var deadline = deadlineAt(contract);
        var stableFrames = 0;
        while (Date.now() <= deadline) {
            if (canceled(generation)) return result(false, "lookup_superseded");
            var input = entryField(contract, name);
            if (input && visible(input) && String(input.value) === String(expected)) {
                stableFrames += 1;
                if (stableFrames >= 2) return result(true);
            } else {
                stableFrames = 0;
            }
            await requestFrame();
        }
        return result(false, name === "duration_hours"
            ? "duration_verification_failed" : "narrative_verification_failed");
    }

    async function fillDuration(value, contract, generation) {
        var input = entryField(contract, "duration_hours");
        if (!input || !visible(input) || input.disabled || input.readOnly) {
            return stageFailure("duration_write", "dom_contract_changed");
        }
        if (typeof input.focus === "function") input.focus();
        var written = nativeSet(input, value);
        if (!written.ok) return stageResult(written, "duration_write");
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        if (typeof input.blur === "function") input.blur();
        var verified = await awaitStableEntryValue(
            "duration_hours", value, contract, generation
        );
        return verified.ok ? result(true, "", { stage: "duration_verified" })
            : stageFailure("duration_verified", verified.error || "duration_verification_failed");
    }

    async function fillNarrative(value, contract, generation) {
        var input = entryField(contract, "narrative");
        if (!input || !visible(input) || input.disabled || input.readOnly) {
            return stageFailure("narrative_write", "dom_contract_changed");
        }
        if (typeof input.focus === "function") input.focus();
        var written = nativeSet(input, value);
        if (!written.ok) return stageResult(written, "narrative_write");
        input.dispatchEvent(new Event("input", { bubbles: true }));
        var verified = await awaitStableEntryValue("narrative", value, contract, generation);
        if (!verified.ok) return stageFailure(
            "narrative_verified", verified.error || "narrative_verification_failed"
        );
        input = entryField(contract, "narrative");
        if (input && typeof input.blur === "function") input.blur();
        verified = await awaitStableEntryValue("narrative", value, contract, generation);
        return verified.ok ? result(true, "", { stage: "narrative_verified" })
            : stageFailure("narrative_verified", verified.error || "narrative_verification_failed");
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

    async function verifyEntry(payload, contract, generation) {
        await requestFrame();
        if (canceled(generation)) return stageFailure("entry_verified", "lookup_superseded");
        var date = readEntryDate(contract);
        if (!date.ok || date.value !== String(payload.work_date)) {
            return stageFailure("entry_verified", "date_verification_failed");
        }
        var selected = readSelectedCase(contract);
        if (!selected.ok || selected.label !== normalizeExactText(payload.case_label)) {
            return stageFailure("entry_verified", "case_selection_mismatch");
        }
        for (var name of ["duration_hours", "narrative"]) {
            var input = entryField(contract, name);
            if (!input || String(input.value) !== String(payload[name])) {
                return stageFailure("entry_verified", name + "_verification_failed");
            }
        }
        return result(true, "", { stage: "entry_verified" });
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
        var currentStage = "page_stable";
        try {
            var stable = await awaitStableWorkShell(contract);
            if (!stable.ok) return stageResult(stable, "page_stable");
            currentStage = "date_read";
            var dated = await ensureEntryDate(payload.work_date, contract, generation);
            if (!dated.ok) return dated;
            currentStage = "page_stable";
            var stableAfterDate = await awaitStableWorkShell(contract);
            if (!stableAfterDate.ok) return stageResult(stableAfterDate, "page_stable");
            currentStage = "case_open";
            var prepared = await prepareCaseCombobox(contract, generation);
            if (!prepared.ok) return prepared;
            currentStage = "case_query";
            var chosen = await selectExactCase(
                normalizeExactText(payload.case_label),
                normalizeExactText(payload.case_query),
                contract,
                generation
            );
            if (!chosen.ok) return chosen;
            currentStage = "duration_write";
            var duration = await fillDuration(payload.duration_hours, contract, generation);
            if (!duration.ok) return duration;
            currentStage = "narrative_write";
            var narrative = await fillNarrative(payload.narrative, contract, generation);
            if (!narrative.ok) return narrative;
            currentStage = "entry_verified";
            var verified = await verifyEntry(payload, contract, generation);
            if (!verified.ok) return verified;
            makeFillToolbar();
            activeMode = "review";
            return result(true, "", { status: "filled", stage: "entry_verified" });
        } catch (_error) {
            var error = canceled(generation) ? "lookup_superseded" : "dom_contract_changed";
            return stageFailure(currentStage, error);
        } finally {
            removeFillBlockingLayer();
            if (activeMode === "fill") activeMode = "none";
        }
    }

    function actionHandler(action) {
        var handlers = {
            awaitStableWorkShell: function (args) { return awaitStableWorkShell(args[0]); },
            enterCasePicker: function (args) { return enterCasePicker(args[0]); },
            leaveCasePicker: function () { return leaveCasePicker(); },
            readSelectedCase: function (args) { return readSelectedCase(args[0]); },
            fillEntry: function (args) { return fillEntry(args[0], args[1]); }
        };
        return Object.prototype.hasOwnProperty.call(handlers, action) ? handlers[action] : null;
    }

    function safeActionResult(value) {
        if (!value || typeof value !== "object" || typeof value.ok !== "boolean") {
            return { ok: false, error: "non_mapping_result" };
        }
        var safe = { ok: value.ok };
        ["error", "status", "label", "document_visibility"].forEach(function (key) {
            if (typeof value[key] === "string") safe[key] = value[key];
        });
        ["stage", "internal_error_kind"].forEach(function (key) {
            if (typeof value[key] === "string") safe[key] = value[key];
        });
        if (["none", "semantic_click", "semantic_click_event"].indexOf(value.commit_method) >= 0) {
            safe.commit_method = value.commit_method;
        }
        [
            "viewport_available", "input_exists", "input_interactive",
            "option_connected_before_action", "option_connected_after_action",
            "popup_replaced", "live_option_reacquired"
        ].forEach(function (key) {
            if (typeof value[key] === "boolean") safe[key] = value[key];
        });
        ["option_count", "date_step_count", "commit_attempt_count"].forEach(function (key) {
            if (Number.isInteger(value[key]) && value[key] >= 0 && value[key] <= 10000) {
                safe[key] = value[key];
            }
        });
        return safe;
    }

    function reportActionResult(command, value) {
        var api = helperApi();
        if (!api || typeof api.submit_adapter_action_result !== "function") return;
        Promise.resolve(api.submit_adapter_action_result(
            command.action_nonce,
            command.action,
            safeActionResult(value)
        )).catch(function () {});
    }

    function handleActionMessage(event) {
        if (!event || event.source !== window.top) return;
        if (event.origin !== window.location.origin) return;
        var command = event.data;
        if (!command || command.channel !== ACTION_MESSAGE_CHANNEL || Number(command.version) !== VERSION) return;
        if (typeof command.action_nonce !== "string" || !command.action_nonce || command.action_nonce.length > 256) return;
        if (!Array.isArray(command.arguments) || command.arguments.length > 2) return;
        var handler = actionHandler(command.action);
        if (!handler) return;
        actionQueue = actionQueue.then(function () {
            return handler(command.arguments);
        }).then(function (value) {
            reportActionResult(command, value);
        }, function () {
            reportActionResult(command, { ok: false, error: "javascript_exception" });
        });
    }

    window.addEventListener("message", handleActionMessage);

    window.addEventListener("pagehide", function () {
        window.removeEventListener("message", handleActionMessage);
        activeGeneration += 1;
        clearPickerObserver();
        clearPickerListeners();
        removeFillBlockingLayer();
        activePickerContract = null;
        pickerSelectionRevision = 0;
        activeMode = "none";
        try { delete window.WorkTraceFDWorkAdapter; } catch (_error) {}
    });

    window.WorkTraceFDWorkAdapter = Object.freeze({
        version: VERSION,
        awaitStableWorkShell: awaitStableWorkShell,
        enterCasePicker: enterCasePicker,
        leaveCasePicker: leaveCasePicker,
        readSelectedCase: readSelectedCase,
        fillEntry: fillEntry,
        ensureEntryDate: ensureEntryDate,
        fillDuration: fillDuration,
        fillNarrative: fillNarrative,
        _test: Object.freeze({
            normalizeExactText: normalizeExactText,
            visible: visible,
            readSelectedCase: readSelectedCase,
            readEntryDate: readEntryDate,
            selectExactCase: selectExactCase,
            activeMode: function () { return activeMode; }
        })
    });
})();
