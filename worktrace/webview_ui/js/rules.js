// WorkTrace WebView frontend - Project Rules core module.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function installProjectCatalogCoordinator() {
        App.loadProjects = function () {
            if (App.projectsCache) return Promise.resolve(App.projectsCache);
            if (App.projectsLoadPromise) return App.projectsLoadPromise;
            App.projectsLoading = true;
            var epoch = App.dataEpoch || 0;
            var request = App.bridge.listProjectsForTimeline().then(function (result) {
                if (epoch !== (App.dataEpoch || 0)) return null;
                if (result && result.ok !== false && result.projects) {
                    App.projectsCache = result.projects;
                }
                return App.projectsCache;
            }).catch(function () {
                return null;
            }).finally(function () {
                if (App.projectsLoadPromise === request) {
                    App.projectsLoadPromise = null;
                    App.projectsLoading = false;
                }
            });
            App.projectsLoadPromise = request;
            return request;
        };
    }
    installProjectCatalogCoordinator();

    function closestTimelineItem(target) {
        while (target && target !== document) {
            if (target.classList && target.classList.contains("timeline-item")) return target;
            target = target.parentElement;
        }
        return null;
    }

    function installTimelineProjectLoadGate() {
        var list = document.getElementById("timeline-sessions-list");
        if (!list || list.getAttribute("data-project-load-gate") === "1") return;
        list.setAttribute("data-project-load-gate", "1");
        list.addEventListener("click", function (event) {
            if (!App.projectsLoading || !App.projectsLoadPromise) return;
            var item = closestTimelineItem(event.target);
            if (!item) return;
            event.preventDefault();
            event.stopImmediatePropagation();
            var epoch = App.dataEpoch || 0;
            App.projectsLoadPromise.then(function () {
                if (epoch !== (App.dataEpoch || 0)) return;
                if (document.body.contains(item)) item.click();
            });
        }, true);
    }
    installTimelineProjectLoadGate();

    function refreshSharedProjectCatalog() {
        App.projectsCache = null;
        App.projectsLoading = false;
        App.projectsLoadPromise = null;
        return typeof App.loadProjects === "function" ? App.loadProjects() : Promise.resolve(null);
    }
    App.refreshSharedProjectCatalog = refreshSharedProjectCatalog;

    function loadProjectRules() {
        if (App.rulesLoadPromise) return App.rulesLoadPromise;
        var token = App.requestCoordinator.beginLatest("rules", "home");
        App.setRulesLoading(true);
        App.clearRulesError();
        var request = App.bridge.getProjectRules().then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            if (result && result.ok === false) {
                App.showRulesError("加载项目规则失败");
                return null;
            }
            App.showProjectRules(result || { projects: [] });
            App.clearRulesError();
            return refreshSharedProjectCatalog().then(function () { return result; });
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) App.showRulesError("加载项目规则失败");
            return null;
        }).finally(function () {
            if (App.rulesLoadPromise === request) App.rulesLoadPromise = null;
            if (App.requestCoordinator.isCurrent(token)) App.setRulesLoading(false);
        });
        App.rulesLoadPromise = request;
        return request;
    }
    App.loadProjectRules = loadProjectRules;

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

    function showProjectRules(data) {
        App.rulesLoaded = true;
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
        list.innerHTML = projects.map(function (project) {
            return App.renderProjectRuleProject(project);
        }).join("");
        App.bindProjectRuleDelete();
        App.bindProjectRuleFolderEvents();
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
        list.innerHTML = projects.map(function (project) {
            return App.renderProjectRuleProject(project);
        }).join("");
        App.bindProjectRuleDelete();
        App.bindProjectRuleFolderEvents();
    };

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
})();
