// WorkTrace WebView frontend - Project Rules render helpers (Phase 5B-5G, MC2 split).
// renderProjectRuleProject / renderProjectRuleRow and private render helpers.
// Loaded after rules.js, before rule / keyword / folder / project action modules.

(function () {
    "use strict";
    var App = window.WorkTraceApp = window.WorkTraceApp || {};

    function renderProjectRuleProject(project) {
        var name = text(project && project.name, "未命名项目");
        var description = text(project && project.description, "");
        var summary = text(project && project.summary, "暂无规则");
        var enabled = !!(project && project.enabled);
        var isExcluded = !!(project && project.is_excluded);
        var isSystem = !!(project && project.is_system);
        var editable = !!(project && project.editable && !isSystem);
        var canToggle = !!(project && project.can_toggle && !isSystem);
        var canArchive = !!(project && project.can_archive && !isSystem);
        var projectId = positiveInt(project && project.id);
        var rules = (project && project.rules) || [];
        var stateLabel = enabled ? "已启用" : "已禁用";
        var projectClass = enabled ? "rules-project-card" : "rules-project-card is-disabled";
        var rows = rules.length ? rules.map(function (rule) {
            return App.renderProjectRuleRow(rule);
        }).join("") : '<div class="rules-project-empty">此项目暂无规则</div>';
        // Phase 5G: project lifecycle buttons. Only render on user projects
        // (``editable`` / ``can_toggle`` / ``can_archive``). System/special
        // projects (``未归类`` / ``排除规则``) never get these buttons. The
        // buttons are disabled while any project lifecycle write is in
        // flight so the four write paths cannot pollute each other.
        var projectActions = "";
        var projectEditForm = "";
        if (editable && projectId) {
            // When this project is being edited, render the inline edit form
            // in place of the action buttons so the user can edit name /
            // description without leaving the card.
            var editing = App.rulesEditingProjectId === projectId;
            if (editing) {
                var currentName = text(project && project.name, "");
                var currentDescription = text(project && project.description, "");
                var saving = App.rulesUpdatingProjectId === projectId;
                var saveLabel = saving ? "正在保存…" : "保存";
                var editFormDisabled = saving ? " disabled" : "";
                projectEditForm = [
                    '<div class="rules-project-edit-form">',
                    '  <div class="rules-project-edit-row">',
                    '    <label class="rules-project-edit-label">项目名称</label>',
                    '    <input class="rules-project-edit-name" type="text" maxlength="100" value="' + currentName + '" placeholder="输入项目名称"' + editFormDisabled + ' />',
                    '  </div>',
                    '  <div class="rules-project-edit-row">',
                    '    <label class="rules-project-edit-label">项目描述</label>',
                    '    <input class="rules-project-edit-description" type="text" maxlength="500" value="' + currentDescription + '" placeholder="输入项目描述（可选）"' + editFormDisabled + ' />',
                    '  </div>',
                    '  <div class="rules-project-edit-actions">',
                    '    <button class="rules-project-edit-save" type="button" data-project-id="' + count(projectId) + '"' + editFormDisabled + '>' + saveLabel + '</button>',
                    '    <button class="rules-project-edit-cancel" type="button" data-project-id="' + count(projectId) + '"' + editFormDisabled + '>取消</button>',
                    '  </div>',
                    '</div>'
                ].join("");
            } else {
                var projectWriteInProgress = !!(
                    App.rulesCreatingProject ||
                    App.rulesEditingProjectId ||
                    App.rulesUpdatingProjectId ||
                    App.rulesTogglingProjectId ||
                    App.rulesArchivingProjectId
                );
                var actionDisabled = projectWriteInProgress ? " disabled" : "";
                var toggleLabel = (App.rulesTogglingProjectId === projectId) ? "正在更新…" : (enabled ? "停用" : "启用");
                var archiveLabel = (App.rulesArchivingProjectId === projectId) ? "正在归档…" : "归档";
                var editLabel = "编辑";
                projectActions = [
                    '<div class="rules-project-actions">',
                    '  <button class="rules-project-edit-button" type="button" data-project-id="' + count(projectId) + '"' + actionDisabled + '>' + editLabel + '</button>',
                    '  <button class="rules-project-toggle-button" type="button" data-project-id="' + count(projectId) + '"' + actionDisabled + '>' + toggleLabel + '</button>',
                    '  <button class="rules-project-archive-button" type="button" data-project-id="' + count(projectId) + '"' + actionDisabled + '>' + archiveLabel + '</button>',
                    '</div>'
                ].join("");
            }
        }
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
            projectActions,
            projectEditForm,
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
        var deleting = App.rulesDeletingRuleKey === ruleKey;
        // Phase 5D: disable the toggle button while any rule write is in
        // flight on this row (toggle saving or keyword delete) or when the
        // rule id is missing. This keeps the toggle and delete write paths
        // from concurrently polluting the same row.
        var disabledAttr = (App.rulesSavingRuleKey || App.rulesDeletingRuleKey || !ruleId) ? " disabled" : "";
        var buttonLabel = saving ? "正在更新…" : actionLabel;
        // Phase 5D / 5F: only keyword rules get delete + edit buttons. When
        // editing this row, render the inline edit form in place of the
        // normal row body so the user can edit the keyword text without
        // leaving the row. The toggle and delete buttons stay disabled while
        // keyword edit / save is in flight so the write paths cannot pollute
        // each other.
        var deleteButton = "";
        var keywordEditButton = "";
        var keywordEditing = false;
        if (kind === "keyword" && ruleId) {
            keywordEditing = App.rulesEditingKeywordKey === ruleKey;
            var keywordWriteInProgress = !!(
                App.rulesSavingRuleKey ||
                App.rulesDeletingRuleKey ||
                App.rulesEditingKeywordKey ||
                App.rulesUpdatingKeywordKey
            );
            var keywordBtnDisabled = keywordWriteInProgress ? " disabled" : "";
            var editLabel = (App.rulesUpdatingKeywordKey === ruleKey) ? "正在保存…" : "编辑";
            keywordEditButton = '  <button class="rules-keyword-edit-button" type="button" data-rule-kind="keyword" data-rule-id="' + count(ruleId) + '"' + keywordBtnDisabled + '>' + editLabel + '</button>';
            var deleteDisabled = keywordWriteInProgress ? " disabled" : "";
            var deleteLabel = deleting ? "正在删除…" : "删除";
            deleteButton = '  <button class="rules-keyword-delete-button" type="button" data-rule-kind="keyword" data-rule-id="' + count(ruleId) + '"' + deleteDisabled + '>' + deleteLabel + '</button>';
        }
        // Phase 5E: folder rules get inline edit + delete buttons. When
        // editing this row, render the inline edit form in place of the
        // normal row body so the user can edit folder_path and recursive
        // without leaving the row. The toggle button stays disabled while
        // folder edit / delete is in flight so the four write paths cannot
        // pollute each other.
        var folderButtons = "";
        var folderEditing = false;
        if (kind === "folder" && ruleId) {
            folderEditing = App.rulesEditingFolderKey === ruleKey;
            var folderWriteInProgress = !!(
                App.rulesCreatingFolder ||
                App.rulesEditingFolderKey ||
                App.rulesDeletingFolderKey
            );
            var folderBtnDisabled = (folderWriteInProgress || App.rulesSavingRuleKey || App.rulesDeletingRuleKey) ? " disabled" : "";
            var editLabel = saving ? "正在更新…" : "编辑";
            var folderDeleteLabel = App.rulesDeletingFolderKey === ruleKey ? "正在删除…" : "删除";
            folderButtons = '  <button class="rules-folder-edit-button" type="button" data-rule-kind="folder" data-rule-id="' + count(ruleId) + '"' + folderBtnDisabled + '>' + editLabel + '</button>';
            folderButtons += '  <button class="rules-folder-delete-button" type="button" data-rule-kind="folder" data-rule-id="' + count(ruleId) + '"' + folderBtnDisabled + '>' + folderDeleteLabel + '</button>';
        }
        // When this folder row is being edited, render the inline edit form
        // in place of the normal body. The edit form holds its own folder
        // path input + recursive checkbox + save / cancel buttons.
        if (folderEditing) {
            var currentPath = text(rule && rule.target, "");
            var currentRecursive = !!(rule && rule.recursive);
            return [
                '<div class="rules-row is-folder-editing">',
                '  <span class="rules-kind-badge rules-kind-' + kind + '">' + label + '</span>',
                '  <div class="rules-folder-edit-form">',
                '    <input class="rules-folder-edit-input" type="text" maxlength="512" value="' + currentPath + '" placeholder="输入文件夹路径" />',
                '    <label class="rules-folder-edit-recursive-label"><input class="rules-folder-edit-recursive" type="checkbox"' + (currentRecursive ? " checked" : "") + ' /> 包含子文件夹</label>',
                '    <button class="rules-folder-edit-save" type="button" data-rule-kind="folder" data-rule-id="' + count(ruleId) + '">保存</button>',
                '    <button class="rules-folder-edit-cancel" type="button" data-rule-kind="folder" data-rule-id="' + count(ruleId) + '">取消</button>',
                '  </div>',
                '</div>'
            ].join("");
        }
        // Phase 5F: when this keyword row is being edited, render the inline
        // edit form in place of the normal body. The edit form holds its own
        // keyword input + save / cancel buttons. The maxlength matches the
        // keyword create input (200 chars).
        if (keywordEditing) {
            var currentKeyword = text(rule && rule.target, "");
            var keywordSaving = App.rulesUpdatingKeywordKey === ruleKey;
            var keywordSaveLabel = keywordSaving ? "正在保存…" : "保存";
            var keywordEditFormDisabled = keywordSaving ? " disabled" : "";
            return [
                '<div class="rules-row is-keyword-editing">',
                '  <span class="rules-kind-badge rules-kind-' + kind + '">' + label + '</span>',
                '  <div class="rules-keyword-edit-form">',
                '    <input class="rules-keyword-edit-input" type="text" maxlength="200" value="' + currentKeyword + '" placeholder="输入关键词" />',
                '    <button class="rules-keyword-edit-save" type="button" data-rule-kind="keyword" data-rule-id="' + count(ruleId) + '"' + keywordEditFormDisabled + '>' + keywordSaveLabel + '</button>',
                '    <button class="rules-keyword-edit-cancel" type="button" data-rule-kind="keyword" data-rule-id="' + count(ruleId) + '"' + keywordEditFormDisabled + '>取消</button>',
                '  </div>',
                '</div>'
            ].join("");
        }
        return [
            '<div class="rules-row ' + (enabled ? "" : "is-disabled") + '">',
            '  <span class="rules-kind-badge rules-kind-' + kind + '">' + label + '</span>',
            '  <div class="rules-row-main">',
            '    <div class="rules-target">' + target + '</div>',
            '    <div class="rules-detail">' + detail + '</div>',
            '  </div>',
            '  <span class="rules-status ' + (enabled ? "is-enabled" : "is-disabled") + '">' + stateLabel + '</span>',
            '  <button class="rules-toggle-btn" type="button" data-rule-type="' + kind + '" data-rule-id="' + count(ruleId) + '" data-next-enabled="' + (!enabled ? "true" : "false") + '"' + disabledAttr + '>' + buttonLabel + '</button>',
            deleteButton,
            keywordEditButton,
            folderButtons,
            '</div>'
        ].join("");
    }
    App.renderProjectRuleRow = renderProjectRuleRow;

    // --- Private render helpers (used only by render functions above) ---

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
