// WorkTrace WebView frontend - Project Rules core module.
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

    function _collectExistingRuleKeys(projects) {
        // Build a set of "<kind>:<id>" keys for every folder / keyword
        // rule currently present in the loaded data. Used to prune stale
        // batch-selection keys (e.g. a rule was deleted via the single-rule
        // delete path) so the toolbar count never references a rule that no
        // longer exists.
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
        // Best-effort preserve selection by rule key. Walks the loaded
        // data, builds the set of still-existing rule keys, and drops any
        // selection entry that no longer corresponds to a real rule. This
        // is the only place selection is pruned on a regular refresh; the
        // batch write handlers clear selection explicitly on success and
        // preserve it on failure.
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
        // Cache the last-loaded data so the inline folder edit form can
        // re-render the list immediately without a round-trip through
        // loadProjectRules (which would lose input focus).
        App.lastProjectRulesData = data || { projects: [] };
        var list = document.getElementById("rules-list");
        var empty = document.getElementById("rules-empty");
        // Keep the keyword create form's project selector in sync with the
        // freshly loaded Project Rules data. The selector is only
        // re-populated when no keyword create is in flight so an in-flight
        // submit is never displaced by an auto-refresh.
        App.populateKeywordCreateProjectSelector((data && data.projects) || []);
        // Same sync for the folder create form's project selector.
        App.populateFolderCreateProjectSelector((data && data.projects) || []);
        if (!list || !empty) return;
        var projects = (data && data.projects) || [];
        // Prune stale batch selection keys before rendering so the per-row
        // checkbox state + toolbar count match the loaded data.
        _pruneBatchSelection(projects);
        if (!projects.length) {
            list.innerHTML = "";
            empty.hidden = false;
            // When there are no projects at all, hide the batch toolbar so
            // the page does not show an empty toolbar with inactive controls.
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
        // Bind the excluded-rule create event delegation. The bind helper
        // is idempotent (guarded by data-*-bound attrs) so calling it on
        // every render is safe.
        App.bindExcludedKeywordRuleEvents();
        App.bindExcludedFolderRuleEvents();
        // Bind the batch event delegation (checkbox change on #rules-list,
        // click on #rules-batch-toolbar / #rules-batch-panel). The bind
        // helpers are idempotent (guarded by data-*-bound attrs) so calling
        // them on every render is safe.
        App.bindProjectRuleBatchEvents();
        // Refresh the batch toolbar so the selected count and button
        // disabled state reflect the freshly rendered list.
        App.refreshProjectRulesBatchToolbar();
    }
    App.showProjectRules = showProjectRules;

    function rerenderProjectRulesList() {
        // Re-render the rules list from the last-loaded data so the inline
        // folder edit form can appear / disappear immediately without a
        // round-trip through loadProjectRules. Falls back to a
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
        App.bindProjectRuleImpactEvents();
        // Re-bind excluded-rule create event delegation. The bind helper
        // is idempotent (guarded by data-*-bound attrs) so calling it on
        // every re-render is safe.
        App.bindExcludedKeywordRuleEvents();
        App.bindExcludedFolderRuleEvents();
        // Re-bind batch event delegation + refresh the toolbar so the
        // per-row checkbox state and selected count stay in sync after an
        // inline re-render (e.g. toggling the inline folder edit form).
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
