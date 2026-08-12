// WorkTrace shared UI primitives: focus management, Drawer, Dialog, Toast, Tooltip, and project autocomplete.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var dialogLayer = document.getElementById("confirm-dialog-layer");
    var dialog = document.getElementById("confirm-dialog");
    var dialogTitle = document.getElementById("confirm-dialog-title");
    var dialogBody = document.getElementById("confirm-dialog-body");
    var dialogPrimary = document.getElementById("confirm-dialog-primary");
    var dialogSecondary = document.getElementById("confirm-dialog-secondary");
    var tooltip = document.getElementById("app-tooltip");
    var dialogState = null;
    var toastTimer = null;
    var tooltipTarget = null;
    var PROJECT_AUTOCOMPLETE_LIMIT = 10;

    function isWithinHiddenAncestor(element) {
        var node = element;
        while (node && node !== document.body) {
            if (node.hidden) return true;
            if (node.getAttribute && node.getAttribute("aria-hidden") === "true") return true;
            node = node.parentNode;
        }
        return false;
    }

    function hasVisibleLayoutBox(element) {
        if (typeof element.getClientRects === "function") {
            try {
                if (element.getClientRects().length === 0) return false;
            } catch (error) {
                // Fall through to offsetParent fallback for test environments.
            }
        } else if (typeof element.offsetParent !== "undefined") {
            return element.offsetParent !== null;
        }
        return true;
    }

    function focusable(container) {
        if (!container) return [];
        return Array.prototype.slice.call(container.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), select:not([disabled]), '
            + 'textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
        )).filter(function (element) {
            return !isWithinHiddenAncestor(element) && hasVisibleLayoutBox(element);
        });
    }
    App.focusableElements = focusable;

    function trapFocus(event, container) {
        if (event.key !== "Tab") return;
        var items = focusable(container);
        if (!items.length) return;
        var first = items[0];
        var last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    }
    App.trapFocus = trapFocus;

    function restoreFocus(target) {
        if (target && document.documentElement.contains(target)
                && typeof target.focus === "function") target.focus();
    }

    App.openManagedDrawer = function (layer, trigger, initialFocus, options) {
        if (!layer) return;
        options = typeof options === "function" ? { requestClose: options } : (options || {});
        layer._returnFocus = trigger || document.activeElement;
        layer._requestClose = typeof options.requestClose === "function"
            ? options.requestClose : null;
        layer.hidden = false;
        var target = initialFocus || focusable(layer)[0];
        if (target) target.focus();
    };

    App.closeManagedDrawer = function (layer, options) {
        if (!layer) return;
        options = options || {};
        var target = layer._returnFocus;
        layer.hidden = true;
        layer._returnFocus = null;
        layer._requestClose = null;
        if (options.restoreFocus !== false) restoreFocus(target);
    };

    function normalizedDialogChoices(options) {
        if (!Array.isArray(options.choices)) return [];
        return options.choices.filter(function (choice) {
            return choice && typeof choice.value === "string" && choice.value
                && typeof choice.label === "string" && choice.label;
        });
    }

    function renderDialogChoices(options) {
        var choices = normalizedDialogChoices(options);
        if (!choices.length) return;
        var group = document.createElement("div");
        group.className = "dialog-choice-group";
        group.setAttribute("role", "radiogroup");
        choices.forEach(function (choice) {
            var row = document.createElement("label");
            row.className = "dialog-choice-row";
            var input = document.createElement("input");
            input.type = "radio";
            input.name = "confirm-dialog-choice";
            input.value = choice.value;
            var selected = dialogState.choice || options.defaultChoice || choices[0].value;
            input.checked = choice.value === selected;
            if (input.checked) dialogState.choice = choice.value;
            input.addEventListener("change", function () {
                if (input.checked && dialogState) dialogState.choice = choice.value;
            });
            var copy = document.createElement("span");
            copy.className = "dialog-choice-copy";
            var title = document.createElement("span");
            title.className = "dialog-choice-title";
            title.textContent = choice.label;
            copy.appendChild(title);
            if (choice.description) {
                var description = document.createElement("span");
                description.className = "field-hint";
                description.textContent = String(choice.description);
                copy.appendChild(description);
            }
            row.appendChild(input);
            row.appendChild(copy);
            group.appendChild(row);
        });
        dialogBody.appendChild(group);
    }

    function renderDialogStep() {
        if (!dialogState) return;
        var options = dialogState.options;
        var second = dialogState.step === 2;
        dialogTitle.textContent = second
            ? (options.secondTitle || "确认操作")
            : (options.title || "确认操作");
        dialogBody.innerHTML = "";
        if (second && options.secondIntro) {
            var secondIntro = document.createElement("p");
            secondIntro.textContent = options.secondIntro;
            dialogBody.appendChild(secondIntro);
        }
        if (options.objectLabel) {
            var object = document.createElement("div");
            object.className = "dialog-object";
            object.textContent = options.objectLabel;
            dialogBody.appendChild(object);
        }
        if (!second && options.warning) {
            var warning = document.createElement("p");
            warning.className = "dialog-warning";
            warning.textContent = options.warning;
            dialogBody.appendChild(warning);
        }
        if (!second) renderDialogChoices(options);
        dialogSecondary.textContent = second ? "返回" : "取消";
        dialogPrimary.textContent = second
            ? (options.confirmLabel || "确认")
            : (options.twoStep === true ? "继续" : (options.confirmLabel || "确认"));
        dialogPrimary.classList.toggle(
            "danger",
            second || (options.twoStep !== true && options.danger === true)
        );
        dialogSecondary.focus();
    }

    function finishDialog(confirmed) {
        if (!dialogState) return;
        var state = dialogState;
        dialogState = null;
        dialogLayer.hidden = true;
        restoreFocus(state.returnFocus);
        if (!confirmed) {
            state.resolve(false);
            return;
        }
        var choices = normalizedDialogChoices(state.options);
        state.resolve(choices.length ? (state.choice || choices[0].value) : true);
    }

    App.openConfirmDialog = function (options) {
        options = Object.assign({}, options || {});
        if (dialogState) return Promise.resolve(false);
        return new Promise(function (resolve) {
            dialogState = {
                options: options,
                step: 1,
                choice: options.defaultChoice || null,
                returnFocus: options.trigger || document.activeElement,
                resolve: resolve
            };
            dialogLayer.hidden = false;
            renderDialogStep();
        });
    };

    App.openDeleteDialog = function (options) {
        return App.openConfirmDialog(Object.assign({
            title: "确认删除",
            secondTitle: "确认删除",
            secondIntro: "此操作不可撤销。",
            confirmLabel: "删除",
            twoStep: true,
            danger: true
        }, options || {}));
    };

    if (dialogPrimary) dialogPrimary.addEventListener("click", function () {
        if (!dialogState) return;
        if (dialogState.options.twoStep === true && dialogState.step === 1) {
            dialogState.step = 2;
            renderDialogStep();
            return;
        }
        finishDialog(true);
    });
    if (dialogSecondary) dialogSecondary.addEventListener("click", function () {
        if (!dialogState) return;
        if (dialogState.step === 2) {
            dialogState.step = 1;
            renderDialogStep();
            return;
        }
        finishDialog(false);
    });
    if (dialogLayer) dialogLayer.addEventListener("click", function (event) {
        if (event.target === dialogLayer) finishDialog(false);
    });

    App.showToast = function (message) {
        var toast = document.getElementById("app-toast");
        if (!toast) return;
        clearTimeout(toastTimer);
        var copy = String(message || "");
        toast.textContent = copy;
        toast.hidden = !copy;
        if (copy) toastTimer = setTimeout(function () {
            toast.hidden = true;
            toast.textContent = "";
        }, 3200);
    };

    function normalizedProjectSearchText(value) {
        return String(value || "").trim().toLocaleLowerCase();
    }

    function projectNameOrder(left, right) {
        return String((left && left.name) || "").localeCompare(
            String((right && right.name) || ""),
            "zh-Hans-CN",
            { sensitivity: "base" }
        );
    }

    function projectAutocompleteCandidates(projects, query) {
        var list = (Array.isArray(projects) ? projects : []).filter(function (project) {
            return project && parseInt(project.id, 10) > 0 && String(project.name || "").trim();
        });
        var normalized = normalizedProjectSearchText(query);
        if (normalized) {
            return list.filter(function (project) {
                return normalizedProjectSearchText(project.name).indexOf(normalized) >= 0
                    || normalizedProjectSearchText(project.description).indexOf(normalized) >= 0;
            }).sort(projectNameOrder).slice(0, PROJECT_AUTOCOMPLETE_LIMIT);
        }
        return list.filter(function (project) {
            return !!String(project.last_used_at || "").trim();
        }).sort(function (left, right) {
            var leftUsed = String(left.last_used_at || "");
            var rightUsed = String(right.last_used_at || "");
            if (leftUsed !== rightUsed) return leftUsed < rightUsed ? 1 : -1;
            return projectNameOrder(left, right);
        }).slice(0, PROJECT_AUTOCOMPLETE_LIMIT);
    }
    App.projectAutocompleteCandidates = projectAutocompleteCandidates;

    function projectCatalogForSelect(select) {
        if (!select) return [];
        var catalog = App.projectCatalog;
        if (select.id === "edit-project-select") {
            var editing = catalog && typeof catalog.getEditing === "function"
                ? catalog.getEditing()
                : (App.editingProjectsCache || App.projectsCache || []);
            return editing.filter(function (project) {
                return String((project && project.name) || "") !== "未归类";
            });
        }
        if (catalog && typeof catalog.getFilter === "function") return catalog.getFilter();
        return App.filterProjectsCache || [];
    }

    function sourceOptionLabel(option) {
        if (!option) return "";
        return String(option.textContent || option.text || "").trim();
    }

    function selectedSourceLabel(select) {
        if (!select || !select.options || select.selectedIndex < 0) return "";
        return sourceOptionLabel(select.options[select.selectedIndex]);
    }

    function findSourceOption(select, predicate) {
        if (!select || !select.options) return null;
        for (var i = 0; i < select.options.length; i++) {
            if (predicate(select.options[i])) return select.options[i];
        }
        return null;
    }

    function specialCandidates(select) {
        var result = [];
        if (!select) return result;
        if (select.id === "edit-project-select") {
            var uncategorized = findSourceOption(select, function (option) {
                return sourceOptionLabel(option) === "未归类";
            });
            if (uncategorized) {
                result.push({
                    value: String(uncategorized.value || ""),
                    name: "未归类",
                    description: "",
                    special: true
                });
            }
            return result;
        }
        var allProjects = findSourceOption(select, function (option) {
            return String(option.value || "") === "" && sourceOptionLabel(option) === "全部项目";
        });
        var unclassified = findSourceOption(select, function (option) {
            return String(option.value || "") === "unclassified";
        });
        if (allProjects) {
            result.push({
                value: "",
                name: sourceOptionLabel(allProjects),
                description: "",
                special: true
            });
        }
        if (unclassified) {
            result.push({
                value: "unclassified",
                name: sourceOptionLabel(unclassified) || "未归类",
                description: "",
                special: true
            });
        }
        return result;
    }

    function optionForProject(project) {
        return {
            value: String(project.id || ""),
            name: String(project.name || ""),
            description: String(project.description || ""),
            special: false
        };
    }

    function enhanceProjectSelect(select) {
        if (!select || String(select.tagName || "").toUpperCase() !== "SELECT") return null;
        if (select._projectAutocomplete) return select._projectAutocomplete;
        if (!document.createElement || !select.parentNode) return null;

        var shell = document.createElement("span");
        shell.className = "project-autocomplete-shell";
        if (select.id !== "edit-project-select") shell.classList.add("project-autocomplete-filter");

        var input = document.createElement("input");
        input.type = "text";
        input.autocomplete = "off";
        input.spellcheck = false;
        input.className = "project-autocomplete-input";
        input.id = select.id + "-input";
        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");

        var menu = document.createElement("div");
        menu.className = "project-autocomplete-menu";
        menu.id = select.id + "-suggestions";
        menu.setAttribute("role", "listbox");
        menu.hidden = true;
        input.setAttribute("aria-controls", menu.id);

        shell.appendChild(input);
        shell.appendChild(menu);
        select.parentNode.insertBefore(shell, select.nextSibling);
        select.hidden = true;
        select.setAttribute("aria-hidden", "true");
        select.tabIndex = -1;

        if (document.querySelectorAll) {
            Array.prototype.forEach.call(
                document.querySelectorAll('label[for="' + select.id + '"]'),
                function (label) { label.setAttribute("for", input.id); }
            );
        }
        if (select.closest) {
            var wrappingLabel = select.closest("label");
            if (wrappingLabel) wrappingLabel.setAttribute("for", input.id);
        }

        var state = {
            select: select,
            shell: shell,
            input: input,
            menu: menu,
            items: [],
            activeIndex: -1,
            dirty: false
        };
        select._projectAutocomplete = state;

        function closeMenu() {
            menu.hidden = true;
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
            state.items = [];
            state.activeIndex = -1;
        }

        function restoreSelectionLabel() {
            input.value = selectedSourceLabel(select);
            state.dirty = false;
        }

        function setActive(index) {
            if (!state.items.length) return;
            index = Math.max(0, Math.min(state.items.length - 1, index));
            state.activeIndex = index;
            var options = menu.querySelectorAll('[role="option"]');
            for (var i = 0; i < options.length; i++) {
                var active = i === index;
                options[i].classList.toggle("active", active);
                options[i].setAttribute("aria-selected", active ? "true" : "false");
                if (active) {
                    input.setAttribute("aria-activedescendant", options[i].id);
                    if (options[i].scrollIntoView) {
                        options[i].scrollIntoView({ block: "nearest" });
                    }
                }
            }
        }

        function choose(candidate) {
            if (!candidate) return;
            select.value = String(candidate.value || "");
            restoreSelectionLabel();
            closeMenu();
            if (typeof Event === "function") {
                select.dispatchEvent(new Event("change", { bubbles: true }));
            } else if (document.createEvent) {
                var event = document.createEvent("Event");
                event.initEvent("change", true, false);
                select.dispatchEvent(event);
            }
            restoreSelectionLabel();
        }

        function renderCandidates(query) {
            var normalized = normalizedProjectSearchText(query);
            var projects = projectCatalogForSelect(select);
            var candidates = projectAutocompleteCandidates(projects, normalized).map(optionForProject);
            if (!normalized) candidates = specialCandidates(select).concat(candidates);
            state.items = candidates;
            state.activeIndex = -1;
            menu.innerHTML = "";
            if (!candidates.length || select.disabled) {
                closeMenu();
                return;
            }
            candidates.forEach(function (candidate, index) {
                var option = document.createElement("button");
                option.type = "button";
                option.className = "project-autocomplete-option";
                option.id = menu.id + "-option-" + index;
                option.setAttribute("role", "option");
                option.setAttribute("aria-selected", "false");
                option.tabIndex = -1;
                var name = document.createElement("span");
                name.className = "project-autocomplete-name";
                name.textContent = candidate.name;
                option.appendChild(name);
                if (candidate.description) {
                    var description = document.createElement("span");
                    description.className = "project-autocomplete-description";
                    description.textContent = candidate.description;
                    option.appendChild(description);
                }
                option.addEventListener("pointerdown", function (event) {
                    event.preventDefault();
                    choose(candidate);
                    input.focus();
                });
                option.addEventListener("mousemove", function () { setActive(index); });
                menu.appendChild(option);
            });
            menu.hidden = false;
            input.setAttribute("aria-expanded", "true");
        }

        function syncFromSource() {
            input.disabled = !!select.disabled;
            restoreSelectionLabel();
            if (select.disabled) closeMenu();
        }

        input.addEventListener("focus", function () {
            syncFromSource();
            renderCandidates("");
            if (input.select) input.select();
        });
        input.addEventListener("input", function () {
            state.dirty = true;
            renderCandidates(input.value);
        });
        input.addEventListener("keydown", function (event) {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                if (menu.hidden) renderCandidates(state.dirty ? input.value : "");
                if (!state.items.length) return;
                var delta = event.key === "ArrowDown" ? 1 : -1;
                var next = state.activeIndex < 0
                    ? (delta > 0 ? 0 : state.items.length - 1)
                    : state.activeIndex + delta;
                if (next < 0) next = state.items.length - 1;
                if (next >= state.items.length) next = 0;
                setActive(next);
                return;
            }
            if (event.key === "Enter" && !menu.hidden && state.activeIndex >= 0) {
                event.preventDefault();
                choose(state.items[state.activeIndex]);
                return;
            }
            if (event.key === "Escape") {
                if (!menu.hidden || state.dirty) {
                    event.preventDefault();
                    restoreSelectionLabel();
                    closeMenu();
                    if (input.select) input.select();
                }
            }
        });
        input.addEventListener("blur", function () {
            setTimeout(function () {
                if (shell.contains && shell.contains(document.activeElement)) return;
                restoreSelectionLabel();
                closeMenu();
            }, 0);
        });
        select.addEventListener("change", syncFromSource);

        if (typeof MutationObserver === "function") {
            var observer = new MutationObserver(function () {
                syncFromSource();
                if (!menu.hidden && document.activeElement === input) {
                    renderCandidates(state.dirty ? input.value : "");
                }
            });
            observer.observe(select, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ["disabled"]
            });
            state.observer = observer;
        }

        syncFromSource();
        return state;
    }
    App.enhanceProjectSelect = enhanceProjectSelect;

    function installProjectAutocompletes() {
        ["timeline-project-filter", "statistics-project-filter", "edit-project-select"]
            .forEach(function (id) {
                var select = document.getElementById(id);
                if (select && String(select.tagName || "").toUpperCase() === "SELECT") {
                    enhanceProjectSelect(select);
                }
            });
    }
    App.installProjectAutocompletes = installProjectAutocompletes;
    installProjectAutocompletes();

    function tooltipOwner(target) {
        if (!target || !target.closest) return null;
        return target.closest("[data-tooltip]");
    }

    function hideTooltip() {
        tooltipTarget = null;
        if (!tooltip) return;
        tooltip.hidden = true;
        tooltip.textContent = "";
    }

    function positionTooltip(target) {
        if (!tooltip || !target || typeof target.getBoundingClientRect !== "function") return;
        var rect = target.getBoundingClientRect();
        var width = Number(tooltip.offsetWidth || 0);
        var height = Number(tooltip.offsetHeight || 0);
        var viewportWidth = Number(window.innerWidth || 10000);
        var viewportHeight = Number(window.innerHeight || 10000);
        var gap = 6;
        var left = rect.left + rect.width / 2 - width / 2;
        left = Math.max(6, Math.min(left, viewportWidth - width - 6));
        var top = rect.bottom + gap;
        if (top + height + 6 > viewportHeight) top = Math.max(6, rect.top - height - gap);
        tooltip.style.left = Math.round(left) + "px";
        tooltip.style.top = Math.round(top) + "px";
    }

    function showTooltip(target) {
        if (!tooltip || !target || target.disabled) return;
        var text = String(target.getAttribute("data-tooltip") || "").trim();
        if (!text) return;
        tooltipTarget = target;
        tooltip.textContent = text;
        tooltip.hidden = false;
        positionTooltip(target);
    }

    function enteredTooltipTarget(event) {
        var target = tooltipOwner(event.target);
        if (target) showTooltip(target);
    }

    function leftTooltipTarget(event) {
        var target = tooltipOwner(event.target);
        if (!target || target !== tooltipTarget) return;
        var related = event.relatedTarget;
        if (related && target.contains && target.contains(related)) return;
        hideTooltip();
    }

    document.addEventListener("mouseover", enteredTooltipTarget);
    document.addEventListener("focusin", enteredTooltipTarget);
    document.addEventListener("mouseout", leftTooltipTarget);
    document.addEventListener("focusout", leftTooltipTarget);
    if (typeof window.addEventListener === "function") {
        window.addEventListener("scroll", hideTooltip, true);
        window.addEventListener("resize", hideTooltip);
    }
    App.hideTooltip = hideTooltip;

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") hideTooltip();
        if (dialogState) {
            if (event.key === "Escape") {
                event.preventDefault();
                finishDialog(false);
                return;
            }
            trapFocus(event, dialog);
            return;
        }
        var drawer = document.querySelector(".drawer-layer:not([hidden])");
        if (!drawer) return;
        if (event.key === "Escape") {
            event.preventDefault();
            if (typeof drawer._requestClose === "function") drawer._requestClose();
            else App.closeManagedDrawer(drawer);
            return;
        }
        trapFocus(event, drawer.querySelector(".drawer"));
    });
})();
