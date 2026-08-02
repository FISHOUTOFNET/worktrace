(function () {
    "use strict";
    if (window.WorkTraceFDWorkAdapter && window.WorkTraceFDWorkAdapter.version === 2) return;

    var ROOT_ATTRIBUTE = "data-worktrace-fdwork-compact";
    var HIDDEN_ATTRIBUTE = "data-worktrace-fdwork-hidden";
    var STYLE_ID = "worktrace-fdwork-compact-style";
    var TOOLBAR_ID = "worktrace-fdwork-toolbar";
    var lastPayload = null;
    var lastContract = null;
    var compactObserver = null;

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
        }, 5000);
        return form && visible(form)
            ? result(true)
            : result(false, "page_contract_changed");
    }

    async function fillCaseNumber(caseNumber, contract) {
        var input = field(contract, "case_number");
        if (!input || !visible(input)) return result(false, "page_contract_changed");
        input.focus();
        if (typeof input.click === "function") input.click();
        var set = nativeSet(input, caseNumber);
        if (!set.ok) return set;

        var listSelector = contract.fields.case_number.listbox;
        var listbox = await waitFor(function () {
            return document.querySelector(listSelector) || document.querySelector("[role='listbox']");
        }, 5000);
        if (!listbox) return result(false, "case_search_timeout");

        var loaded = await waitFor(function () {
            return listbox.querySelectorAll("[role='option']").length
                || normalizeExactText(listbox.textContent) === "暂无数据";
        }, 5000);
        if (!loaded) return result(false, "case_search_timeout");
        var options = Array.prototype.filter.call(
            listbox.querySelectorAll("[role='option']"),
            visible
        );
        var expected = normalizeExactText(caseNumber);
        var exact = options.filter(function (option) {
            return normalizeExactText(
                option.getAttribute("title") || option.textContent
            ) === expected;
        });
        if (exact.length === 0) return result(false, "case_not_found");
        if (exact.length !== 1) return result(false, "case_ambiguous");
        exact[0].click();
        var accepted = await waitFor(function () {
            return selectedCaseText(input) === expected;
        }, 3000);
        if (!accepted || selectedCaseText(input) !== expected) {
            return result(false, "case_selection_mismatch");
        }
        return result(true);
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

    async function searchCases(query, contract) {
        if (detectPage() !== "WORK_HOUR_LIST") return result(false, "page_contract_changed");
        if (!contract || !contract.field || contract.version !== 2) {
            return result(false, "page_contract_changed");
        }
        var input = document.querySelector(contract.field.selector);
        if (!input || !visible(input)) return result(false, "page_contract_changed");
        var controlsId = normalizeExactText(input.getAttribute("aria-controls"));
        if (!controlsId) return result(false, "page_contract_changed");
        var popup = null;
        try {
            if (typeof input.focus === "function") input.focus();
            var setResult = setSearchValue(input, query);
            if (!setResult.ok) return setResult;
            popup = await waitFor(function () {
                var candidate = document.getElementById(controlsId);
                return candidate && candidate.getAttribute("role") === "listbox" && visible(candidate)
                    ? candidate
                    : null;
            }, 5000);
            if (!popup) return result(false, "page_contract_changed");
            var state = await waitFor(function () {
                var options = Array.prototype.filter.call(
                    popup.querySelectorAll("[role='option']"),
                    visible
                );
                if (options.length) return { options: options };
                var empty = Array.prototype.find.call(
                    popup.querySelectorAll("div,span,p"),
                    function (element) {
                        return visible(element)
                            && normalizeExactText(element.textContent) === contract.empty_text;
                    }
                );
                return empty ? { empty: true } : null;
            }, 5000);
            if (!state) return result(false, "case_not_found");
            if (state.empty) {
                await delay(120);
                var lateOptions = Array.prototype.filter.call(
                    popup.querySelectorAll("[role='option']"),
                    visible
                );
                if (lateOptions.length) state = { options: lateOptions };
                else {
                    var stableEmpty = Array.prototype.find.call(
                        popup.querySelectorAll("div,span,p"),
                        function (element) {
                            return visible(element)
                                && normalizeExactText(element.textContent) === contract.empty_text;
                        }
                    );
                    if (!stableEmpty) return result(false, "page_contract_changed");
                    return result(true, "", { labels: [] });
                }
            }
            var texts = state.options.map(function (option) {
                return String(option.innerText || option.textContent || "");
            });
            return normalizeCaseLabels(texts, contract.max_options, contract.max_label_length);
        } finally {
            setSearchValue(input, "");
            if (typeof input.dispatchEvent === "function" && typeof KeyboardEvent === "function") {
                input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
            }
            if (typeof input.blur === "function") input.blur();
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
        removeCompactMode();
        if (detectPage() !== "WORK_HOUR_LIST") return result(false, "page_contract_changed");
        lastPayload = Object.freeze(Object.assign({}, payload));
        lastContract = contract;
        var opened = await openEntryForm(contract);
        if (!opened.ok) return opened;
        var caseResult = await fillCaseNumber(payload.case_number, contract);
        if (!caseResult.ok) return caseResult;
        var dateResult = fillAndVerify("work_date", payload.work_date, contract);
        if (!dateResult.ok) return dateResult;
        var durationResult = fillAndVerify("duration_hours", payload.duration_hours, contract);
        if (!durationResult.ok) return durationResult;
        var narrativeResult = fillAndVerify("narrative", payload.narrative, contract);
        if (!narrativeResult.ok) return narrativeResult;
        var verified = verifyEntry(payload, contract);
        if (!verified.ok) return verified;
        var ignoredReady = ignoredRequiredFieldsReady(contract)
            || await waitFor(function () {
                return ignoredRequiredFieldsReady(contract);
            }, 3000);
        if (!ignoredReady) return result(false, "ignored_required_field_missing");
        return installCompactMode(contract);
    }

    window.WorkTraceFDWorkAdapter = Object.freeze({
        version: 2,
        detectPage: detectPage,
        installCompactMode: installCompactMode,
        removeCompactMode: removeCompactMode,
        openEntryForm: openEntryForm,
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
})();
