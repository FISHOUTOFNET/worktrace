// WorkTrace WebView frontend - Project Rules core module.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function loadProjectRules() {
        if (App.rulesLoading) {
            return Promise.resolve();
        }
        var token = ++App.rulesRequestToken;
        App.setRulesLoading(true);
        App.clearRulesError();
        return App.callBridge("get_project_rules").then(function (result) {
            if (token !== App.rulesRequestToken) return;
            if (result && result.ok === false) {
                App.showRulesError("加载项目规则失败");
                return;
            }
            App.showProjectRules(result || { projects: [] });
            App.clearRulesError();
        }).catch(function () {
            if (token !== App.rulesRequestToken) return;
            App.showRulesError("加载项目规则失败");
        }).then(function () {
            if (token === App.rulesRequestToken) {
                App.setRulesLoading(false);
            }
        });
    }
    App.loadProjectRules = loadProjectRules;

    function _sortProjectsForRulesHome(projects) {
        var list = (projects || []).slice();
        var mode = App.rulesSortMode || "last_used";
        list.sort(function (a, b) {
            if (mode === "alpha") {
                return App.safeText(a && a.name, "").localeCompare(
                    App.safeText(b && b.name, ""),
                    "zh-Hans-CN"
                );
            }
            var aUsed = App.safeText(a && a.last_used_at, "");
            var bUsed = App.safeText(b && b.last_used_at, "");
            if (aUsed && bUsed && aUsed !== bUsed) return aUsed < bUsed ? 1 : -1;
            if (aUsed && !bUsed) return -1;
            if (!aUsed && bUsed) return 1;
            return App.safeText(a && a.name, "").localeCompare(
                App.safeText(b && b.name, ""),
                "zh-Hans-CN"
            );
        });
        return list;
    }
    App.sortProjectsForRulesHome = _sortProjectsForRulesHome;

    function showProjectRules(data) {
        App.rulesLoaded = true;
        App.lastProjectRulesData = data || { projects: [] };
        var list = document.getElementById("rules-list");
        var empty = document.getElementById("rules-empty");
        if (App.refreshRulesPanelTargets) {
            App.refreshRulesPanelTargets();
        }
        if (!list || !empty) return;
        var projects = _sortProjectsForRulesHome((data && data.projects) || []);
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

    function rerenderProjectRulesList() {
        var list = document.getElementById("rules-list");
        if (!list) return;
        if (!App.lastProjectRulesData) {
            App.loadProjectRules();
            return;
        }
        var projects = _sortProjectsForRulesHome((App.lastProjectRulesData && App.lastProjectRulesData.projects) || []);
        if (!projects.length) {
            return;
        }
        list.innerHTML = projects.map(function (project) {
            return App.renderProjectRuleProject(project);
        }).join("");
        App.bindProjectRuleDelete();
        App.bindProjectRuleFolderEvents();
    }
    App.rerenderProjectRulesList = rerenderProjectRulesList;

    function setRulesLoading(loading) {
        App.rulesLoading = loading;
        var el = document.getElementById("rules-loading");
        if (el) el.hidden = !loading;
    }
    App.setRulesLoading = setRulesLoading;

    function showRulesError(message) {
        var banner = document.getElementById("rules-error");
        if (!banner) return;
        if (!message) {
            banner.hidden = true;
            banner.textContent = "加载项目规则失败";
            return;
        }
        banner.hidden = false;
        banner.textContent = message;
    }
    App.showRulesError = showRulesError;

    function clearRulesError() {
        App.showRulesError("");
    }
    App.clearRulesError = clearRulesError;

})();
