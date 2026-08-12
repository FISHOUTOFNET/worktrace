// WorkTrace project autocomplete: recent-project suggestions and local catalog search.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    var PROJECT_AUTOCOMPLETE_LIMIT = 10;

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
            dirty: false,
            catalogRefreshPromise: null
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

        function dispatchSourceChange() {
            if (typeof Event === "function") {
                select.dispatchEvent(new Event("change", { bubbles: true }));
            } else if (document.createEvent) {
                var event = document.createEvent("Event");
                event.initEvent("change", true, false);
                select.dispatchEvent(event);
            }
        }

        function appendSourceOption(value, label) {
            var option = document.createElement("option");
            option.value = String(value || "");
            option.textContent = String(label || "");
            select.appendChild(option);
            return option;
        }

        function syncFilterSourceOptions(projects) {
            if (select.id === "edit-project-select") return;
            var previous = String(select.value || "");
            select.innerHTML = "";
            appendSourceOption("", "全部项目");
            appendSourceOption("unclassified", "未归类");
            (Array.isArray(projects) ? projects : []).forEach(function (project) {
                if (!project || parseInt(project.id, 10) <= 0) return;
                appendSourceOption(project.id, project.name || "未命名项目");
            });
            select.value = previous;
            if (String(select.value || "") !== previous) {
                select.value = "";
                dispatchSourceChange();
            }
        }

        function ensureSourceOption(candidate) {
            if (!candidate || candidate.special || !String(candidate.value || "")) return;
            var value = String(candidate.value);
            var existing = findSourceOption(select, function (option) {
                return String(option.value || "") === value;
            });
            if (!existing) appendSourceOption(value, candidate.name || "未命名项目");
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
            ensureSourceOption(candidate);
            select.value = String(candidate.value || "");
            restoreSelectionLabel();
            closeMenu();
            dispatchSourceChange();
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

        function refreshCatalogForInteraction() {
            var catalog = App.projectCatalog;
            if (!catalog || typeof catalog.load !== "function") return Promise.resolve(null);
            if (typeof catalog.invalidate === "function") catalog.invalidate();
            var pending = catalog.load().then(function (snapshot) {
                if (!snapshot) return null;
                syncFilterSourceOptions(snapshot.filterProjects || []);
                if (document.activeElement === input) {
                    renderCandidates(state.dirty ? input.value : "");
                }
                return snapshot;
            }).catch(function () { return null; }).finally(function () {
                if (state.catalogRefreshPromise === pending) state.catalogRefreshPromise = null;
            });
            state.catalogRefreshPromise = pending;
            return pending;
        }

        function syncFromSource() {
            input.disabled = !!select.disabled;
            restoreSelectionLabel();
            if (select.disabled) closeMenu();
        }

        input.addEventListener("focus", function () {
            syncFromSource();
            renderCandidates("");
            refreshCatalogForInteraction();
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
})();
