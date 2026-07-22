// WorkTrace WebView frontend — Project Rules semantic rendering.
(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};
    function text(value, fallback) { return App.escapeHtml(App.safeText(value, fallback)); }
    function count(value) { return App.escapeHtml(String(parseInt(value, 10) || 0)); }
    function kind(value) { return value === "folder" ? "folder" : "keyword"; }

    function renderProjectRuleProject(project) {
        var id = parseInt(project && project.id, 10) || 0;
        var rules = (project && project.rules) || [];
        var rows = rules.length ? rules.map(renderProjectRuleRow).join("")
            : '<div class="rules-project-empty">此项目暂无规则</div>';
        var searchable = [project && project.name, project && project.description]
            .concat(rules.map(function (rule) { return (rule.target || "") + " " + (rule.detail || ""); }))
            .join(" ").toLocaleLowerCase();
        return '<article class="rules-project-card" data-project-id="' + count(id)
            + '" data-rules-search="' + text(searchable, "") + '">'
            + '<div class="rules-project-head">'
            + '<button type="button" class="rules-project-toggle" aria-expanded="false"'
            + ' aria-label="展开 ' + text(project && project.name, "项目") + ' 的规则" data-tooltip="展开规则">'
            + App.iconMarkup("chevron-right") + '</button>'
            + '<div class="rules-project-title-group"><div class="rules-project-title">'
            + text(project && project.name, "未命名项目") + '</div>'
            + (project && project.description ? '<div class="rules-project-description">'
                + text(project.description, "") + '</div>' : '')
            + '</div><div class="rules-project-actions"><div class="rules-project-button-row">'
            + '<button class="rules-project-add-rule-button icon-button" type="button" data-project-id="' + count(id)
            + '" aria-label="新建规则" data-tooltip="新建规则">' + App.iconMarkup("plus") + '</button>'
            + '<button class="rules-project-edit-button icon-button" type="button" data-project-id="' + count(id)
            + '" aria-label="编辑项目" data-tooltip="编辑项目">' + App.iconMarkup("pencil") + '</button>'
            + '<button class="rules-project-delete-button icon-button danger-icon-button" type="button" data-project-id="' + count(id)
            + '" aria-label="删除项目" data-tooltip="删除项目">' + App.iconMarkup("trash") + '</button>'
            + '</div><div class="rules-project-meta"><span>上次使用：'
            + text(project && project.last_used_at, "暂无使用记录") + '</span><span>累计时间：'
            + (project && project.total_duration_seconds != null
                ? text(App.formatDuration(project.total_duration_seconds), "00:00:00") : '—')
            + '</span></div></div></div><div class="rules-row-list" hidden>' + rows + '</div></article>';
    }
    App.renderProjectRuleProject = renderProjectRuleProject;

    function renderProjectRuleRow(rule) {
        var ruleKind = kind(rule && rule.kind);
        var id = parseInt(rule && rule.id, 10) || 0;
        return '<div class="rules-row"><span class="rules-kind-badge rules-kind-' + ruleKind + '">'
            + text(rule && rule.kind_label, "规则") + '</span><div class="rules-row-main"><div class="rules-target">'
            + text(rule && rule.target, "未设置") + '</div>'
            + (rule && rule.detail ? '<div class="rules-detail">' + text(rule.detail, "") + '</div>' : '')
            + '</div><button class="rules-' + ruleKind + '-delete-button icon-button danger-icon-button" type="button" data-rule-kind="'
            + ruleKind + '" data-rule-id="' + count(id) + '" aria-label="删除规则" data-tooltip="删除规则">'
            + App.iconMarkup("trash") + '</button></div>';
    }
    App.renderProjectRuleRow = renderProjectRuleRow;
    App.renderExcludedRuleRow = renderProjectRuleRow;
})();
