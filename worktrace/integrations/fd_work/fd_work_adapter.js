(function () {
    "use strict";
    if (window.WorkTraceFDWorkAdapter && window.WorkTraceFDWorkAdapter.version === 4) return;

    var ROOT_ATTRIBUTE = "data-worktrace-fdwork-compact";
    var HIDDEN_ATTRIBUTE = "data-worktrace-fdwork-hidden";
    var STYLE_ID = "worktrace-fdwork-compact-style";
    var TOOLBAR_ID = "worktrace-fdwork-toolbar";
    var lastPayload = null;
    var lastContract = null;
    var compactObserver = null;
    var lookupGeneration = 0;

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
        if (style && (style.display === "none" || style.visibility === "hidden")) {
            return false;
        }
        return typeof element.getClientRects !== "function"
            || element.getClientRects().length > 0;
    }

    function nativeSet(element, value) {
        var prototype = element instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : HTMLInputElement.prototype;
        var descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
        if (!descriptor || typeof descriptor.set !== "function") {
            return result(false, "page_contract_changed");
        }
        descriptor.set.call(element, String(value));
        ["input", "change", "blur"].forEach(function (name) {
            element.dispatchEvent(new Event(name, { bubbles: true }));
        });
        return result(true);
    }

    function setSearchValue(input, value) {
        var descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
        if (!descriptor || typeof descriptor.set !== "function") {
            return result(false, "page_contract_changed");
        }
        descriptor.set.call(input, String(value));
        ["input", "change"].forEach(function (name) {
            input.dispatchEvent(new Event(name, { bubbles: true }));
        });
        return result(true);
    }

    function normalizeCaseLabels(texts, maxOptions, maxLabelLength) {
        if (!Array.isArray(texts) || Number(maxOptions) < 1 || Number(maxOptions) > 20) {
            return result(false, "page_contract_changed");
        }
        var labels = [];
        var seen = Object.create(null);
        for (var index = 0; index < texts.length; index += 1) {
            if (typeof texts[index] !== "string") {
                return result(false, "page_contract_changed");
            }
            var label = normalizeExactText(texts[index]);
            if (!label || label.length > Number(maxLabelLength)) {
                return result(false, "page_contract_changed");
            }
            if (seen[label]) return result(false, "duplicate_case_label");
            seen[label] = true;
            if (labels.length < Number(maxOptions)) labels.push(label);
        }
        return result(true, "", { labels: labels });
    }

    function waitFor(predicate, timeoutMs) {
        return new Promise(function (resolve) {
            var settled = false;
            var finish = function (value) {
                if (settled) return;
                settled = true;
                observer.disconnect();
                clearTimeout(timer);
                resolve(value);
            };
            var check = function () {
                var value = null;
                try { value = predicate(); } catch (_error) { value = null; }
                if (value) finish(value);
            };
            var observer = new MutationObserver(check);
            observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true });
            var timer = setTimeout(function () { finish(null); }, timeoutMs || 5000);
            check();
        });
    }

    function delay(milliseconds) {
        return new Promise(function (resolve) {
            setTimeout(resolve, milliseconds);
        });
    }

    function startOperationDeadline(contract) {
        var copy = Object.assign({}, contract || {});
        copy.operation_deadline_ms = Date.now() + Math.max(
            1,
            Number(copy.lookup_timeout_ms) || 5000
        );
        return copy;
    }

    function remainingMilliseconds(contract, cap) {
        var remaining = Math.max(
            0,
            Number(contract && contract.operation_deadline_ms) - Date.now()
        );
        return cap == null ? remaining : Math.min(remaining, Number(cap));
    }

    function field(contract, name) {
        var item = contract && contract.fields && contract.fields[name];
        return item ? document.querySelector(item.selector) : null;
    }

    function formItemFor(element) {
        return element && element.closest
            ? element.closest(".ant-form-item, [role='group'], .form-group")
            : null;
    }

    function selectedCaseText(input) {
        var item = formItemFor(input) || input.parentElement;
        if (!item) return normalizeExactText(input.value);
        var selected = item.querySelector(
            ".ant-select-selection-item, [aria-selected='true'], [data-selected-value]"
        );
        return normalizeExactText(
            selected
                ? (selected.getAttribute("title") || selected.textContent)
                : input.value
        );
    }

    async function openEntryForm(contract) {
        var selector = contract && contract.form_selector;
        var form = selector ? document.querySelector(selector) : null;
        if (!form) form = await waitFor(function () {
            return selector ? document.querySelector(selector) : null;
        }, Math.max(1, remainingMilliseconds(contract, 5000)));
        return form && visible(form)
            ? result(true)
            : result(false, "page_contract_changed");
    }

    function fillAndVerify(name, value, contract) {
        var input = field(contract, name);
        if (!input || !visible(input)) return result(false, "page_contract_changed");
        var set = nativeSet(input, value);
        if (!set.ok) return set;
        return String(input.value) === String(value)
            ? result(true)
            : result(false, name + "_verification_failed");
    }

    function ignoredRequiredFieldsReady(contract) {
        var ignored = contract.ignored_fields || [];
        for (var index = 0; index < ignored.length; index += 1) {
            var input = document.querySelector(ignored[index].selector);
            if (!input) continue;
            var item = formItemFor(input);
            var required = input.getAttribute("aria-required") === "true"
                || !!(item && item.querySelector(".ant-form-item-required, [aria-required='true']"));
            if (!required) continue;
            var selected = item && item.querySelector(".ant-select-selection-item, [data-selected-value]");
            if (!normalizeExactText(selected ? selected.textContent : input.value)) {
                return false;
            }
        }
        return true;
    }

    function removeCompactMode() {
        if (compactObserver) {
            compactObserver.disconnect();
            compactObserver = null;
        }
        document.documentElement.removeAttribute(ROOT_ATTRIBUTE);
        Array.prototype.forEach.call(
            document.querySelectorAll("[" + HIDDEN_ATTRIBUTE + "]"),
            function (node) { node.removeAttribute(HIDDEN_ATTRIBUTE); }
        );
        var toolbar = document.getElementById(TOOLBAR_ID);
        if (toolbar) toolbar.remove();
        return result(true);
    }

    function makeToolbar(contract) {
        var existing = document.getElementById(TOOLBAR_ID);
        if (existing) return existing;
        var toolbar = document.createElement("div");
        toolbar.id = TOOLBAR_ID;
        toolbar.setAttribute("role", "toolbar");
        var label = document.createElement("span");
        label.textContent = "已从 WorkTrace 填入";
        toolbar.appendChild(label);
        [
            ["重新填入", function () { if (lastPayload && lastContract) fillEntry(lastPayload, lastContract); }],
            ["复制描述", function () {
                if (lastPayload && navigator.clipboard) navigator.clipboard.writeText(lastPayload.narrative);
            }],
            ["显示完整页面", removeCompactMode],
            ["关闭", function () { window.close(); }]
        ].forEach(function (definition) {
            var button = document.createElement("button");
            button.type = "button";
            button.textContent = definition[0];
            button.addEventListener("click", definition[1]);
            toolbar.appendChild(button);
        });
        document.body.insertBefore(toolbar, document.body.firstChild);
        return toolbar;
    }

    function installCompactMode(contract) {
        if (!ignoredRequiredFieldsReady(contract)) {
            removeCompactMode();
            return result(false, "ignored_required_field_missing");
        }
        var form = document.querySelector(contract.form_selector);
        if (!form) return result(false, "page_contract_changed");
        var keep = [];
        Object.keys(contract.fields).forEach(function (name) {
            var input = field(contract, name);
            var item = formItemFor(input);
            if (item) keep.push(item);
        });
        Array.prototype.forEach.call(form.querySelectorAll(".ant-form-item"), function (item) {
            if (keep.indexOf(item) < 0) item.setAttribute(HIDDEN_ATTRIBUTE, "true");
        });
        var childOnPath = form;
        var ancestor = form.parentElement;
        while (ancestor && ancestor !== document.body) {
            Array.prototype.forEach.call(ancestor.children, function (child) {
                if (child !== childOnPath) child.setAttribute(HIDDEN_ATTRIBUTE, "true");
            });
            childOnPath = ancestor;
            ancestor = ancestor.parentElement;
        }
        if (document.body) {
            Array.prototype.forEach.call(document.body.children, function (child) {
                if (child !== childOnPath && child.id !== TOOLBAR_ID) {
                    child.setAttribute(HIDDEN_ATTRIBUTE, "true");
                }
            });
        }
        if (!document.getElementById(STYLE_ID)) {
            var style = document.createElement("style");
            style.id = STYLE_ID;
            style.textContent =
                "html[" + ROOT_ATTRIBUTE + "='true'] [" + HIDDEN_ATTRIBUTE + "]" +
                "{display:none!important;}" +
                "#" + TOOLBAR_ID + "{display:flex;gap:8px;align-items:center;padding:10px;" +
                "position:sticky;top:0;z-index:2147483647;background:#fff;border-bottom:1px solid #ddd;}";
            document.head.appendChild(style);
        }
        document.documentElement.setAttribute(ROOT_ATTRIBUTE, "true");
        makeToolbar(contract);
        compactObserver = new MutationObserver(function () {
            if (
                document.querySelector(".ant-form-item-has-error, [aria-invalid='true']")
                || !ignoredRequiredFieldsReady(contract)
            ) {
                removeCompactMode();
            }
        });
        compactObserver.observe(form, { childList: true, subtree: true, attributes: true });
        return result(true);
    }

    function detectPage() {
        return /\/Works\/WorkHourList(?:$|[?#])/i.test(window.location.href)
            ? "WORK_HOUR_LIST"
            : "UNKNOWN";
    }

    function lookupState(popup, contract) {
        var options = Array.prototype.filter.call(
            popup.querySelectorAll("[role='option']"),
            visible
        );
        var texts = options.map(function (option) {
            return normalizeExactText(option.getAttribute("title") || option.textContent);
        });
        var empty = Array.prototype.find.call(
            popup.querySelectorAll("div,span,p"),
            function (element) {
                return visible(element)
                    && normalizeExactText(element.textContent) === contract.empty_text;
            }
        );
        var loading = Array.prototype.find.call(
            popup.querySelectorAll("[aria-busy='true'],.ant-spin-spinning,.ant-select-item-empty .ant-spin"),
            visible
        );
        return {
            options: options,
            signature: texts.join("\u001f"),
            count: options.length,
            empty: !!empty,
            loading: !!loading
        };
    }

    function caseFieldContract(contract) {
        return contract && (contract.field || (contract.fields && contract.fields.case_number));
    }

    function caseDiagnostics(input, popup, extra) {
        return Object.assign({
            document_visibility: String(document.visibilityState || "unknown"),
            viewport_available: Number(window.innerWidth || 0) > 0 && Number(window.innerHeight || 0) > 0,
            input_exists: !!input,
            input_interactive: !!(input && !input.disabled && !input.readOnly),
            popup_exists: !!popup,
            popup_interactive: !!(popup && visible(popup))
        }, extra || {});
    }

    function caseFailure(error, input, popup, extra) {
        return result(false, error, caseDiagnostics(input, popup, extra));
    }

    function requestFrame() {
        return new Promise(function (resolve) {
            var raf = window.requestAnimationFrame || (typeof requestAnimationFrame === "function" && requestAnimationFrame);
            if (raf) raf.call(window, function () { resolve(); });
            else setTimeout(resolve, 16);
        });
    }

    function blockingOverlayVisible() {
        return Array.prototype.some.call(
            document.querySelectorAll(
                ".ant-spin-spinning,.ant-modal-mask,.ant-drawer-mask,[data-loading='true']"
            ),
            visible
        );
    }

    function popupForInput(input) {
        var controlsId = normalizeExactText(input && input.getAttribute("aria-controls"));
        return controlsId && document.getElementById
            ? document.getElementById(controlsId)
            : null;
    }

    async function prepareCaseCombobox(contract, generation) {
        if (generation !== lookupGeneration) return result(false, "lookup_superseded");
        if (detectPage() !== "WORK_HOUR_LIST") return result(false, "page_contract_changed");
        if (!contract || contract.version !== 4 || !caseFieldContract(contract)) {
            return result(false, "page_contract_changed");
        }
        var input = document.querySelector(caseFieldContract(contract).selector);
        if (!input) return caseFailure("case_input_missing", null, null);
        if (input.disabled || input.readOnly) {
            return caseFailure("case_input_not_interactive", input, null);
        }
        if (
            String(document.visibilityState || "visible") !== "visible"
            || Number(window.innerWidth || 0) <= 0
            || Number(window.innerHeight || 0) <= 0
            || !visible(input)
        ) return caseFailure("case_input_not_rendered", input, null);
        if (blockingOverlayVisible()) {
            return caseFailure("case_input_not_interactive", input, null);
        }
        var controlsId = normalizeExactText(input.getAttribute("aria-controls"));
        if (!controlsId) return caseFailure("case_aria_controls_missing", input, null);
        if (typeof input.focus === "function") input.focus();
        if (typeof input.click === "function") input.click();
        var popupWait = remainingMilliseconds(
            contract,
            Math.max(1, Number(contract.popup_timeout_ms) || 3000)
        );
        if (popupWait <= 0) return caseFailure("case_popup_not_created", input, null);
        var popup = await waitFor(function () {
            if (generation !== lookupGeneration) return null;
            var candidate = popupForInput(input);
            return candidate && candidate.getAttribute("role") === "listbox" && visible(candidate)
                ? candidate : null;
        }, Math.max(1, popupWait));
        if (generation !== lookupGeneration) return result(false, "lookup_superseded");
        if (!popup) {
            var candidate = popupForInput(input);
            return candidate
                ? caseFailure("case_popup_not_interactive", input, candidate)
                : caseFailure("case_popup_not_created", input, null);
        }
        return result(true, "", { input: input, popup: popup });
    }

    async function interactiveHandshake(contract) {
        contract = startOperationDeadline(contract);
        var generation = ++lookupGeneration;
        var prepared = await prepareCaseCombobox(contract, generation);
        if (!prepared.ok) return prepared;
        await requestFrame();
        await requestFrame();
        if (generation !== lookupGeneration) return result(false, "lookup_superseded");
        var input = prepared.input;
        var popup = popupForInput(input);
        if (
            !input || input.disabled || input.readOnly || !visible(input)
            || !popup || !visible(popup) || blockingOverlayVisible()
        ) return caseFailure("case_input_not_interactive", input, popup);
        return result(true, "", caseDiagnostics(input, popup, { phase: "work_interactive" }));
    }

    async function lookupCaseOptions(input, query, contract, generation, initialPopup) {
        return new Promise(function (resolve) {
            var settled = false;
            var popup = initialPopup;
            var before = lookupState(popup, contract);
            var evidence = query === "";
            var loadingObserved = before.loading;
            var loadingFinished = false;
            var clearedObserved = before.count > 0 && before.count === 0;
            var stabilityTimer = null;
            var observer = null;
            var timeoutTimer = null;
            var stabilityMs = Math.max(150, Math.min(250, Number(contract.stability_ms) || 200));

            function finish(value) {
                if (settled) return;
                settled = true;
                if (observer) observer.disconnect();
                clearTimeout(stabilityTimer);
                clearTimeout(timeoutTimer);
                resolve(value);
            }

            function currentSnapshot() {
                var currentPopup = popupForInput(input);
                if (!currentPopup || !visible(currentPopup)) return null;
                var identityChanged = currentPopup !== popup;
                if (identityChanged) popup = currentPopup;
                return { popup: currentPopup, identityChanged: identityChanged, state: lookupState(currentPopup, contract) };
            }

            function scheduleStable(snapshot) {
                clearTimeout(stabilityTimer);
                stabilityTimer = setTimeout(async function () {
                    await delay(stabilityMs);
                    if (generation !== lookupGeneration) {
                        finish(result(false, "lookup_superseded"));
                        return;
                    }
                    var stable = currentSnapshot();
                    if (!stable || stable.popup !== snapshot.popup) return;
                    if (
                        stable.state.signature !== snapshot.state.signature
                        || stable.state.count !== snapshot.state.count
                        || stable.state.empty !== snapshot.state.empty
                        || stable.state.loading
                    ) return;
                    if (query !== "" && (!evidence || String(input.value) !== query)) return;
                    if (!stable.state.count && !stable.state.empty) return;
                    finish({
                        ok: true,
                        state: stable.state,
                        popup: stable.popup,
                        recent: query === "",
                        loading_observed: loadingObserved
                    });
                }, 0);
            }

            function inspect() {
                if (generation !== lookupGeneration) {
                    finish(result(false, "lookup_superseded"));
                    return;
                }
                var snapshot = currentSnapshot();
                if (!snapshot) return;
                var state = snapshot.state;
                if (state.loading) loadingObserved = true;
                if (loadingObserved && !state.loading) loadingFinished = true;
                if (!state.count && !state.empty && before.count) clearedObserved = true;
                if (
                    snapshot.identityChanged
                    || state.signature !== before.signature
                    || state.count !== before.count
                    || state.empty !== before.empty
                    || loadingFinished
                    || (clearedObserved && (state.count || state.empty))
                ) evidence = true;
                if (!state.loading && (state.count || state.empty) && (query === "" || evidence)) {
                    scheduleStable(snapshot);
                }
            }

            observer = new MutationObserver(function () { inspect(); });
            observer.observe(document.documentElement, {
                childList: true,
                subtree: true,
                attributes: true,
                characterData: true
            });
            var lookupWait = remainingMilliseconds(contract);
            if (lookupWait <= 0) {
                finish(caseFailure("case_results_timeout", input, popup));
                return;
            }
            timeoutTimer = setTimeout(function () {
                finish(caseFailure(
                    query !== "" && !evidence && before.count
                        ? "case_results_stale" : "case_results_timeout",
                    input,
                    popup,
                    { loading_observed: loadingObserved, result_count: before.count }
                ));
            }, Math.max(1, lookupWait));

            if (query !== "") {
                var setResult = setSearchValue(input, query);
                if (!setResult.ok || String(input.value) !== query) {
                    finish(caseFailure("case_query_not_applied", input, popup));
                    return;
                }
            }
            inspect();
        });
    }

    async function selectExactCase(input, expected, contract, generation, preparedPopup) {
        var lookup = await lookupCaseOptions(
            input,
            String(expected),
            contract,
            generation,
            preparedPopup
        );
        if (!lookup || lookup.ok === false) return lookup || result(false, "case_results_timeout");
        var normalized = normalizeExactText(expected);
        var exact = lookup.state.options.filter(function (option) {
            return normalizeExactText(option.getAttribute("title") || option.textContent) === normalized;
        });
        if (exact.length === 0) return result(false, "case_not_found");
        if (exact.length !== 1) return result(false, "case_ambiguous");
        exact[0].click();
        var selectionWait = remainingMilliseconds(contract, 3000);
        if (selectionWait <= 0) return result(false, "case_results_timeout");
        var accepted = await waitFor(function () {
            return selectedCaseText(input) === normalized;
        }, Math.max(1, selectionWait));
        if (!accepted || selectedCaseText(input) !== normalized) {
            return result(false, "case_selection_mismatch");
        }
        return result(true);
    }

    async function fillCaseNumber(caseNumber, contract, generation) {
        contract = contract && contract.operation_deadline_ms
            ? contract : startOperationDeadline(contract);
        generation = Number.isInteger(generation) ? generation : ++lookupGeneration;
        var prepared = await prepareCaseCombobox(contract, generation);
        if (!prepared.ok) return prepared;
        var selected = await selectExactCase(
            prepared.input,
            normalizeExactText(caseNumber),
            contract,
            generation,
            prepared.popup
        );
        if (selected.ok) selected.generation = generation;
        return selected;
    }

    async function searchCases(query, contract) {
        contract = startOperationDeadline(contract);
        query = String(query == null ? "" : query);
        var generation = ++lookupGeneration;
        var prepared = await prepareCaseCombobox(contract, generation);
        if (!prepared.ok) return prepared;
        var input = prepared.input;
        try {
            var lookup = await lookupCaseOptions(input, query, contract, generation, prepared.popup);
            if (!lookup || lookup.ok === false) return lookup || result(false, "case_results_timeout");
            var state = lookup.state;
            var stableEmpty = state.empty && state.count === 0;
            if (stableEmpty) return result(true, "", { labels: [], loading_observed: lookup.loading_observed });
            var texts = state.options.map(function (option) {
                return String(option.innerText || option.textContent || "");
            });
            var normalized = normalizeCaseLabels(texts, contract.max_options, contract.max_label_length);
            if (normalized.ok) normalized.loading_observed = lookup.loading_observed;
            return normalized;
        } finally {
            if (generation === lookupGeneration) {
                setSearchValue(input, "");
                if (typeof input.dispatchEvent === "function" && typeof KeyboardEvent === "function") {
                    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
                }
                if (typeof input.blur === "function") input.blur();
            }
        }
    }

    function verifyEntry(payload, contract) {
        var expected = {
            work_date: payload.work_date,
            duration_hours: payload.duration_hours,
            narrative: payload.narrative
        };
        var names = Object.keys(expected);
        for (var index = 0; index < names.length; index += 1) {
            var input = field(contract, names[index]);
            if (!input || String(input.value) !== String(expected[names[index]])) {
                return result(false, names[index] + "_verification_failed");
            }
        }
        var caseInput = field(contract, "case_number");
        if (!caseInput || selectedCaseText(caseInput) !== normalizeExactText(payload.case_number)) {
            return result(false, "case_selection_mismatch");
        }
        return result(true);
    }

    async function fillEntry(payload, contract) {
        contract = startOperationDeadline(contract);
        var generation = ++lookupGeneration;
        removeCompactMode();
        if (detectPage() !== "WORK_HOUR_LIST") return result(false, "page_contract_changed");
        lastPayload = Object.freeze(Object.assign({}, payload));
        lastContract = contract;
        var opened = await openEntryForm(contract);
        if (!opened.ok) return opened;
        if (generation !== lookupGeneration) return result(false, "lookup_superseded");
        var caseResult = await fillCaseNumber(payload.case_number, contract, generation);
        if (!caseResult.ok) return caseResult;
        if (generation !== lookupGeneration) return result(false, "lookup_superseded");
        if (remainingMilliseconds(contract) <= 0) return result(false, "page_operation_timeout");
        var dateResult = fillAndVerify("work_date", payload.work_date, contract);
        if (!dateResult.ok) return dateResult;
        if (generation !== lookupGeneration) return result(false, "lookup_superseded");
        var durationResult = fillAndVerify("duration_hours", payload.duration_hours, contract);
        if (!durationResult.ok) return durationResult;
        if (generation !== lookupGeneration) return result(false, "lookup_superseded");
        var narrativeResult = fillAndVerify("narrative", payload.narrative, contract);
        if (!narrativeResult.ok) return narrativeResult;
        var verified = verifyEntry(payload, contract);
        if (!verified.ok) return verified;
        var ignoredReady = ignoredRequiredFieldsReady(contract)
            || await waitFor(function () {
                return ignoredRequiredFieldsReady(contract);
            }, Math.max(1, remainingMilliseconds(contract, 3000)));
        if (!ignoredReady) return result(false, "ignored_required_field_missing");
        return installCompactMode(contract);
    }

    window.WorkTraceFDWorkAdapter = Object.freeze({
        version: 4,
        detectPage: detectPage,
        installCompactMode: installCompactMode,
        removeCompactMode: removeCompactMode,
        openEntryForm: openEntryForm,
        interactiveHandshake: interactiveHandshake,
        prepareCaseCombobox: prepareCaseCombobox,
        lookupCaseOptions: lookupCaseOptions,
        selectExactCase: selectExactCase,
        fillCaseNumber: fillCaseNumber,
        fillWorkDate: function (value, contract) { return fillAndVerify("work_date", value, contract); },
        fillDuration: function (value, contract) { return fillAndVerify("duration_hours", value, contract); },
        fillNarrative: function (value, contract) { return fillAndVerify("narrative", value, contract); },
        verifyEntry: verifyEntry,
        searchCases: searchCases,
        fillEntry: fillEntry,
        _test: Object.freeze({
            normalizeExactText: normalizeExactText,
            normalizeCaseLabels: normalizeCaseLabels,
            visible: visible,
            exactMatches: function (texts, expected) {
                var normalized = normalizeExactText(expected);
                return texts.filter(function (text) {
                    return normalizeExactText(text) === normalized;
                });
            }
        })
    });
    if (typeof window.addEventListener === "function") {
        window.addEventListener("pagehide", function () { lookupGeneration += 1; });
    }
})();
