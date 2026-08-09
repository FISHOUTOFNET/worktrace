"""Static contracts for concise, user-facing WorkTrace copy."""
from __future__ import annotations

import os
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import read_js  # noqa: E402


def test_shared_copy_policy_removes_routine_explanations() -> None:
    source = read_js("ui_components.js")

    assert 'compactPageHeader("#page-overview")' in source
    assert 'compactPageHeader("#page-timeline")' in source
    assert 'compactPageHeader("#page-rules")' in source
    assert 'compactPageHeader("#page-settings")' in source
    assert 'setSelectorText("#page-statistics .page-header p", "仅统计已完成时段")' in source
    assert 'setSelectorText("#timeline-readonly-notice", "进行中时段不可编辑")' in source
    assert 'hideSelector("#rules-panel-folder-recursive small")' in source
    assert 'hideSelector("#settings-privacy-card small")' in source
    assert 'hideSelector("#settings-storage-card small")' in source
    assert 'statsScopeRow.hidden = true' in source
    assert '"本地项目；也可选择 FD Work 案件": ""' in source
    assert '"已取消 FD Work 关联，将作为本地项目保存": "已取消 FD Work 关联"' in source
    assert 'status.textContent = "";' in source


def test_shared_confirmation_copy_keeps_only_decision_relevant_risk() -> None:
    source = read_js("ui_components.js")

    assert 'normalized.warning = "此操作不可撤销。";' in source
    assert 'normalized.secondIntro = "即将删除：";' in source
    assert 'normalized.warning = "当前数据将被备份替换，且不可撤销。";' in source
    assert 'normalized.secondTitle.replace(/永久/g, "")' in source
    assert 'normalized.confirmLabel.replace(/永久/g, "")' in source
    assert 'return "项目已删除";' in source


def test_rule_delete_copy_uses_plain_user_terms() -> None:
    source = read_js("rules_keyword_actions.js")

    assert 'warning: "如何处理已有归类？"' in source
    assert 'label: "保留已有归类"' in source
    assert 'label: "视同规则不存在"' in source
    assert 'description:' not in source
    assert 'App.showToast("规则已删除")' in source
