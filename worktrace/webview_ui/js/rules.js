// WorkTrace WebView frontend — Project Rules module (Phase 5B).
// Existing project-bound folder / keyword rules can be enabled or disabled.

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
        var list = document.getElementById("rules-list");
        var empty = document.getElementById("rules-empty");
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
    }
    App.showProjectRules = showProjectRules;

    function renderProjectRuleProject(project) {
        var name = text(project && project.name, "未命名项目");
        var description = text(project && project.description, "");
        var summary = text(project && project.summary, "暂无规则");
        var enabled = !!(project && project.enabled);
        var isExcluded = !!(project && project.is_excluded);
        var rules = (project && project.rules) || [];
        var stateLabel = enabled ? "已启用" : "已禁用";
        var projectClass = enabled ? "rules-project-card" : "rules-project-card is-disabled";
        var rows = rules.length ? rules.map(function (rule) {
            return App.renderProjectRuleRow(rule);
        }).join("") : '<div class="rules-project-empty">此项目暂无规则</div>';
        return [
            '<article class="' + projectClass + '">',
            '  <div class="rules-project-head">',
            '    <div class="rules-project-title-group">',
            '      <div class="rules-project-title">' + name + '</div>',
            description ? '      <div class="rules-project-description">' + description + '</div>' : "",
            '    </div>',
            '    <div class="rules-project-badges">',
            '      <span class="rules-status ' + (enabled ? "is-enabled" : "is-disabled") + '">' + stateLabel + '</span>',
            isExcluded ? '      <span class="rules-excluded-badge">排除规则</span>' : "",
            '    </div>',
            '  </div>',
            '  <div class="rules-project-summary">' + summary + '</div>',
            '  <div class="rules-count-grid">',
            '    <div><span>规则总数</span><strong>' + count(project && project.rule_count) + '</strong></div>',
            '    <div><span>文件夹规则</span><strong>' + count(project && project.folder_rule_count) + '</strong></div>',
            '    <div><span>关键词规则</span><strong>' + count(project && project.keyword_rule_count) + '</strong></div>',
            '  </div>',
            '  <div class="rules-row-list">' + rows + '</div>',
            '</article>'
        ].join("");
    }
    App.renderProjectRuleProject = renderProjectRuleProject;

    function renderProjectRuleRow(rule) {
        var label = text(rule && rule.kind_label, "规则");
        var target = text(rule && rule.target, "未设置");
        var detail = text(rule && rule.detail, "");
        var enabled = !!(rule && rule.enabled);
        var stateLabel = enabled ? "已启用" : "已禁用";
        var actionLabel = enabled ? "停用" : "启用";
        var kind = ruleKind(rule && rule.kind);
        var ruleId = positiveInt(rule && rule.id);
        var ruleKey = kind + ":" + ruleId;
        var saving = App.rulesSavingRuleKey === ruleKey;
        var disabledAttr = (App.rulesSavingRuleKey || !ruleId) ? " disabled" : "";
        var buttonLabel = saving ? "正在更新…" : actionLabel;
        return [
            '<div class="rules-row ' + (enabled ? "" : "is-disabled") + '">',
            '  <span class="rules-kind-badge rules-kind-' + kind + '">' + label + '</span>',
            '  <div class="rules-row-main">',
            '    <div class="rules-target">' + target + '</div>',
            '    <div class="rules-detail">' + detail + '</div>',
            '  </div>',
            '  <span class="rules-status ' + (enabled ? "is-enabled" : "is-disabled") + '">' + stateLabel + '</span>',
            '  <button class="rules-toggle-btn" type="button" data-rule-type="' + kind + '" data-rule-id="' + count(ruleId) + '" data-next-enabled="' + (!enabled ? "true" : "false") + '"' + disabledAttr + '>' + buttonLabel + '</button>',
            '</div>'
        ].join("");
    }
    App.renderProjectRuleRow = renderProjectRuleRow;

    function bindProjectRuleToggles() {
        var list = document.getElementById("rules-list");
        if (!list || list.getAttribute("data-rules-toggle-bound") === "1") return;
        list.setAttribute("data-rules-toggle-bound", "1");
        list.addEventListener("click", App.handleProjectRuleToggle);
    }
    App.bindProjectRuleToggles = bindProjectRuleToggles;

    function handleProjectRuleToggle(event) {
        var button = event.target && event.target.closest ? event.target.closest(".rules-toggle-btn") : null;
        if (!button || App.rulesSavingRuleKey) return;
        var ruleType = button.getAttribute("data-rule-type");
        var ruleId = parseInt(button.getAttribute("data-rule-id"), 10);
        var nextEnabled = button.getAttribute("data-next-enabled") === "true";
        if ((ruleType !== "folder" && ruleType !== "keyword") || !ruleId) {
            App.showRulesError("更新规则状态失败");
            return;
        }
        if (!nextEnabled && !window.confirm("确定停用这条规则吗？停用后它将不再用于自动归类。")) {
            return;
        }
        App.setProjectRuleSaving(ruleType + ":" + ruleId);
        App.clearRulesError();
        App.callBridge("set_project_rule_enabled", ruleType, ruleId, nextEnabled).then(function (result) {
            if (result && result.ok === false) {
                App.showRulesError(result.error || "更新规则状态失败");
                return;
            }
            return App.loadProjectRules().then(function () {
                App.showRulesError("规则状态已更新");
            });
        }).catch(function () {
            App.showRulesError("更新规则状态失败");
        }).then(function () {
            App.setProjectRuleSaving(null);
        });
    }
    App.handleProjectRuleToggle = handleProjectRuleToggle;

    function setProjectRuleSaving(ruleKey) {
        App.rulesSavingRuleKey = ruleKey || null;
        var buttons = document.querySelectorAll(".rules-toggle-btn");
        Array.prototype.forEach.call(buttons, function (button) {
            var currentKey = button.getAttribute("data-rule-type") + ":" + button.getAttribute("data-rule-id");
            button.disabled = !!App.rulesSavingRuleKey;
            if (currentKey === App.rulesSavingRuleKey) {
                button.textContent = "正在更新…";
            }
        });
    }
    App.setProjectRuleSaving = setProjectRuleSaving;

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

    function text(value, fallback) {
        return App.escapeHtml(App.safeText(value, fallback));
    }

    function count(value) {
        return App.escapeHtml(String(parseInt(value, 10) || 0));
    }

    function positiveInt(value) {
        var parsed = parseInt(value, 10);
        return parsed > 0 ? parsed : 0;
    }

    function ruleKind(value) {
        return value === "folder" ? "folder" : (value === "keyword" ? "keyword" : "unknown");
    }

})();
