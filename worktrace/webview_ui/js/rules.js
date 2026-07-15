// WorkTrace WebView frontend - Project Rules core module.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function loadProjectRules() {
        if (App.rulesLoadPromise) return App.rulesLoadPromise;
        var token = App.requestCoordinator.beginLatest("rules", "home");
        App.setRulesLoading(true);
        App.clearRulesError();
        var request = App.callBridge("get_project_rules").then(function (result) {
            if (!App.requestCoordinator.isCurrent(token)) return null;
            if (result && result.ok === false) {
                App.showRulesError("加载项目规则失败");
                return null;
            }
            App.showProjectRules(result || { projects: [] });
            App.clearRulesError();
            return result;
        }).catch(function () {
            if (App.requestCoordinator.isCurrent(token)) {
                App.showRulesError("加载项目规则失败");
            }
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
        var projects = sortProjectsForRulesHome(
            (App.lastProjectRulesData.projects || [])
        );
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

    // init.js is the last static script. Load the small cross-module
    // coordinator after the window is fully initialized without modifying the
    // large HTML template or adding a bundler.
    window.addEventListener("load", function () {
        if (document.querySelector('script[data-worktrace-hardening="1"]')) return;
        var script = document.createElement("script");
        script.src = "js/frontend_hardening.js";
        script.async = false;
        script.setAttribute("data-worktrace-hardening", "1");
        document.body.appendChild(script);
    });
})();
