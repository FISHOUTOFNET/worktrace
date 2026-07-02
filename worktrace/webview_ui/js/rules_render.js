// WorkTrace WebView frontend - lightweight Project Rules render helpers.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function renderProjectRuleProject(project) {
        var name = text(project && project.name, "未命名项目");
        var description = text(project && project.description, "");
        var language = text(project && project.language, "中文");
        var lastUsed = text(project && project.last_used_at, "暂无使用记录");
        var projectId = positiveInt(project && project.id);
        var rules = (project && project.rules) || [];
        var rows = rules.length ? rules.map(function (rule) {
            return App.renderProjectRuleRow(rule);
        }).join("") : '<div class="rules-project-empty">此项目暂无规则</div>';
        return [
            '<article class="rules-project-card" data-project-id="' + count(projectId) + '">',
            '  <div class="rules-project-head">',
            '    <div class="rules-project-title-group">',
            '      <div class="rules-project-title">' + name + '</div>',
            description ? '      <div class="rules-project-description">' + description + '</div>' : "",
            '    </div>',
            '    <div class="rules-project-meta">',
            '      <span>' + language + '</span>',
            '      <span>上次使用：' + lastUsed + '</span>',
            '    </div>',
            '  </div>',
            '  <div class="rules-project-actions">',
            '    <button class="rules-project-edit-button" type="button" data-project-id="' + count(projectId) + '">编辑项目</button>',
            '    <button class="rules-project-add-rule-button" type="button" data-project-id="' + count(projectId) + '">新增规则</button>',
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
        var kind = ruleKind(rule && rule.kind);
        var ruleId = positiveInt(rule && rule.id);
        var ruleKey = kind + ":" + ruleId;
        var deleting = App.rulesDeletingRuleKey === ruleKey || App.rulesDeletingFolderKey === ruleKey;
        var deleteClass = kind === "folder" ? "rules-folder-delete-button" : "rules-keyword-delete-button";
        var deleteLabel = deleting ? "正在删除..." : "删除";
        var disabled = deleting ? " disabled" : "";
        return [
            '<div class="rules-row ' + (enabled ? "" : "is-disabled") + '">',
            '  <span class="rules-kind-badge rules-kind-' + kind + '">' + label + '</span>',
            '  <div class="rules-row-main">',
            '    <div class="rules-target">' + target + '</div>',
            detail ? '    <div class="rules-detail">' + detail + '</div>' : "",
            '  </div>',
            '  <span class="rules-status ' + (enabled ? "is-enabled" : "is-disabled") + '">' + stateLabel + '</span>',
            '  <button class="' + deleteClass + '" type="button" data-rule-kind="' + kind + '" data-rule-id="' + count(ruleId) + '"' + disabled + '>' + deleteLabel + '</button>',
            '</div>'
        ].join("");
    }
    App.renderProjectRuleRow = renderProjectRuleRow;

    function renderExcludedRuleRow(rule) {
        return App.renderProjectRuleRow(rule);
    }
    App.renderExcludedRuleRow = renderExcludedRuleRow;

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
        return value === "folder" ? "folder" : "keyword";
    }

})();
