// WorkTrace WebView frontend - Project Rules render helpers.
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
        // Project lifecycle buttons. Only render on user projects
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
            isExcluded ? renderExcludedRuleCreateForm() : "",
            '  <div class="rules-row-list">' + rows + '</div>',
            '</article>'
        ].join("");
    }
    App.renderProjectRuleProject = renderProjectRuleProject;

    // Excluded-rule creation form. Rendered dynamically inside the
    // ``排除规则`` card so it does NOT count as a static submit button
    // (the static contract test locks the static submit button count to 3).
    // The form has two sub-sections: keyword rule creation and folder rule
    // creation. Both call the dedicated excluded-rule bridge methods that
    // do NOT accept an arbitrary project_id (the API pins the project_id
    // to EXCLUDED_PROJECT internally). Project lifecycle buttons are NOT
    // rendered for the excluded card (``editable`` / ``can_toggle`` /
    // ``can_archive`` are all false for system projects), but rule-level
    // CRUD (edit / delete / toggle) remains available in the rules row
    // list below.
    function renderExcludedRuleCreateForm() {
        var writeInProgress = !!(App.rulesCreatingKeyword || App.rulesCreatingFolder);
        var kwDisabled = writeInProgress ? " disabled" : "";
        var folderDisabled = writeInProgress ? " disabled" : "";
        return [
            '<div class="rules-excluded-create">',
            '  <div class="rules-excluded-create-title">新增排除规则</div>',
            '  <div class="rules-excluded-create-row">',
            '    <input class="rules-excluded-keyword-input" type="text" maxlength="200" placeholder="排除关键词"' + kwDisabled + ' />',
            '    <button class="rules-excluded-keyword-submit" type="button"' + kwDisabled + '>新增排除关键词</button>',
            '  </div>',
            '  <div class="rules-excluded-create-row">',
            '    <input class="rules-excluded-folder-input" type="text" maxlength="512" placeholder="排除文件夹路径"' + folderDisabled + ' />',
            '    <label class="rules-excluded-folder-recursive-label"><input class="rules-excluded-folder-recursive" type="checkbox" checked' + folderDisabled + ' /> 包含子文件夹</label>',
            '    <button class="rules-excluded-folder-submit" type="button"' + folderDisabled + '>新增排除文件夹</button>',
            '  </div>',
            '</div>'
        ].join("");
    }
    App.renderExcludedRuleCreateForm = renderExcludedRuleCreateForm;

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
        // Disable the toggle button while any rule write is in flight on
        // this row (toggle saving or keyword delete) or when the rule id is
        // missing. This keeps the toggle and delete write paths from
        // concurrently polluting the same row.
        var disabledAttr = (App.rulesSavingRuleKey || App.rulesDeletingRuleKey || !ruleId) ? " disabled" : "";
        var buttonLabel = saving ? "正在更新…" : actionLabel;
        // Only keyword rules get delete + edit buttons. When editing this
        // row, render the inline edit form in place of the normal row body
        // so the user can edit the keyword text without leaving the row.
        // The toggle and delete buttons stay disabled while keyword edit /
        // save is in flight so the write paths cannot pollute each other.
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
        // Folder rules get inline edit + delete buttons. When editing this
        // row, render the inline edit form in place of the normal row body
        // so the user can edit folder_path and recursive without leaving
        // the row. The toggle button stays disabled while folder edit /
        // delete is in flight so the four write paths cannot pollute each
        // other.
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
        // Every folder / keyword rule with a valid id gets a "预览影响"
        // (read-only impact preview) and "应用到历史记录" (safe single-rule
        // backfill) button. The preview button stays enabled for disabled
        // rules (preview is informational and returns zero counts); the
        // backfill button is disabled for disabled rules because backfill
        // refuses to apply a disabled rule (``rule_disabled``). Both buttons
        // are disabled while any rule write is in flight so the impact paths
        // can never pollute the toggle / delete / edit / lifecycle write
        // paths, and vice versa.
        var impactButtons = "";
        if (ruleId) {
            var impactWriteInProgress = !!(
                App.rulesBackfillingRuleKey ||
                App.rulesSavingRuleKey ||
                App.rulesDeletingRuleKey ||
                App.rulesEditingKeywordKey ||
                App.rulesUpdatingKeywordKey ||
                App.rulesEditingFolderKey ||
                App.rulesCreatingFolder ||
                App.rulesDeletingFolderKey
            );
            var previewingThis = App.rulesPreviewingImpactKey === ruleKey;
            var previewingOther = App.rulesPreviewingImpactKey && App.rulesPreviewingImpactKey !== ruleKey;
            var previewBtnDisabled = (App.rulesBackfillingRuleKey || previewingOther || !ruleId) ? " disabled" : "";
            var previewLabel = previewingThis ? "正在预览…" : "预览影响";
            // Backfill is refused for disabled rules; render it disabled so
            // the user gets immediate visual feedback instead of an error.
            var backfillDisabled = (!enabled || impactWriteInProgress || App.rulesPreviewingImpactKey) ? " disabled" : "";
            var backfillingThis = App.rulesBackfillingRuleKey === ruleKey;
            var backfillLabel = backfillingThis ? "正在应用…" : "应用到历史记录";
            impactButtons = '  <button class="rules-preview-impact-button" type="button" data-rule-kind="' + kind + '" data-rule-id="' + count(ruleId) + '"' + previewBtnDisabled + '>' + previewLabel + '</button>';
            impactButtons += '  <button class="rules-backfill-button" type="button" data-rule-kind="' + kind + '" data-rule-id="' + count(ruleId) + '"' + backfillDisabled + '>' + backfillLabel + '</button>';
        }
        // Every folder / keyword rule with a valid id gets a batch-selection
        // checkbox as the first element of the row. The checkbox is disabled
        // while any batch operation is in flight OR while any per-rule write
        // is in flight on this row, so the batch selection state can never
        // pollute an in-flight per-rule write (and vice versa). Selection
        // lives in ``App.rulesBatchSelectedKeys`` (JS memory only — no
        // browser storage APIs).
        var batchCheckbox = "";
        var batchSelected = false;
        if (ruleId) {
            batchSelected = !!App.rulesBatchSelectedKeys[ruleKey];
            var batchCheckboxDisabled = !!(
                App.rulesBatchInFlight ||
                App.rulesSavingRuleKey ||
                App.rulesDeletingRuleKey ||
                App.rulesEditingKeywordKey ||
                App.rulesUpdatingKeywordKey ||
                App.rulesEditingFolderKey ||
                App.rulesCreatingFolder ||
                App.rulesDeletingFolderKey ||
                App.rulesBackfillingRuleKey ||
                App.rulesPreviewingImpactKey
            );
            var batchCheckboxDisabledAttr = batchCheckboxDisabled ? " disabled" : "";
            var batchCheckedAttr = batchSelected ? " checked" : "";
            batchCheckbox = '  <input class="rules-batch-checkbox" type="checkbox" data-rule-kind="' + kind + '" data-rule-id="' + count(ruleId) + '"' + batchCheckedAttr + batchCheckboxDisabledAttr + ' />';
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
        // When this keyword row is being edited, render the inline edit form
        // in place of the normal body. The edit form holds its own keyword
        // input + save / cancel buttons. The maxlength matches the keyword
        // create input (200 chars).
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
            '<div class="rules-row ' + (enabled ? "" : "is-disabled") + (batchSelected ? " is-batch-selected" : "") + '">',
            batchCheckbox,
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
            impactButtons,
            '</div>'
        ].join("");
    }
    App.renderProjectRuleRow = renderProjectRuleRow;

    // --- rule impact preview / backfill result panel render ---

    function renderProjectRuleImpactPreview(ruleKey, impact) {
        // Render the read-only impact preview panel below the rules list.
        // The panel shows the rule summary, the skip / count grid, and up
        // to 20 display-safe sample rows. No raw sensitive metadata is
        // ever surfaced — the bridge already filtered the payload to
        // display-safe fields.
        if (!impact) return "";
        var rule = impact.rule || {};
        var counts = impact.counts || {};
        var samples = impact.samples || [];
        var kindLabel = rule.kind === "folder" ? "文件夹规则" : "关键词规则";
        var target = text(rule.target, "未设置");
        var projectName = text(rule.project_name, "未知项目");
        var enabledLabel = rule.enabled ? "已启用" : "已禁用";
        var availLabel = rule.project_available === false ? "目标项目不可用" : "";
        var headerParts = [kindLabel + "：" + target, "归属项目：" + projectName, enabledLabel];
        if (availLabel) headerParts.push(availLabel);
        var header = headerParts.join(" | ");
        var countsGrid = [
            '<div class="rules-impact-counts">',
            '  <div><span>命中数量</span><strong>' + count(counts.matched_count) + '</strong></div>',
            '  <div><span>符合条件</span><strong>' + count(counts.eligible_count) + '</strong></div>',
            '  <div><span>将被更新</span><strong>' + count(counts.would_update_count) + '</strong></div>',
            '  <div><span>已是目标</span><strong>' + count(counts.already_target_count) + '</strong></div>',
            '  <div><span>手动跳过</span><strong>' + count(counts.manual_skipped_count) + '</strong></div>',
            '  <div><span>隐藏跳过</span><strong>' + count(counts.hidden_skipped_count) + '</strong></div>',
            '  <div><span>删除跳过</span><strong>' + count(counts.deleted_skipped_count) + '</strong></div>',
            '  <div><span>进行中跳过</span><strong>' + count(counts.in_progress_skipped_count) + '</strong></div>',
            '  <div><span>非正常跳过</span><strong>' + count(counts.non_normal_skipped_count) + '</strong></div>',
            '</div>'
        ].join("");
        var samplesBlock = "";
        if (samples.length) {
            var rows = samples.map(function (sample) {
                return [
                    '<tr>',
                    '  <td>' + count(sample.activity_id) + '</td>',
                    '  <td>' + text(sample.start_time, "") + '</td>',
                    '  <td>' + text(sample.end_time, "") + '</td>',
                    '  <td>' + App.escapeHtml(App.formatDuration(sample.duration_seconds || 0)) + '</td>',
                    '  <td>' + text(sample.resource_name, "未知") + '</td>',
                    '  <td>' + text(sample.current_project_name, "未归类") + '</td>',
                    '  <td>' + text(sample.target_project_name, "未知项目") + '</td>',
                    '  <td>' + text(sample.match_source, "") + '</td>',
                    '</tr>'
                ].join("");
            }).join("");
            samplesBlock = [
                '<div class="rules-impact-samples">',
                '  <div class="rules-impact-samples-title">预览样本（最多 20 条）</div>',
                '  <table class="rules-impact-samples-table">',
                '    <thead><tr><th>ID</th><th>开始时间</th><th>结束时间</th><th>时长</th><th>资源名称</th><th>当前项目</th><th>目标项目</th><th>匹配来源</th></tr></thead>',
                '    <tbody>' + rows + '</tbody>',
                '  </table>',
                '</div>'
            ].join("");
        } else {
            samplesBlock = '<div class="rules-impact-samples-empty">暂无可预览的样本记录。</div>';
        }
        return [
            '<div class="rules-impact-panel-inner" data-rule-key="' + App.escapeHtml(String(ruleKey || "")) + '">',
            '  <div class="rules-impact-header">',
            '    <div class="rules-impact-title">规则影响预览</div>',
            '    <div class="rules-impact-subtitle">' + header + '</div>',
            '  </div>',
            countsGrid,
            samplesBlock,
            '  <div class="rules-impact-actions">',
            '    <button class="rules-impact-close-button" type="button">关闭</button>',
            '  </div>',
            '</div>'
        ].join("");
    }
    App.renderProjectRuleImpactPreview = renderProjectRuleImpactPreview;

    function renderProjectRuleBackfillResult(ruleKey, result) {
        // Render the narrow backfill result panel. Shows the updated count
        // and skip summary only; no sample rows. The panel auto-includes a
        // close button.
        if (!result) return "";
        var rule = result.rule || {};
        var kindLabel = rule.kind === "folder" ? "文件夹规则" : "关键词规则";
        var target = text(rule.target, "未设置");
        var projectName = text(rule.project_name, "未知项目");
        var header = kindLabel + "：" + target + " | 归属项目：" + projectName;
        var summary = [
            '<div class="rules-impact-counts">',
            '  <div><span>已更新</span><strong>' + count(result.updated_count) + '</strong></div>',
            '  <div><span>命中数量</span><strong>' + count(result.matched_count) + '</strong></div>',
            '  <div><span>符合条件</span><strong>' + count(result.eligible_count) + '</strong></div>',
            '  <div><span>已是目标</span><strong>' + count(result.already_target_count) + '</strong></div>',
            '  <div><span>手动跳过</span><strong>' + count(result.manual_skipped_count) + '</strong></div>',
            '  <div><span>隐藏跳过</span><strong>' + count(result.hidden_skipped_count) + '</strong></div>',
            '  <div><span>删除跳过</span><strong>' + count(result.deleted_skipped_count) + '</strong></div>',
            '  <div><span>进行中跳过</span><strong>' + count(result.in_progress_skipped_count) + '</strong></div>',
            '  <div><span>非正常跳过</span><strong>' + count(result.non_normal_skipped_count) + '</strong></div>',
            '</div>'
        ].join("");
        return [
            '<div class="rules-impact-panel-inner" data-rule-key="' + App.escapeHtml(String(ruleKey || "")) + '">',
            '  <div class="rules-impact-header">',
            '    <div class="rules-impact-title">应用规则结果</div>',
            '    <div class="rules-impact-subtitle">' + header + '</div>',
            '  </div>',
            summary,
            '  <div class="rules-impact-actions">',
            '    <button class="rules-impact-close-button" type="button">关闭</button>',
            '  </div>',
            '</div>'
        ].join("");
    }
    App.renderProjectRuleBackfillResult = renderProjectRuleBackfillResult;

    // --- selected-rule batch operations toolbar + panel -------

    function renderProjectRulesBatchToolbar() {
        // Render the batch toolbar (selected count + 5 buttons). The
        // toolbar is rendered into ``#rules-batch-toolbar`` by ``rules.js``
        // on every list render. Buttons are disabled when there is no
        // selection OR any batch operation is in flight. The clear button
        // is only enabled when there is a selection (it stays enabled
        // during in-flight so the user can cancel a pending selection —
        // but the batch in-flight guard in the handler still refuses to
        // act while a batch op is running, so this is purely visual).
        // visual).
        var selectedCount = Object.keys(App.rulesBatchSelectedKeys || {}).length;
        var hasSelection = selectedCount > 0;
        var inFlight = !!App.rulesBatchInFlight;
        var actionDisabled = (!hasSelection || inFlight) ? " disabled" : "";
        var countLabel = "已选择 " + count(selectedCount) + " 条规则";
        var previewLabel = inFlight ? "正在处理…" : "预览选中规则影响";
        var applyLabel = inFlight ? "正在处理…" : "应用选中规则到历史记录";
        var enableLabel = inFlight ? "正在处理…" : "启用选中规则";
        var disableLabel = inFlight ? "正在处理…" : "停用选中规则";
        var clearLabel = "清空选择";
        var clearDisabled = (!hasSelection || inFlight) ? " disabled" : "";
        return [
            '<div class="rules-batch-toolbar-inner">',
            '  <span class="rules-batch-selected-count">' + countLabel + '</span>',
            '  <button class="rules-batch-preview-button" type="button"' + actionDisabled + '>' + previewLabel + '</button>',
            '  <button class="rules-batch-apply-button" type="button"' + actionDisabled + '>' + applyLabel + '</button>',
            '  <button class="rules-batch-enable-button" type="button"' + actionDisabled + '>' + enableLabel + '</button>',
            '  <button class="rules-batch-disable-button" type="button"' + actionDisabled + '>' + disableLabel + '</button>',
            '  <button class="rules-batch-clear-button" type="button"' + clearDisabled + '>' + clearLabel + '</button>',
            '</div>'
        ].join("");
    }
    App.renderProjectRulesBatchToolbar = renderProjectRulesBatchToolbar;

    function renderProjectRulesBatchPanel(data) {
        // Render the batch panel (aggregate counts + per-rule summaries).
        // The panel is rendered into ``#rules-batch-panel`` by the batch
        // action handlers. ``data`` is
        // ``{mode: "preview"|"apply"|"toggle", payload: {...}}``. No raw
        // sensitive activity detail is ever surfaced here — the bridge
        // already filtered the payload to display-safe aggregate fields.
        if (!data) return "";
        var mode = data.mode || "preview";
        var payload = data.payload || {};
        var title = mode === "preview" ? "批量预览结果"
            : (mode === "apply" ? "批量应用结果" : "批量启用/停用结果");
        var rules = payload.rules || [];
        var aggregate = payload.counts || {};
        var sections = [];
        // Aggregate counts grid (preview / apply modes). Toggle mode has
        // no activity counts, only an enabled bool + count.
        if (mode === "preview" || mode === "apply") {
            var aggRows = [
                '<div><span>命中数量</span><strong>' + count(aggregate.matched_count) + '</strong></div>',
                '<div><span>符合条件</span><strong>' + count(aggregate.eligible_count) + '</strong></div>',
                '<div><span>将被更新</span><strong>' + count(aggregate.would_update_count) + '</strong></div>',
                '<div><span>已是目标</span><strong>' + count(aggregate.already_target_count) + '</strong></div>',
                '<div><span>手动跳过</span><strong>' + count(aggregate.manual_skipped_count) + '</strong></div>',
                '<div><span>隐藏跳过</span><strong>' + count(aggregate.hidden_skipped_count) + '</strong></div>',
                '<div><span>删除跳过</span><strong>' + count(aggregate.deleted_skipped_count) + '</strong></div>',
                '<div><span>进行中跳过</span><strong>' + count(aggregate.in_progress_skipped_count) + '</strong></div>',
                '<div><span>非正常跳过</span><strong>' + count(aggregate.non_normal_skipped_count) + '</strong></div>'
            ];
            if (mode === "apply") {
                aggRows.unshift(
                    '<div><span>已更新</span><strong>' + count(aggregate.updated_count) + '</strong></div>',
                    '<div><span>冲突跳过</span><strong>' + count(aggregate.collision_skipped_count) + '</strong></div>'
                );
            }
            sections.push(
                '<div class="rules-impact-counts">' + aggRows.join("") + '</div>'
            );
        } else {
            // toggle mode: show the resulting enabled state + count
            sections.push(
                '<div class="rules-impact-counts">' +
                '<div><span>已更新规则数</span><strong>' + count(payload.count) + '</strong></div>' +
                '<div><span>目标状态</span><strong>' + (payload.enabled ? "已启用" : "已停用") + '</strong></div>' +
                '</div>'
            );
        }
        // Per-rule summaries. Normalize the entry shape: preview / toggle
        // entries are flat ({kind, id, enabled, project_name, target,
        // project_available, ...}); apply entries are nested
        // ({rule: {...}, counts: {...}}).
        if (rules.length) {
            var ruleRows = rules.map(function (entry) {
                var rule = entry.rule || entry;
                var ruleCounts = entry.counts || null;
                var kindLabel = rule.kind === "folder" ? "文件夹" : "关键词";
                var target = text(rule.target, "未设置");
                var projectName = text(rule.project_name, "未知项目");
                var enabledLabel = rule.enabled ? "已启用" : "已禁用";
                var availLabel = rule.project_available === false ? "目标项目不可用" : "";
                var headParts = [kindLabel + "：" + target, "归属项目：" + projectName, enabledLabel];
                if (availLabel) headParts.push(availLabel);
                var head = headParts.join(" | ");
                var countsLine = "";
                if (ruleCounts) {
                    var parts = [];
                    if (typeof ruleCounts.updated_count === "number") {
                        parts.push("已更新 " + count(ruleCounts.updated_count));
                    }
                    if (typeof ruleCounts.collision_skipped_count === "number") {
                        parts.push("冲突跳过 " + count(ruleCounts.collision_skipped_count));
                    }
                    parts.push("命中 " + count(ruleCounts.matched_count));
                    parts.push("符合条件 " + count(ruleCounts.eligible_count));
                    parts.push("将被更新 " + count(ruleCounts.would_update_count));
                    parts.push("已是目标 " + count(ruleCounts.already_target_count));
                    parts.push("手动跳过 " + count(ruleCounts.manual_skipped_count));
                    countsLine = '<div class="rules-batch-rule-counts">' + App.escapeHtml(parts.join(" | ")) + '</div>';
                }
                return '<div class="rules-batch-rule-summary"><div class="rules-batch-rule-head">' + head + '</div>' + countsLine + '</div>';
            }).join("");
            sections.push(
                '<div class="rules-batch-rules-list">' + ruleRows + '</div>'
            );
        }
        return [
            '<div class="rules-impact-panel-inner" data-batch-mode="' + App.escapeHtml(mode) + '">',
            '  <div class="rules-impact-header">',
            '    <div class="rules-impact-title">' + title + '</div>',
            '  </div>',
            sections.join(""),
            '  <div class="rules-impact-actions">',
            '    <button class="rules-batch-panel-close-button" type="button">关闭</button>',
            '  </div>',
            '</div>'
        ].join("");
    }
    App.renderProjectRulesBatchPanel = renderProjectRulesBatchPanel;

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
