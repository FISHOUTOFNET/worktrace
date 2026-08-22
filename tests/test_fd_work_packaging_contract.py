from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = [pytest.mark.contract, pytest.mark.parallel_safe]
ROOT = Path(__file__).resolve().parents[1]


def test_fd_work_adapter_is_explicitly_packaged():
    spec = (ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
    assert "'fd_work' / 'fd_work_adapter.js'" in spec
    assert "'worktrace/integrations/fd_work'" in spec


def test_fd_work_does_not_change_database_schema():
    for name in ("schema.sql", "schema_internal.sql", "schema_indexes.sql"):
        source = (ROOT / "worktrace" / name).read_text(encoding="utf-8").lower()
        assert "fd_work" not in source


def test_fd_work_does_not_enter_projection_statistics_export_or_collector_hot_paths():
    protected = (
        ROOT / "worktrace" / "services" / "report_projection_provider.py",
        ROOT / "worktrace" / "services" / "report_projection_builder.py",
        ROOT / "worktrace" / "services" / "statistics_service.py",
        ROOT / "worktrace" / "services" / "export_service.py",
        ROOT / "worktrace" / "collector" / "collector.py",
    )
    for path in protected:
        if path.exists():
            assert "integrations.fd_work" not in path.read_text(encoding="utf-8")


def test_timeline_eligibility_uses_binding_only_and_never_case_search():
    draft_builder = (
        ROOT / "worktrace" / "integrations" / "fd_work" / "draft_builder.py"
    ).read_text(encoding="utf-8")
    timeline = (
        ROOT / "worktrace" / "webview_ui" / "js" / "timeline.js"
    ).read_text(encoding="utf-8")
    assert "require_project_binding" in draft_builder
    assert "search_cases" not in draft_builder
    assert "searchFDWorkCases" not in timeline


def test_persistent_webview_profile_stays_outside_backup_and_cookie_apis():
    webview_main = (ROOT / "worktrace" / "webview_main.py").read_text(
        encoding="utf-8"
    )
    backup = (
        ROOT / "worktrace" / "services" / "secure_backup_service.py"
    ).read_text(encoding="utf-8")
    fd_work_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "worktrace" / "integrations" / "fd_work").glob("*.py")
    )

    assert '"webview-profile"' in webview_main
    assert "private_mode=False" in webview_main
    assert "webview-profile" not in backup
    assert "plugins/fd_work" not in backup.replace("\\\\", "/")
    assert "state.db" not in backup
    assert "get_cookies(" not in webview_main
    assert "get_cookies(" not in fd_work_sources


def test_helper_bridge_binds_only_the_page_adapter_action_result_sink():
    webview_main = (ROOT / "worktrace" / "webview_main.py").read_text(
        encoding="utf-8"
    )

    assert "action_result_sink=fd_work_page_adapter" in webview_main


def test_deferred_ui_modules_remain_statically_discoverable_for_packaging():
    webview_main = (ROOT / "worktrace" / "webview_main.py").read_text(
        encoding="utf-8"
    )
    loader_start = webview_main.index("def _load_ui_components()")
    loader_end = webview_main.index("def _prepare_webview", loader_start)
    loader = webview_main[loader_start:loader_end]

    for module in (
        ".desktop.shell",
        ".desktop.windows_icons",
        ".desktop.windows_webview_power",
        ".integrations.fd_work.helper_bridge",
        ".integrations.fd_work.interaction_coordinator",
        ".integrations.fd_work.main_window_sink",
        ".integrations.fd_work.page_adapter",
        ".integrations.fd_work.window_controller",
        ".webview_ui.bridge",
    ):
        assert f"from {module} import" in loader
    assert "collect_all('webview')" in (ROOT / "WorkTrace.spec").read_text(
        encoding="utf-8"
    )
