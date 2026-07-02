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

    function _collectExistingRuleKeys(projects) {
        // rule currently present in the loaded data. Used to prune stale
        var keys = {};
        if (!projects || !projects.length) return keys;
        for (var i = 0; i < projects.length; i++) {
            var rules = (projects[i] && projects[i].rules) || [];
            for (var j = 0; j < rules.length; j++) {
                var rule = rules[j] || {};
                var kind = rule.kind;
                var id = parseInt(rule.id, 10);
                if ((kind === "folder" || kind === "keyword") && id > 0) {
                    keys[kind + ":" + id] = true;
                }
            }
        }
        return keys;
    }

    function _pruneBatchSelection(projects) {
        // batch write handlers clear selection explicitly on success and
        if (!App.rulesBatchSelectedKeys) return;
        var existing = _collectExistingRuleKeys(projects);
        var pruned = {};
        var keys = Object.keys(App.rulesBatchSelectedKeys);
        for (var i = 0; i < keys.length; i++) {
            if (existing[keys[i]]) {
                pruned[keys[i]] = true;
            }
        }
        App.rulesBatchSelectedKeys = pruned;
    }

    function showProjectRules(data) {
        App.rulesLoaded = true;
        App.lastProjectRulesData = data || { projects: [] };
        var list = document.getElementById("rules-list");
        var empty = document.getElementById("rules-empty");
        // re-populated when no keyword create is in flight so an in-flight
        App.populateKeywordCreateProjectSelector((data && data.projects) || []);
        App.populateFolderCreateProjectSelector((data && data.projects) || []);
        if (!list || !empty) return;
        var projects = (data && data.projects) || [];
        // Prune stale batch selection keys before rendering so the per-row
        _pruneBatchSelection(projects);
        if (!projects.length) {
            list.innerHTML = "";
            empty.hidden = false;
            var emptyToolbar = document.getElementById("rules-batch-toolbar");
            if (emptyToolbar) emptyToolbar.hidden = true;
            App.refreshProjectRulesBatchToolbar();
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
        App.bindProjectRuleImpactEvents();
        App.bindExcludedKeywordRuleEvents();
        App.bindExcludedFolderRuleEvents();
        App.bindProjectRuleBatchEvents();
        App.refreshProjectRulesBatchToolbar();
    }
    App.showProjectRules = showProjectRules;

    function rerenderProjectRulesList() {
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
        App.bindProjectRuleImpactEvents();
        App.bindExcludedKeywordRuleEvents();
        App.bindExcludedFolderRuleEvents();
        App.bindProjectRuleBatchEvents();
        App.refreshProjectRulesBatchToolbar();
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
