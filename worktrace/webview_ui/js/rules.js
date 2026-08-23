// WorkTrace WebView frontend - Project Rules core module.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function loadProjectRules(options) {
        options = options || {};
        var forceFresh = options.forceFresh === true;
        var showLoading = options.showLoading === true
            || (!App.rulesLoaded && options.showLoading !== false);
        if (App.rulesLoadPromise && !forceFresh) return App.rulesLoadPromise;
        var token = App.requestCoordinator.beginLatest("rules", "home");
        if (showLoading) App.setRulesLoading(true);
        App.clearRulesError();
        var request = App.bridge.getProjectRules().then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            if (result && result.ok === false) {
                App.showRulesError("加载项目规则失败");
                return null;
            }
            App.showProjectRules(result || { projects: [] });
            App.clearRulesError();
            return result;
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) App.showRulesError("加载项目规则失败");
            return null;
        }).finally(function () {
            if (App.rulesLoadPromise === request) App.rulesLoadPromise = null;
            if (showLoading && App.requestCoordinator.isCurrent(token)) App.setRulesLoading(false);
        });
        App.rulesLoadPromise = request;
        return request;
    }
    App.loadProjectRules = loadProjectRules;
    App.reloadProjectRules = function () {
        if (App.projectCatalog) App.projectCatalog.invalidate();
        return loadProjectRules({ forceFresh: true, showLoading: false });
    };

    function sortProjectsForRulesHome(projects) {
        var list = (projects || []).slice();
        var mode = App.rulesSortMode || "last_used";
        list.sort(function (a, b) {
            if (mode === "alpha") {
                return App.safeText(a && a.name, "").localeCompare(
                    App.safeText(b && b.name, ""), "zh-Hans-CN"
                );
            }
            var aUsed = App.safeText(a && a.last_used_at, "");
            var bUsed = App.safeText(b && b.last_used_at, "");
            if (aUsed && bUsed && aUsed !== bUsed) return aUsed < bUsed ? 1 : -1;
            if (aUsed && !bUsed) return -1;
            if (!aUsed && bUsed) return 1;
            return App.safeText(a && a.name, "").localeCompare(
                App.safeText(b && b.name, ""), "zh-Hans-CN"
            );
        });
        return list;
    }
    App.sortProjectsForRulesHome = sortProjectsForRulesHome;

    function captureExpandedProjects(list) {
        var expanded = {};
        if (!list || typeof list.querySelectorAll !== "function") return expanded;
        var cards = list.querySelectorAll(".rules-project-card");
        for (var index = 0; index < cards.length; index++) {
            var card = cards[index];
            var toggle = card.querySelector && card.querySelector(".rules-project-toggle");
            var projectId = card.getAttribute && card.getAttribute("data-project-id");
            if (projectId && toggle && toggle.getAttribute("aria-expanded") === "true") {
                expanded[String(projectId)] = true;
            }
        }
        return expanded;
    }

    function restoreExpandedProjects(list, expanded) {
        if (!list || !expanded || typeof list.querySelectorAll !== "function") return;
        var cards = list.querySelectorAll(".rules-project-card");
        for (var index = 0; index < cards.length; index++) {
            var card = cards[index];
            var projectId = card.getAttribute && card.getAttribute("data-project-id");
            if (!projectId || !expanded[String(projectId)]) continue;
            var toggle = card.querySelector && card.querySelector(".rules-project-toggle");
            var rows = card.querySelector && card.querySelector(".rules-row-list");
            if (rows) rows.hidden = false;
            if (toggle) {
                toggle.setAttribute("aria-expanded", "true");
                toggle.classList.toggle("is-expanded", true);
                toggle.setAttribute("aria-label", "收起项目规则");
                toggle.setAttribute("data-tooltip", "收起规则");
            }
        }
    }

    function renderProjectRulesList(list, projects) {
        var expanded = captureExpandedProjects(list);
        list.innerHTML = projects.map(function (project) {
            return App.renderProjectRuleProject(project);
        }).join("");
        restoreExpandedProjects(list, expanded);
        applyRulesSearch();
    }

    function showProjectRules(data) {
        App.rulesLoaded = true;
        App.rulesRefreshPending = false;
        App.lastProjectRulesData = data || { projects: [] };
        var list = document.getElementById("rules-list");
        var empty = document.getElementById("rules-empty");
        if (App.refreshRulesPanelTargets) App.refreshRulesPanelTargets();
        if (!list || !empty) return;
        var projects = sortProjectsForRulesHome((data && data.projects) || []);
        if (!projects.length) {
            list.innerHTML = "";
            empty.hidden = false;
            return;
        }
        empty.hidden = true;
        renderProjectRulesList(list, projects);
        if (App.bindProjectRuleDeleteEvents) App.bindProjectRuleDeleteEvents();
    }
    App.showProjectRules = showProjectRules;

    App.rerenderProjectRulesList = function () {
        var list = document.getElementById("rules-list");
        if (!list) return;
        if (!App.lastProjectRulesData) {
            App.loadProjectRules();
            return;
        }
        var projects = sortProjectsForRulesHome(App.lastProjectRulesData.projects || []);
        if (!projects.length) return;
        renderProjectRulesList(list, projects);
        if (App.bindProjectRuleDeleteEvents) App.bindProjectRuleDeleteEvents();
    };

    function applyRulesSearch() {
        var input = document.getElementById("rules-search-input");
        var query = App.safeText(input && input.value, "").trim().toLocaleLowerCase();
        var cards = document.querySelectorAll("#rules-list .rules-project-card");
        for (var index = 0; index < cards.length; index++) {
            cards[index].hidden = !!query
                && String(cards[index].getAttribute("data-rules-search") || "").indexOf(query) < 0;
        }
    }
    App.applyRulesSearch = applyRulesSearch;

    App.setRulesLoading = function (loading) {
        App.rulesLoading = loading;
        var el = document.getElementById("rules-loading");
        if (el) el.hidden = !loading;
    };

    App.showRulesError = function (message) {
        var banner = document.getElementById("rules-error");
        if (!banner) return;
        banner.hidden = !message;
        banner.textContent = message || "加载项目规则失败";
    };
    App.clearRulesError = function () { App.showRulesError(""); };

    function refreshProjectRulesSilently() {
        return loadProjectRules({ showLoading: false });
    }

    function onRulesDataChanged(change) {
        change = change || {};
        if (change.structureChanged !== true && change.classificationChanged !== true) {
            return Promise.resolve(null);
        }
        App.rulesRefreshPending = true;
        if (change.source !== "refresh-state"
            || App.currentPage !== "rules"
            || change.classificationChanged !== true) {
            return Promise.resolve(null);
        }
        return refreshProjectRulesSilently();
    }

    function onRulesPageEntered() {
        if (!App.rulesLoaded) return loadProjectRules({ showLoading: true });
        if (App.rulesRefreshPending !== true) return Promise.resolve(null);
        return refreshProjectRulesSilently();
    }

    function onRulesRefreshRequested() {
        if (!App.rulesLoaded) return loadProjectRules({ showLoading: true });
        return refreshProjectRulesSilently();
    }

    function resetRulesGeneration() {
        App.rulesLoaded = false;
        App.rulesRefreshPending = false;
        App.lastProjectRulesData = null;
        App.rulesLoadPromise = null;
        App.rulesRequestToken = (App.rulesRequestToken || 0) + 1;
        if (typeof App.resetRulesTransientUi === "function") {
            App.resetRulesTransientUi({ restoreFocus: false });
        }
        App.setRulesLoading(false);
    }

    function bindRulesEvents() {
        if (App.initRulesPanelEvents) App.initRulesPanelEvents();
    }

    App.rules = Object.freeze({
        bindEvents: bindRulesEvents,
        // Activity-backed last-used ordering makes report structure stale on entry,
        // but only classification/privacy changes refresh an already-open page.
        refreshPolicy: Object.freeze({
            entryGenerations: Object.freeze([
                "classification_catalog", "privacy_catalog", "report_structure"
            ]),
            automaticGenerations: Object.freeze([
                "classification_catalog", "privacy_catalog"
            ]),
            deferred: false
        }),
        hasLoadedData: function () { return App.rulesLoaded === true; },
        onDataChanged: onRulesDataChanged,
        onPageEntered: onRulesPageEntered,
        onPageLeft: function () {
            if (typeof App.resetRulesTransientUi === "function") {
                App.resetRulesTransientUi({ restoreFocus: false });
            }
        },
        onRefreshRequested: onRulesRefreshRequested,
        refreshEvidence: function () { return App.lastProjectRulesData || null; },
        resetGeneration: resetRulesGeneration
    });
})();
