// WorkTrace WebView frontend — Project Rules module (Phase 5B / 5C).
// Existing project-bound folder / keyword rules can be enabled or disabled
// (Phase 5B), and one new keyword rule can be created on an existing
// rule-target project (Phase 5C).

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
        // Phase 5C: keep the keyword create form's project selector in sync
        // with the freshly loaded Project Rules data. The selector is only
        // re-populated when no keyword create is in flight so an in-flight
        // submit is never displaced by an auto-refresh.
        App.populateKeywordCreateProjectSelector((data && data.projects) || []);
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

    // --- Phase 5C: keyword rule creation foundation -------------------

    function populateKeywordCreateProjectSelector(projects) {
        // Phase 5C: populate the keyword-create project selector from the
        // freshly loaded Project Rules data. Only enabled, non-excluded
        // projects with a positive id are valid targets — this mirrors the
        // ``project_api.list_rule_target_projects()`` eligibility rule the
        // API uses, so the selector only ever offers targets the API will
        // accept. Re-population is skipped entirely while a keyword create
        // is in flight so the user's selection is never displaced by an
        // auto-refresh, and the previous selection is preserved when the
        // list is re-rendered.
        if (App.rulesCreatingKeyword) return;
        var select = document.getElementById("rules-keyword-create-project");
        var submitBtn = document.getElementById("rules-keyword-create-submit");
        var input = document.getElementById("rules-keyword-create-input");
        var emptyHint = document.getElementById("rules-keyword-create-empty");
        if (!select || !submitBtn || !input) return;
        var list = projects || [];
        var targets = [];
        for (var i = 0; i < list.length; i++) {
            var p = list[i];
            if (p && p.enabled && !p.is_excluded && p.id > 0) {
                targets.push(p);
            }
        }
        var previousValue = select.value;
        select.innerHTML = "";
        if (!targets.length) {
            if (emptyHint) emptyHint.hidden = false;
            submitBtn.disabled = true;
            input.disabled = true;
            select.disabled = true;
            return;
        }
        if (emptyHint) emptyHint.hidden = true;
        for (var j = 0; j < targets.length; j++) {
            var opt = document.createElement("option");
            opt.value = String(targets[j].id);
            // ``textContent`` is safe here (no HTML parsing) and the name
            // is already display-safe from the bridge projection.
            opt.textContent = targets[j].name;
            select.appendChild(opt);
        }
        // Preserve the user's previous selection when the project list is
        // refreshed without changing the available targets.
        if (previousValue) {
            for (var k = 0; k < select.options.length; k++) {
                if (select.options[k].value === previousValue) {
                    select.value = previousValue;
                    break;
                }
            }
        }
        select.disabled = false;
        input.disabled = false;
        submitBtn.disabled = false;
    }
    App.populateKeywordCreateProjectSelector = populateKeywordCreateProjectSelector;

    function handleKeywordCreateSubmit() {
        // Phase 5C: validate project id + keyword locally, then call the
        // bridge. Only one keyword create may be in flight at a time. The
        // keyword is trimmed before validation and before the bridge call.
        // On success the keyword input is cleared and the Project Rules
        // list is refreshed; on failure the keyword input is preserved so
        // the user can edit and retry.
        if (App.rulesCreatingKeyword) return;
        var select = document.getElementById("rules-keyword-create-project");
        var input = document.getElementById("rules-keyword-create-input");
        if (!select || !input) return;
        var projectId = parseInt(select.value, 10);
        if (!(projectId > 0)) {
            App.showKeywordCreateStatus("请选择有效的项目", true);
            return;
        }
        var keyword = (input.value || "").trim();
        if (!keyword) {
            App.showKeywordCreateStatus("请输入关键词", true);
            return;
        }
        App.setKeywordCreateCreating(true);
        App.clearKeywordCreateStatus();
        App.callBridge("create_project_keyword_rule", projectId, keyword).then(function (result) {
            if (result && result.ok === false) {
                App.showKeywordCreateStatus(result.error || "新增关键词规则失败", true);
                return;
            }
            input.value = "";
            App.clearKeywordCreateStatus();
            return App.loadProjectRules().then(function () {
                App.showKeywordCreateStatus("关键词规则已新增", false);
            });
        }).catch(function () {
            App.showKeywordCreateStatus("新增关键词规则失败", true);
        }).then(function () {
            App.setKeywordCreateCreating(false);
        });
    }
    App.handleKeywordCreateSubmit = handleKeywordCreateSubmit;

    function setKeywordCreateCreating(creating) {
        // Phase 5C: toggle the keyword create saving state. The state is
        // intentionally separate from ``rulesSavingRuleKey`` (Phase 5B
        // toggle saving) so the two write paths can never pollute each
        // other's button / input disabled state.
        App.rulesCreatingKeyword = creating;
        var btn = document.getElementById("rules-keyword-create-submit");
        var input = document.getElementById("rules-keyword-create-input");
        var select = document.getElementById("rules-keyword-create-project");
        if (btn) {
            btn.disabled = creating;
            btn.textContent = creating ? "正在新增…" : "新增关键词规则";
        }
        if (input) input.disabled = creating;
        if (select) select.disabled = creating;
    }
    App.setKeywordCreateCreating = setKeywordCreateCreating;

    function showKeywordCreateStatus(message, isError) {
        var el = document.getElementById("rules-keyword-create-status");
        if (!el) return;
        if (!message) {
            el.hidden = true;
            el.textContent = "";
            el.className = "rules-keyword-create-status";
            return;
        }
        el.hidden = false;
        el.textContent = message;
        el.className = "rules-keyword-create-status" + (isError ? " is-error" : " is-success");
    }
    App.showKeywordCreateStatus = showKeywordCreateStatus;

    function clearKeywordCreateStatus() {
        App.showKeywordCreateStatus("", false);
    }
    App.clearKeywordCreateStatus = clearKeywordCreateStatus;

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
