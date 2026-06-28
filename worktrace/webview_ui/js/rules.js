// WorkTrace WebView frontend - Project Rules core module (Phase 5B-5G, MC2 split).
// Core loading / refresh / top-level wiring only.
// Render / rule / keyword / folder / project actions live in their split modules.

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

    function showProjectRules(data) {
        App.rulesLoaded = true;
        // Phase 5E: cache the last-loaded data so the inline folder edit
        // form can re-render the list immediately without a round-trip
        // through loadProjectRules (which would lose input focus).
        App.lastProjectRulesData = data || { projects: [] };
        var list = document.getElementById("rules-list");
        var empty = document.getElementById("rules-empty");
        // Phase 5C: keep the keyword create form's project selector in sync
        // with the freshly loaded Project Rules data. The selector is only
        // re-populated when no keyword create is in flight so an in-flight
        // submit is never displaced by an auto-refresh.
        App.populateKeywordCreateProjectSelector((data && data.projects) || []);
        // Phase 5E: same sync for the folder create form's project selector.
        App.populateFolderCreateProjectSelector((data && data.projects) || []);
        if (!list || !empty) return;
        var projects = (data && data.projects) || [];
        if (!projects.length) {
            list.innerHTML = "";
            empty.hidden = false;
            return;
        }
        empty.hidden = true;
        list.innerHTML = projects.map(function (project) {
            return App.renderProjectRuleProject(project);
        }).join("");
        App.bindProjectRuleToggles();
        App.bindProjectRuleDelete();
        App.bindProjectRuleFolderEvents();
        App.bindProjectRuleKeywordEditEvents();
        App.bindProjectLifecycleEvents();
    }
    App.showProjectRules = showProjectRules;

    function rerenderProjectRulesList() {
        // Phase 5E: re-render the rules list from the last-loaded data so
        // the inline folder edit form can appear / disappear immediately
        // without a round-trip through loadProjectRules. Falls back to a
        // loadProjectRules call if no cached data is available.
        var list = document.getElementById("rules-list");
        if (!list) return;
        if (!App.lastProjectRulesData) {
            App.loadProjectRules();
            return;
        }
        var projects = (App.lastProjectRulesData && App.lastProjectRulesData.projects) || [];
        if (!projects.length) {
            return;
        }
        list.innerHTML = projects.map(function (project) {
            return App.renderProjectRuleProject(project);
        }).join("");
        App.bindProjectRuleToggles();
        App.bindProjectRuleDelete();
        App.bindProjectRuleFolderEvents();
        App.bindProjectRuleKeywordEditEvents();
        App.bindProjectLifecycleEvents();
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
