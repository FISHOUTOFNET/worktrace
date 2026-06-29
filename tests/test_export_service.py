from pathlib import Path

from openpyxl import load_workbook

from worktrace.services import activity_service, export_service
from worktrace.services.settings_service import (
    get_bool_setting,
    get_setting,
    set_setting,
)


def test_excel_export_file_creation(temp_db, tmp_path):
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    path = export_service.export_excel("2026-06-18", "2026-06-18", str(tmp_path / "out.xlsx"))
    assert Path(path).exists()
    wb = load_workbook(path)
    assert "Summary" in wb.sheetnames
    assert "Activity Logs" in wb.sheetnames
    headers = [cell.value for cell in wb["Activity Logs"][1]]
    assert headers == [
        "日期",
        "开始时间",
        "结束时间",
        "时长",
        "状态",
        "资源类型",
        "资源名称",
        "应用",
        "项目",
        "路径",
        "域名",
        "备注",
    ]


def test_exports_prefer_activity_file_name_for_wps_activity(temp_db, tmp_path):
    aid = activity_service.create_activity(
        "WPS Writer",
        "wps.exe",
        "合同审查意见.docx - WPS",
        file_path_hint="D:\\ClientA\\合同审查意见.docx",
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-18 09:30:00")

    xlsx_path = export_service.export_excel("2026-06-18", "2026-06-18", str(tmp_path / "out.xlsx"))
    ws = load_workbook(xlsx_path)["Activity Logs"]
    headers = [cell.value for cell in ws[1]]
    name_col = headers.index("资源名称") + 1
    assert ws.cell(row=2, column=name_col).value == "合同审查意见.docx"


def test_export_all_and_clear_requires_confirmation(temp_db, tmp_path):
    path = export_service.export_all_local_data(str(tmp_path / "all.xlsx"))
    assert Path(path).exists()
    wb = load_workbook(path)
    assert "folder_project_rule" in wb.sheetnames
    assert "folder_rule_index_state" not in wb.sheetnames
    assert "folder_rule_file_index" not in wb.sheetnames
    assert "activity_resource" in wb.sheetnames
    try:
        export_service.clear_all_local_data(confirm=False)
    except ValueError:
        pass
    else:
        raise AssertionError("clear_all_local_data should require confirmation")


# --- Phase 6D: clear-all destructive reset guard -----------------------


def _seed_business_data() -> int:
    """Insert a small amount of business data so a clear-all has something
    to drop, and the post-clear state can be asserted as empty."""
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    return aid


def test_clear_all_confirm_false_does_not_reset_db(temp_db) -> None:
    # confirm=False must reject and must NOT call reset_database. The
    # seeded activity must still exist after the rejected call.
    aid = _seed_business_data()
    try:
        export_service.clear_all_local_data(confirm=False)
    except ValueError:
        pass
    else:
        raise AssertionError("clear_all_local_data(confirm=False) must raise")
    # The activity must still be present (DB was not reset).
    from worktrace.services import activity_service as act_svc
    activities = act_svc.get_activities_by_range(
        "2026-06-18", "2026-06-18"
    )
    assert any(a["id"] == aid for a in activities), (
        "clear_all_local_data(confirm=False) must not reset the DB"
    )


def test_clear_all_success_sets_pause_guard_and_clears_after(temp_db) -> None:
    # On success: secure_import_in_progress must be False, user_paused
    # must be True (left paused for the user to verify), collector_status
    # must be paused, current_activity_snapshot must be empty.
    _seed_business_data()
    # Pre-state: ensure the app is running so we can prove the guard
    # forces it to paused during the reset and leaves it paused after.
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    set_setting("current_activity_snapshot", '{"app":"Word"}')
    set_setting("secure_import_in_progress", "false")

    export_service.clear_all_local_data(confirm=True)

    assert get_bool_setting("secure_import_in_progress", False) is False
    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status", "") == "paused"
    assert (get_setting("current_activity_snapshot", "") or "") == ""
    # The business data must have been cleared.
    from worktrace.services import activity_service as act_svc
    activities = act_svc.get_activities_by_range(
        "2026-06-18", "2026-06-18"
    )
    assert activities == [], "clear-all must drop all business data"


def test_clear_all_success_re_seeds_default_settings(temp_db) -> None:
    # reset_database() calls seed_defaults(); after clear-all the system
    # default project must exist and settings table must be re-seeded.
    _seed_business_data()
    export_service.clear_all_local_data(confirm=True)
    # The system default project is re-seeded by seed_defaults.
    from worktrace.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM project WHERE created_by = 'system'"
        ).fetchall()
    names = {r[0] for r in rows}
    assert names, "clear-all must re-seed system default projects"


