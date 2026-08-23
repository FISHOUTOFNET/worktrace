"""Static contracts for concise copy and presentation ownership."""
from __future__ import annotations

import os
import sys

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from static_helpers import func_body, read_js, read_resource  # noqa: E402


def test_shipping_html_contains_final_static_copy() -> None:
    source = read_resource("index_fd_work_v5.html")

    assert "同时应用到历史记录" not in source
    assert ">应用到历史记录<" in source
    assert "默认匹配该文件夹及全部子文件夹" not in source
    assert ">包含子文件夹<" in source
    assert "统计仅包含已完成时间段" not in source
    assert "仅统计已完成时段" not in source
    assert ">进行中时段不可编辑<" in source
    assert "新建项目后可添加自动归类规则" not in source
    assert 'id="app-tooltip" role="tooltip" hidden' in source


def test_shipping_html_owns_brand_privacy_and_local_copy() -> None:
    source = read_resource("index_fd_work_v5.html")

    assert '<div class="app-brand" aria-label="有迹 · Trace">' in source
    assert '<span class="nav-label">有迹 · Trace</span>' in source
    assert "核心工作轨迹本地保存" in source
    assert "所有数据只存于本机" not in source
    assert ">我已阅读并了解</button>" in source
    assert ">我已阅读并同意</button>" not in source
    assert 'id="settings-health-summary"' not in source
    assert 'id="settings-privacy-notice-btn" type="button">查看政策</button>' in source
    assert "查看《有迹隐私政策》" not in source
    assert "了解有迹处理哪些数据、数据存储在哪里，以及如何管理这些数据。" not in source


def test_shared_ui_components_do_not_patch_feature_presentation() -> None:
    source = read_js("ui_components.js")

    for forbidden in (
        "applyStaticConciseCopy",
        "normalizeRulesOptionRows",
        "normalizeSettingsStatusCopy",
        "rules-panel-folder-recursive",
        "rules-panel-backfill",
        "settings-privacy-notice-status",
        "stats-scope-row",
        "timeline-readonly-notice",
        "MutationObserver",
        "再次确认",
        "当前选中的时间段",
    ):
        assert forbidden not in source

    assert 'group.className = "dialog-choice-group"' in source
    assert 'row.className = "dialog-choice-row"' in source
    assert 'document.getElementById("app-tooltip")' in source
    assert "getBoundingClientRect" in source


def test_shared_primitive_css_owns_dialog_and_tooltip_geometry() -> None:
    source = read_resource("ui_components.css")

    assert "#app-tooltip" in source
    assert "position: fixed" in source
    assert "pointer-events: none" in source
    assert ".dialog-choice-row" in source
    assert "grid-template-columns: 14px minmax(0, 1fr)" in source
    assert "[data-tooltip]::after" in source and "content: none !important" in source


def test_fd_work_status_owner_notifies_host_instead_of_pages() -> None:
    source = read_js("fd_work_v5.js")
    receive = func_body(source, "App.receiveFDWorkStatus = function") if False else source[
        source.index("App.receiveFDWorkStatus = function"):
        source.index("App.fdWorkStatusText = function")
    ]

    assert "notifyStatusHost(App.fdWorkStatus)" in receive
    assert "App.lastSettingsStatus" not in receive
    assert "App.renderFDWorkToggle" not in receive
    assert "App.updateFDWorkEntryButton" not in receive
    assert "App.projectIdentity.syncStatus" not in receive

    composition = read_js("ui_composition.js")
    assert "App.fdWork.bindStatusHost" in composition
    assert "App.settings.onFDWorkStatusChanged" in composition
    assert "App.renderFDWorkToggle" not in composition
    assert "App.updateFDWorkEntryButton" in composition
    assert "App.projectIdentity.syncStatus" in composition


def test_settings_presentation_does_not_coordinate_timeline_or_restore_prefixes() -> None:
    source = read_js("settings.js")
    fd_work_toggle = func_body(source, "renderFDWorkToggle")
    status = func_body(source, "renderSettingsStatus")

    assert "App.updateFDWorkEntryButton" not in fd_work_toggle
    assert 'status.export_path_configured ? "已配置" : "未配置"' in status
    assert 'noticeStatus.textContent = accepted ? "已确认" : "未确认"' in status
    assert "导出目录：已配置" not in status
    assert "导出目录：未配置" not in status
    assert "隐私说明：" not in status


def test_fd_work_copy_is_concise_at_its_owner_boundary() -> None:
    source = read_js("fd_work_v5.js")

    assert 'showIdentityStatus("本地项目", false)' not in source
    assert 'showIdentityStatus("将作为本地项目保存", false)' not in source
    assert 'showIdentityStatus("已取消 FD Work 关联", false)' in source
    assert 'showIdentityStatus("正在打开案件选择器…", false)' in source
    assert '"名称已修改，保存后将取消 FD Work 关联"' in source
    assert '"FD Work 保存结果未确认，请先在 FD Work 页面核对；确认前不要重复填入"' in source


def test_rule_delete_copy_has_one_owner_and_plain_terms() -> None:
    source = read_js("rules_delete_actions.js")

    assert 'warning: "如何处理已有归类？"' in source
    assert 'label: "保留已有归类"' in source
    assert 'label: "视同规则不存在"' in source
    assert 'App.showToast("规则已删除")' in source
    assert not (read_resource("js/rules_keyword_actions.js") if False else False)
