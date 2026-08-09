from __future__ import annotations

import pytest

from static_helpers import read_js

pytestmark = [pytest.mark.contract, pytest.mark.webview_static]


def test_fd_work_project_identity_does_not_reach_into_rules_panel_state() -> None:
    source = read_js("fd_work_v5.js")
    forbidden = (
        "App.rulesPanel",
        "App.rulesCreating",
        "App.rulesChoosing",
        "App.loadProjectRules",
        "App.refreshRulesPanelWriteState",
    )
    for marker in forbidden:
        assert marker not in source, f"FD Work identity must not depend on Rules internals: {marker}"

    assert "bindHost: bindIdentityHost" in source
    assert "editorGeneration" in source
    assert "editingProjectId" in source
    assert "projectBusy" in source


def test_rules_owner_explicitly_binds_project_identity_host() -> None:
    source = read_js("rules_create_panel_v5.js")
    assert "App.projectIdentity.bindHost({" in source
    assert "onStateChanged: refreshPanelWriteState" in source
    assert "onBindingChanged: function ()" in source