def test_clear_all_rejects_when_secure_import_in_progress(temp_db) -> None:
    # If another destructive operation is in progress, clear-all must
    # refuse with ValueError("operation_in_progress") and must NOT touch
    # the DB. The prior activity must remain.
    aid = _seed_business_data()
    set_setting("secure_import_in_progress", "true")
    try:
        export_service.clear_all_local_data(confirm=True)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "clear-all must reject when secure_import_in_progress is true"
        )
    # The flag must still be true (we did not enter the guard).
    assert get_bool_setting("secure_import_in_progress", False) is True
    # The activity must still be present (DB was not reset).
    from worktrace.services import activity_service as act_svc
    activities = act_svc.get_activities_by_range(
        "2026-06-18", "2026-06-18"
    )
    assert any(a["id"] == aid for a in activities), (
        "clear-all must not reset the DB when another destructive op is in progress"
    )


def test_clear_all_failure_restores_prior_state_and_clears_guard(
    temp_db, monkeypatch
) -> None:
    # When reset_database raises, the guard must clear
    # secure_import_in_progress and best-effort restore the prior pause /
    # status / snapshot state. The exception must propagate so the API
    # facade can collapse it to the stable Chinese message.
    _seed_business_data()
    # Pre-state: app was running with a snapshot; the guard should restore
    # these values on failure (not leave them forced to paused).
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    set_setting("current_activity_snapshot", '{"app":"Word"}')
    set_setting("secure_import_in_progress", "false")

    def _boom() -> None:
        raise RuntimeError("reset_database boom")

    monkeypatch.setattr(export_service, "reset_database", _boom)

    try:
        export_service.clear_all_local_data(confirm=True)
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "clear-all must re-raise the reset_database exception"
        )

    # The guard must be cleared so the collector is not permanently blocked.
    assert get_bool_setting("secure_import_in_progress", False) is False
    # Prior pause / status / snapshot state must be restored.
    assert get_bool_setting("user_paused", False) is False
    assert get_setting("collector_status", "") == "running"
    assert (get_setting("current_activity_snapshot", "") or "") == '{"app":"Word"}'


def test_clear_all_success_invalidates_context_recompute_cache(temp_db) -> None:
    # The context recompute cache was previously missing from the
    # clear-all path. After a successful clear-all it must be invalidated
    # so the next Timeline / Statistics load does not see pre-clear data.
    # Seed data, then clear-all and assert the post-clear activity list
    # is empty (the cache invalidation is verified indirectly: without
    # invalidation the context recompute cache would still point at the
    # pre-clear activity row, and the next range query would surface it).
    _seed_business_data()
    export_service.clear_all_local_data(confirm=True)
    # Re-fetch: with no activities, the context service must not return
    # the pre-clear row.
    from worktrace.services import activity_service as act_svc
    activities = act_svc.get_activities_by_range(
        "2026-06-18", "2026-06-18"
    )
    assert activities == []


def test_clear_all_guard_enter_and_exit_set_setting_sequence(
    temp_db, monkeypatch
) -> None:
    # Verify the guard enter / exit set_setting call sequence by
    # intercepting set_setting. On entry: user_paused=true,
    # collector_status=paused, current_activity_snapshot="",
    # secure_import_in_progress=true. On success exit: user_paused=true,
    # collector_status=paused, current_activity_snapshot="",
    # secure_import_in_progress=false.
    calls: list[tuple[str, str]] = []

    real_set_setting = set_setting

    def _spy_set_setting(key: str, value: str) -> None:
        calls.append((key, value))
        real_set_setting(key, value)

    monkeypatch.setattr(
        "worktrace.services.settings_service.set_setting", _spy_set_setting
    )

    export_service.clear_all_local_data(confirm=True)

    # Enter: secure_import_in_progress must have been set to "true" at
    # some point during the call.
    enter_keys = [(k, v) for (k, v) in calls if k == "secure_import_in_progress"]
    assert ("secure_import_in_progress", "true") in enter_keys, (
        "guard enter must set secure_import_in_progress=true"
    )
    # Exit: secure_import_in_progress must end at "false".
    assert enter_keys[-1] == ("secure_import_in_progress", "false"), (
        "guard success exit must set secure_import_in_progress=false; "
        f"got {enter_keys[-1]}"
    )
    # Enter: user_paused must have been set to "true" during the call.
    user_paused_calls = [(k, v) for (k, v) in calls if k == "user_paused"]
    assert ("user_paused", "true") in user_paused_calls, (
        "guard enter must set user_paused=true"
    )
    # Exit: user_paused ends at "true" (left paused after clear-all).
    assert user_paused_calls[-1] == ("user_paused", "true"), (
        "guard success exit must leave user_paused=true; "
        f"got {user_paused_calls[-1]}"
    )
    # Enter: collector_status must have been set to "paused".
    status_calls = [(k, v) for (k, v) in calls if k == "collector_status"]
    assert ("collector_status", "paused") in status_calls, (
        "guard enter must set collector_status=paused"
    )
    # Exit: collector_status ends at "paused".
    assert status_calls[-1] == ("collector_status", "paused"), (
        "guard success exit must leave collector_status=paused; "
        f"got {status_calls[-1]}"
    )
