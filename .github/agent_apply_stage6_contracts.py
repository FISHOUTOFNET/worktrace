from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise AssertionError(f"{path}: expected one replacement, found {count}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


def replace_test(path: str, name: str, body: str) -> None:
    content = read(path)
    pattern = re.compile(
        rf"(?ms)^def {re.escape(name)}\([^\n]*\).*?(?=^def |^class |\Z)"
    )
    match = pattern.search(content)
    if match is None:
        raise AssertionError(f"{path}: test function not found: {name}")
    replacement = textwrap.dedent(body).rstrip() + "\n\n\n"
    write(path, content[: match.start()] + replacement + content[match.end() :])


def update_live_harness() -> None:
    path = "tests/support/live_semantics_harness.py"
    replace_once(
        path,
        '''        return {
            "overview": self.bridge.get_overview(),
            "recent": self.bridge.get_recent_activities(),
            "timeline": timeline,
''',
        '''        overview = self.bridge.get_overview()
        return {
            "overview": overview,
            "recent": {
                "ok": bool(overview.get("ok")),
                "items": list(overview.get("recent_activities") or []),
                "runtime": dict(overview.get("runtime") or {}),
            },
            "timeline": timeline,
''',
    )


def update_runtime_contract_tests() -> None:
    replace_test(
        "tests/test_architecture_consolidation_validation.py",
        "test_session_summary_api_calls_keyword_only_service",
        '''
        def test_session_summary_api_calls_keyword_only_service(monkeypatch):
            captured: dict[str, object] = {}

            def fake_summary(
                *,
                report_date: str | None = None,
                projection_instance_key: str,
                expected_projection_revision: str | None = None,
            ) -> dict[str, object]:
                captured.update(
                    {
                        "report_date": report_date,
                        "projection_instance_key": projection_instance_key,
                        "expected_projection_revision": expected_projection_revision,
                    }
                )
                return {"ok": True, "summary_rows": []}

            monkeypatch.setattr(
                view_model_service,
                "get_session_activity_summary_view_model",
                fake_summary,
            )

            result = view_model_api.get_session_activity_summary_view_model(
                report_date="2026-07-16",
                projection_instance_key="session:1",
                expected_projection_revision="a" * 40,
            )

            assert result["ok"] is True
            assert result["summary_rows"] == []
            assert result["runtime"]["schema_version"] == 1
            assert result["runtime"]["surface"] == "details"
            assert result["runtime"]["scope_report_date"] == "2026-07-16"
            assert captured == {
                "report_date": "2026-07-16",
                "projection_instance_key": "session:1",
                "expected_projection_revision": "a" * 40,
            }
        ''',
    )

    path = "tests/test_collector.py"
    replace_once(
        path,
        '    assert result == {"ok": True, "pause_pending": False}\n',
        '''    assert result["ok"] is True
    assert result["pause_pending"] is False
    assert result["command_state"] == "completed"
    assert result["command_state_unknown"] is False
    assert isinstance(result["command_id"], str) and result["command_id"]
''',
    )

    path = "tests/test_runtime_startup_handshake_contract.py"
    content = read(path)
    content = content.replace(
        "assert runtime.phase is RuntimePhase.FAILED",
        "assert runtime.phase is RuntimePhase.RECOVERABLE_FAILURE",
        3,
    )
    content = content.replace(
        "    assert runtime.stop_event.is_set()\n",
        "    assert runtime.stop_event.is_set() is False\n",
        1,
    )
    write(path, content)

    path = "tests/test_webview_entry.py"
    replace_once(
        path,
        '    for method_name in ("get_status", "toggle_pause", "get_overview", "get_recent_activities"):\n',
        '    for method_name in ("get_status", "toggle_pause", "get_overview"):\n',
    )


def update_frontend_static_contracts() -> None:
    replace_test(
        "tests/webview/test_frontend_global_boundaries.py",
        "test_frontend_module_all_functions_still_defined",
        '''
        def test_frontend_module_all_functions_still_defined():
            """Every shipping entry point remains defined without dynamic bridge dispatch."""
            source = read_all_js()
            required_functions = [
                "showError", "clearError", "showTimelineError", "clearTimelineError",
                "setTimelineLoading", "statusClassFor", "applyStatusType",
                "setTimelineStatus", "setDetailStatus", "setEditStatus",
                "handleResult", "showStatus", "safeText", "escapeHtml",
                "formatTimeRange", "shiftDate", "localTodayStr", "formatDuration",
                "showOverview", "showRecent", "showTimeline", "selectTimelineSession",
                "loadSessionDetails", "renderSessionDetails", "loadTimeline",
                "refreshTimeline", "goPrevDay", "goNextDay", "goToday",
                "loadProjects", "populateEditPanel", "clearEditPanel", "isEditDirty",
                "saveEdit", "cancelEdit", "updateNoteCount", "showEditStatus",
                "setEditSaving", "refreshTimelineAfterEdit",
                "loadStatisticsExportSummary", "showStatistics", "renderStatsTable",
                "validateStatisticsDateRange", "applyStatisticsQuickRange",
                "initStatisticsDefaults", "exportStatisticsCsv", "togglePause",
                "switchPage", "initNav", "initButtons", "startHeartbeat", "init",
            ]
            missing = [
                name for name in required_functions
                if source.find("function " + name + "(") == -1
            ]
            assert not missing, "missing frontend functions: " + ", ".join(missing)
            assert "App.refreshAll = function" in source
            assert "App.callBridge" not in source
            assert "window.pywebview.api" not in source
            all_decls = re.findall(r'\n    function \w+\s*\(', source)
            assert len(all_decls) >= 138
        ''',
    )

    replace_test(
        "tests/webview/test_project_rules_static_contract.py",
        "test_project_rules_panel_create_backfill_contract_is_stable",
        '''
        def test_project_rules_panel_create_backfill_contract_is_stable():
            source = read_rules_module_js()
            body = func_body(source, "savePanelRule")
            assert "App.bridge.createProjectFolderRule" in body
            assert "App.bridge.createProjectKeywordRule" in body
            assert "App.backfillCreatedRule" in body
            assert "规则已新增，但应用到历史记录失败" in body
            assert "同时应用到历史记录（推荐）" in _rules_section()
            assert ".catch(function ()" in body
            for forbidden in ("err.message", "error.message", "reason.message", ".toString"):
                assert forbidden not in body
        ''',
    )
    replace_test(
        "tests/webview/test_project_rules_static_contract.py",
        "test_project_rules_sort_state_is_memory_only",
        '''
        def test_project_rules_sort_state_is_memory_only():
            source = read_rules_module_js()
            assert 'App.rulesSortMode = "last_used"' in read_js("core.js")
            assert "localStorage" not in source
            assert "sessionStorage" not in source
            assert "function sortProjectsForRulesHome" in source
        ''',
    )

    settings_path = "tests/webview/test_settings_static_contract.py"
    replace_test(
        settings_path,
        "test_settings_js_defines_load_settings_privacy_status",
        '''
        def test_settings_js_defines_load_settings_privacy_status() -> None:
            source = read_js("settings.js")
            assert "App.loadSettingsPrivacyStatus" in source
            assert "App.bridge.getSettingsPrivacyStatus()" in source
            assert "App.callBridge" not in source
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_only_calls_allowed_bridge_methods",
        '''
        def test_settings_js_only_calls_allowed_bridge_methods() -> None:
            source = read_js("settings.js")
            for method in (
                "getSettingsPrivacyStatus", "setClipboardCaptureEnabled",
                "exportEncryptedBackup", "previewEncryptedBackupManifest",
                "importEncryptedBackup", "clearAllLocalData",
                "getFirstRunNotice", "acceptFirstRunNotice",
            ):
                assert "App.bridge." + method in source
            for forbidden in (
                "parseEncryptedBackupManifest", "setSettingValue", "saveSettings"
            ):
                assert "App.bridge." + forbidden not in source
            assert "App.callBridge" not in source
            assert "window.pywebview.api" not in source
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_defines_backup_helpers",
        '''
        def test_settings_js_defines_backup_helpers() -> None:
            source = read_js("settings.js")
            named = (
                "setSettingsBackupControlsDisabled", "setSettingsBackupStatus",
                "renderBackupManifest", "exportEncryptedBackup",
                "previewEncryptedBackupManifest",
            )
            assigned = ("clearSettingsBackupStatus",)
            for name in named:
                assert "function " + name in source
                assert "App." + name in source
            for name in assigned:
                assert "App." + name + " = function" in source
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_backup_does_not_persist_passphrase",
        '''
        def test_settings_js_backup_does_not_persist_passphrase() -> None:
            source = read_js("settings.js")
            body = func_body(source, "exportEncryptedBackup")
            assert "var passphrase" in body
            assert "var confirmation" in body
            assert 'passInput.value = ""' in body
            assert 'confirmInput.value = ""' in body
            for forbidden in (
                "App.passphrase", "App.confirmation", "App.backupPassphrase"
            ):
                assert forbidden not in body
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_defines_import_and_clear_helpers",
        '''
        def test_settings_js_defines_import_and_clear_helpers() -> None:
            source = read_js("settings.js")
            named = (
                "setSettingsImportStatus", "setSettingsClearStatus",
                "importEncryptedBackup", "clearAllLocalData",
                "setSettingsDangerControlsDisabled",
            )
            assigned = (
                "clearSettingsImportStatus", "clearSettingsClearStatus",
                "clearBackupManifestPreview",
            )
            for name in named:
                assert "function " + name in source
                assert "App." + name in source
            for name in assigned:
                assert "App." + name + " = function" in source
            init_source = read_js("init.js")
            assert "function resetClientGeneration(reason)" in init_source
            assert "App.resetClientGeneration = resetClientGeneration" in init_source
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_import_clear_uses_text_content",
        '''
        def test_settings_js_import_clear_uses_text_content() -> None:
            source = read_js("settings.js")
            assert "innerHTML" not in source
            status_body = func_body(source, "setStatusLine")
            assert "textContent" in status_body
            for name in ("setSettingsImportStatus", "setSettingsClearStatus"):
                assert "function " + name in source
                assert "setStatusLine" in func_body(source, name)
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_reset_frontend_after_local_data_replacement",
        '''
        def test_settings_js_reset_frontend_after_local_data_replacement() -> None:
            source = read_js("init.js")
            body = func_body(source, "resetClientGeneration")
            for token in (
                "App.timelineLoaded = false", "App.statisticsLoaded = false",
                "App.rulesLoaded = false", "App.projectsCache = null",
                "App.currentSessions = []",
                "App.selectedProjectionInstanceKey = null",
                "App.detailsOwner = null", "App.mutationOwner = null",
                "App.lastRefreshState = null", "liveRuntimeStore.reset()",
                "App._monotonicRenderState = {}",
            ):
                assert token in body
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_import_clear_refresh_status_and_overview",
        '''
        def test_settings_js_import_clear_refresh_status_and_overview() -> None:
            source = read_js("settings.js")
            for name, reason in (
                ("importEncryptedBackup", "secure_import"),
                ("clearAllLocalData", "clear_all_local_data"),
            ):
                body = func_body(source, name)
                assert "loadSettingsPrivacyStatus()" in body
                assert "App.refreshAll" in body
                assert f'App.resetClientGeneration("{reason}")' in body
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_render_first_run_notice_hides_close_in_gate_mode",
        '''
        def test_settings_js_render_first_run_notice_hides_close_in_gate_mode() -> None:
            source = read_js("settings.js")
            body = func_body(source, "renderFirstRunNotice")
            assert 'var accept = element("first-run-notice-accept-btn")' in body
            assert 'var close = element("first-run-notice-close-btn")' in body
            assert 'accept.hidden = mode === "view"' in body
            assert 'close.hidden = mode !== "view"' in body
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_backup_controls_not_dependent_on_settingsLoaded",
        '''
        def test_settings_js_backup_controls_not_dependent_on_settingsLoaded() -> None:
            source = read_js("settings.js")
            body = func_body(source, "setSettingsBackupControlsDisabled")
            assert "settingsLoaded" not in body
            assert ".forEach(function (id) { setDisabled(id, disabled); })" in body
        ''',
    )
    replace_test(
        settings_path,
        "test_settings_js_danger_controls_not_dependent_on_settingsLoaded",
        '''
        def test_settings_js_danger_controls_not_dependent_on_settingsLoaded() -> None:
            source = read_js("settings.js")
            body = func_body(source, "setSettingsDangerControlsDisabled")
            assert "settingsLoaded" not in body
            assert 'setDisabled("settings-clear-confirm", disabled)' in body
            assert 'setDisabled("settings-clear-local-data-btn", disabled)' in body
        ''',
    )

    statistics_path = "tests/webview/test_statistics_static_contract.py"
    replace_test(
        statistics_path,
        "test_frontend_js_statistics_export_only_via_bridge",
        '''
        def test_frontend_js_statistics_export_only_via_bridge():
            source = read_all_js()
            assert "function exportStatisticsCsv" in source
            assert "App.bridge.exportStatisticsCsv(" in source
            assert "App.callBridge" not in source
            lowered = source.lower()
            for forbidden in (
                "exportexcel", "exportpdf", "exporttimesheet", "savefile",
                "saveas", "opensavefile", "createfile", "writefile",
                "write_file", "openfolder", "open_folder", "shell.open",
                "window.pywebview.api.export",
            ):
                assert forbidden not in lowered
        ''',
    )
    replace_test(
        statistics_path,
        "test_frontend_js_statistics_export_calls_bridge_export_statistics_csv",
        '''
        def test_frontend_js_statistics_export_calls_bridge_export_statistics_csv():
            source = read_all_js()
            assert "App.bridge.exportStatisticsCsv(" in source
            assert "App.callBridge" not in source
        ''',
    )
    replace_test(
        statistics_path,
        "test_frontend_js_statistics_export_saving_guard_present",
        '''
        def test_frontend_js_statistics_export_saving_guard_present():
            source = read_all_js()
            assert "App.statisticsExportSaving = false" in source
            body = func_body(source, "exportStatisticsCsv")
            assert "App.statisticsExportSaving" in body
            assert "App.statisticsLoading" in body
            set_load_body = func_body(source, "setStatisticsLoading")
            assert "statisticsExportSaving" in set_load_body
        ''',
    )
    replace_test(
        statistics_path,
        "test_frontend_js_statistics_load_and_export_use_independent_state",
        '''
        def test_frontend_js_statistics_load_and_export_use_independent_state():
            source = read_all_js()
            assert "App.statisticsLoading" in source
            assert "App.statisticsExportSaving" in source
            export_body = func_body(source, "exportStatisticsCsv")
            assert "App.statisticsExportSaving" in export_body
            assert "App.statisticsLoading" in export_body
            load_body = func_body(source, "loadStatisticsExportSummary")
            assert "App.statisticsLoading" in load_body
        ''',
    )


def harden_activity_factory() -> None:
    path = "tests/support/activity_factory.py"
    content = read(path)
    content = content.replace(
        '''Tests may create durable activity facts directly through the repository without
invoking production lifecycle inference. Read methods not defined here are
forwarded to the production activity query service so existing tests can migrate
by changing only their import boundary.
''',
        '''Tests may create durable activity facts directly through the repository without
invoking production lifecycle inference. Production query helpers are exported
explicitly below; unsupported names fail immediately instead of being forwarded
through a dynamic fallback.
''',
    )
    content = content.replace("    del note\n", "", 2)
    content = content.replace("    **_ignored: Any,\n", "")
    old_open = '''    with get_connection() as conn:
        return activity_fact_repository.insert_open_activity(conn, prepared)
'''
    new_open = '''    with get_connection() as conn:
        activity_id = activity_fact_repository.insert_open_activity(conn, prepared)
        if note is not None:
            conn.execute(
                "UPDATE activity_log SET note = ?, updated_at = ? WHERE id = ?",
                (str(note), now_str(), activity_id),
            )
        return activity_id
'''
    if content.count(old_open) != 1:
        raise AssertionError("activity factory open insertion target changed")
    content = content.replace(old_open, new_open, 1)
    old_closed = '''    with get_connection() as conn:
        activity_id = activity_fact_repository.insert_open_activity(conn, prepared)
        activity_fact_repository.close_activity(conn, activity_id, f"{day} {end}")
    return activity_id
'''
    new_closed = '''    with get_connection() as conn:
        activity_id = activity_fact_repository.insert_open_activity(conn, prepared)
        if note is not None:
            conn.execute(
                "UPDATE activity_log SET note = ?, updated_at = ? WHERE id = ?",
                (str(note), now_str(), activity_id),
            )
        activity_fact_repository.close_activity(conn, activity_id, f"{day} {end}")
    return activity_id
'''
    if content.count(old_closed) != 1:
        raise AssertionError("activity factory closed insertion target changed")
    content = content.replace(old_closed, new_closed, 1)
    dynamic_start = content.find("\ndef __getattr__(name: str):")
    if dynamic_start < 0:
        raise AssertionError("activity factory dynamic fallback not found")
    content = content[:dynamic_start].rstrip() + "\n\n"

    production_tree = ast.parse(read("worktrace/services/activity_service.py"))
    factory_tree = ast.parse(content)
    production_names = sorted(
        node.name
        for node in production_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    )
    owned_names = {
        node.name
        for node in factory_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    explicit_names = [name for name in production_names if name not in owned_names]
    content += "# Explicit production query/edit aliases used by tests.\n"
    for name in explicit_names:
        content += f"{name} = _activity_queries.{name}\n"
    content += "\n__all__ = [name for name in globals() if not name.startswith('_')]\n"
    write(path, content)


def update_docs() -> None:
    path = "architecture.md"
    content = read(path)
    content = content.replace(
        "- startup ordering of background workers before the collector,\n",
        "- authorization, collector readiness, and only then derived-worker startup,\n",
    )
    content = content.replace(
        '''`worktrace/services/view_model_service.py` assembles:

- Overview,
- Timeline,
- Details,
- Refresh State.

It coordinates canonical projection and live runtime inputs, then emits UI-ready dictionaries. It does not own SQL writes or collector lifecycle.

The frontend accepts runtime payloads through one structured path into `App.liveRuntime`. UI code does not mutate runtime fields independently.
''',
        '''`worktrace/api/view_model_api.py` is the sole bridge-facing page transport boundary. Page-specific services assemble Overview, Timeline, Details, and Refresh State domain payloads inside a shared `page_read_scope`; the API then attaches the versioned `runtime` envelope without taking another sample or opening another database snapshot.

`worktrace/services/live_runtime_envelope_service.py` is a pure transport projector. It owns `schema_version`, page/live report-date separation, revision identity, and continuity fields, but it performs no database reads.

The frontend accepts runtime payloads only through `App.liveRuntimeStore.acceptEnvelope`. `App.liveRuntime` is a read-only getter backed by that store. Shipping JavaScript uses the fixed `App.bridge` capability object; dynamic method-name dispatch and direct `window.pywebview.api` access are prohibited.
''',
    )
    content += textwrap.dedent(
        '''

        ## Runtime recovery and maintenance commands

        Collector startup uses an attempt-local stop event and generation. A failed or timed-out attempt enters `RECOVERABLE_FAILURE` without setting the application shutdown event, so the same `AppRuntime` can retry safely. Application shutdown remains the only owner of the process-wide stop event.

        Pause and reset use command IDs with explicit `PENDING`, `TAKEN`, `COMPLETED`, `CANCELLED`, and `UNKNOWN` states. An unclaimed timeout is cancelled atomically. A claimed command whose result cannot be confirmed is fail-closed: destructive maintenance does not start, collection remains paused, and process-local live state is cleared.

        Secure import and clear-all advance one frontend client generation through `App.resetClientGeneration(reason)`. That reset invalidates request epochs, owners, selections, caches, refresh state, the live-runtime store, and monotonic render state before the replacement database is rendered.
        '''
    )
    write(path, content)

    path = "docs/current-state.md"
    content = read(path)
    content += textwrap.dedent(
        '''

        ## Canonical runtime boundaries

        - `view_model_api` is the only bridge-facing owner that attaches `runtime.schema_version = 1` to Overview, Timeline, Details, and Refresh State payloads.
        - `LiveRuntimeStore` is the sole frontend runtime writer; `App.liveRuntime` is read-only.
        - Shipping JavaScript calls a fixed `App.bridge` method surface. Dynamic bridge dispatch is not supported.
        - Collector startup failure is recoverable unless an attempt cannot be stopped. Maintenance commands carry command IDs and explicit terminal states; unknown completion remains fail-closed and paused.
        - Secure import and clear-all use the single client-generation reset before reloading Settings and page state.
        - Release evidence is valid only for the commit returned by `git rev-parse HEAD` after checkout.
        '''
    )
    write(path, content)


def harden_ci_exact_head() -> None:
    path = ".github/workflows/ci.yml"
    content = read(path)
    checkout = '''      - name: Check out exact event revision
        uses: actions/checkout@v6
        with:
          ref: ${{ github.event.pull_request.head.sha || github.sha }}
          clean: true
          show-progress: false
'''
    verification = checkout + '''
      - name: Verify exact tested head
        id: tested-head
        shell: pwsh
        run: |
          $ExpectedHead = "${{ github.event.pull_request.head.sha || github.sha }}"
          $ActualHead = (git rev-parse HEAD).Trim()
          "expected_head=$ExpectedHead" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
          "actual_head=$ActualHead" | Out-File -FilePath $env:GITHUB_OUTPUT -Append -Encoding utf8
          Write-Host "expected head: $ExpectedHead"
          Write-Host "actual head:   $ActualHead"
          if ($ExpectedHead -and $ActualHead -ne $ExpectedHead) {
            throw "Checked-out commit does not match the requested validation head"
          }
'''
    if content.count(checkout) < 1:
        raise AssertionError("CI checkout block not found")
    content = content.replace(checkout, verification, 1)
    content = content.replace(
        '            "tested_head=$env:GITHUB_SHA",\n',
        '            "tested_head=${{ steps.tested-head.outputs.actual_head }}",\n            "expected_head=${{ steps.tested-head.outputs.expected_head }}",\n',
        1,
    )
    write(path, content)


def add_architecture_boundary_test() -> None:
    write(
        "tests/test_shipping_frontend_capability_contract.py",
        textwrap.dedent(
            '''\
            from pathlib import Path


            ROOT = Path(__file__).resolve().parents[1]
            JS_DIR = ROOT / "worktrace" / "webview_ui" / "js"


            def test_every_packaged_javascript_module_uses_fixed_bridge_and_runtime_store():
                spec = (ROOT / "WorkTrace.spec").read_text(encoding="utf-8")
                packaged = [
                    path for path in sorted(JS_DIR.glob("*.js")) if path.name in spec
                ]
                assert packaged
                source = "\n".join(path.read_text(encoding="utf-8") for path in packaged)
                assert "App.callBridge" not in source
                assert "window.pywebview.api" not in source
                assert "App.liveRuntime =" not in source
                assert "set: function (value)" not in source
                assert "App.liveRuntimeStore.acceptEnvelope" in source


            def test_activity_factory_has_no_dynamic_production_fallback():
                source = (ROOT / "tests" / "support" / "activity_factory.py").read_text(
                    encoding="utf-8"
                )
                assert "def __getattr__" not in source
                assert "**_ignored" not in source
                assert "del note" not in source
                assert "get_activity = _activity_queries.get_activity" in source
            '''
        ),
    )


def verify() -> None:
    all_js = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "worktrace/webview_ui/js").glob("*.js"))
    )
    if "App.callBridge" in all_js or "window.pywebview.api" in all_js:
        raise AssertionError("dynamic bridge access remains in shipping JavaScript")
    factory = read("tests/support/activity_factory.py")
    if "def __getattr__" in factory or "**_ignored" in factory or "del note" in factory:
        raise AssertionError("activity fixture still masks contract drift")


def main() -> None:
    update_live_harness()
    update_runtime_contract_tests()
    update_frontend_static_contracts()
    harden_activity_factory()
    update_docs()
    harden_ci_exact_head()
    add_architecture_boundary_test()
    verify()


if __name__ == "__main__":
    main()
