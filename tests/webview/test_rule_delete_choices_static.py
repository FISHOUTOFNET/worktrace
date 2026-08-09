from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]

ROOT = Path(__file__).resolve().parents[2]


def test_rule_delete_dialog_exposes_preserve_and_restore_history_modes():
    source = (ROOT / "worktrace/webview_ui/js/rules_keyword_actions.js").read_text(
        encoding="utf-8"
    )

    assert 'value: "preserve"' in source
    assert 'label: "保留已有归类"' in source
    assert 'value: "restore"' in source
    assert 'label: "恢复原状"' in source
    assert 'defaultChoice: "preserve"' in source
    assert 'historyMode === "restore"' in source
    assert "排除该规则后按其他现有规则重新判断" in source
    assert "没有其他规则匹配时恢复为“未归类”" in source
    assert "手动修改过的归属不受影响" in source


def test_project_delete_dialog_states_irreversible_release_semantics():
    source = (ROOT / "worktrace/webview_ui/js/rules_create_panel_v5.js").read_text(
        encoding="utf-8"
    )

    assert "此操作不可撤销" in source
    assert "全部自动归类规则将永久删除" in source
    assert "释放为“未归类”" in source
    assert "活动事实、时长、描述及其他时间编辑不会被删除" in source
    assert "twoStep: true" in source
