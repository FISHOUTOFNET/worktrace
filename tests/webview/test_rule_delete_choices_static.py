from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

ROOT = Path(__file__).resolve().parents[2]


def test_rule_delete_dialog_exposes_preserve_and_treat_as_absent_modes():
    source = (ROOT / "worktrace/webview_ui/js/rules_delete_actions.js").read_text(
        encoding="utf-8"
    )

    assert 'value: "preserve"' in source
    assert 'label: "保留已有归类"' in source
    assert 'value: "restore"' in source
    assert 'label: "视同规则不存在"' in source
    assert 'defaultChoice: "preserve"' in source
    assert 'historyMode === "restore"' in source
    assert 'warning: "如何处理已有归类？"' in source
    assert "objectLabel:" not in source


def test_rule_enabled_state_is_not_exposed_as_a_user_control_or_status():
    render = (ROOT / "worktrace/webview_ui/js/rules_render.js").read_text(
        encoding="utf-8"
    )
    actions = (ROOT / "worktrace/webview_ui/js/rules_rule_actions.js").read_text(
        encoding="utf-8"
    )

    assert "rules-rule-enabled-toggle" not in render
    assert "停用规则" not in render
    assert "启用规则" not in render
    assert "setProjectRuleEnabled" not in actions
    assert "bindProjectRuleEnabledEvents" not in actions
    assert "visibleRuleDetail" in render
    assert 'return kind(rule && rule.kind) === "folder"' in render
    assert '            : "";' in render
    assert 'style="overflow:visible"' not in render
    assert '<span class="rules-detail"> · ' in render


def test_project_delete_copy_is_final_at_project_owner():
    source = (
        ROOT / "worktrace/webview_ui/js/rules_create_panel_v5.js"
    ).read_text(encoding="utf-8")

    assert 'title: "删除项目"' in source
    assert 'secondTitle: "确认删除项目"' in source
    assert 'secondIntro: "即将删除："' in source
    assert 'warning: "此操作不可撤销。"' in source
    assert 'confirmLabel: "删除项目"' in source
    assert 'App.showToast("项目已删除")' in source
    assert "永久删除项目" not in source
