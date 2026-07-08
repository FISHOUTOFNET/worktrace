from pathlib import Path

from openpyxl import load_workbook

from worktrace.services import activity_service, export_service
from worktrace.services.settings_service import (
    get_bool_setting,
    get_setting,
    set_setting,
)
import pytest

pytestmark = [pytest.mark.db, pytest.mark.integration]


def test_excel_export_file_creation(temp_db, tmp_path):
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    path = export_service.export_excel("2026-06-18", "2026-06-18", str(tmp_path / "out.xlsx"))
    assert Path(path).exists()
    wb = load_workbook(path)
    assert "Summary" in wb.sheetnames
    assert "Sessions" in wb.sheetnames
    assert "Activity Logs" not in wb.sheetnames
    headers = [cell.value for cell in wb["Sessions"][1]]
    assert headers == [
        "日期",
        "开始时间",
        "结束时间",
        "时长",
        "项目",
        "状态",
        "备注",
        "修正时长",
        "是否已修正",
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
    ws = load_workbook(xlsx_path)["Sessions"]
    headers = [cell.value for cell in ws[1]]
    assert "资源名称" not in headers
    assert "路径" not in headers


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




def _seed_business_data() -> int:
    """Insert a small amount of business data so a clear-all has something
    to drop, and the post-clear state can be asserted as empty."""
    aid = activity_service.create_activity(
        "Word", "word.exe", "Doc", start_time="2026-06-18 09:00:00"
    )
    activity_service.close_activity(aid, "2026-06-18 09:30:00")
    return aid


def test_clear_all_confirm_false_does_not_reset_db(temp_db) -> None:
    aid = _seed_business_data()
    try:
        export_service.clear_all_local_data(confirm=False)
    except ValueError:
        pass
    else:
        raise AssertionError("clear_all_local_data(confirm=False) must raise")
    from worktrace.services import activity_service as act_svc
    activities = act_svc.get_activities_by_range(
        "2026-06-18", "2026-06-18"
    )
    assert any(a["id"] == aid for a in activities), (
        "clear_all_local_data(confirm=False) must not reset the DB"
    )


def test_clear_all_success_sets_pause_guard_and_clears_after(temp_db) -> None:
    _seed_business_data()
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    set_setting("current_activity_snapshot", '{"app":"Word"}')
    set_setting("pending_short_seconds", "12")
    set_setting("secure_import_in_progress", "false")

    export_service.clear_all_local_data(confirm=True)

    assert get_bool_setting("secure_import_in_progress", False) is False
    assert get_bool_setting("user_paused", False) is True
    assert get_setting("collector_status", "") == "paused"
    assert (get_setting("current_activity_snapshot", "") or "") == ""
    assert get_setting("pending_short_seconds", "") == "0"
    from worktrace.services import activity_service as act_svc
    activities = act_svc.get_activities_by_range(
        "2026-06-18", "2026-06-18"
    )
    assert activities == [], "clear-all must drop all business data"


def test_clear_all_success_re_seeds_default_settings(temp_db) -> None:
    _seed_business_data()
    export_service.clear_all_local_data(confirm=True)
    from worktrace.db import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM project WHERE created_by = 'system'"
        ).fetchall()
    names = {r[0] for r in rows}
    assert names, "clear-all must re-seed system default projects"


def test_clear_all_rejects_when_secure_import_in_progress(temp_db) -> None:
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
    assert get_bool_setting("secure_import_in_progress", False) is True
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
    # Guard must clear secure_import_in_progress and best-effort restore
    # prior state on failure; exception propagates for stable API message.
    _seed_business_data()
    set_setting("user_paused", "false")
    set_setting("collector_status", "running")
    set_setting("current_activity_snapshot", '{"app":"Word"}')
    set_setting("pending_short_seconds", "12")
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
    assert get_bool_setting("user_paused", False) is False
    assert get_setting("collector_status", "") == "running"
    assert (get_setting("current_activity_snapshot", "") or "") == '{"app":"Word"}'
    assert get_setting("pending_short_seconds", "") == "0"


def test_clear_all_guard_clears_runtime_pending_on_boundary(temp_db) -> None:
    set_setting("pending_short_seconds", "12")
    set_setting("current_activity_snapshot", '{"status":"normal"}')
    set_setting("secure_import_in_progress", "false")

    with export_service._destructive_reset_guard():
        assert get_setting("pending_short_seconds", "") == "0"
        assert get_setting("current_activity_snapshot", "") == ""


def test_clear_all_success_invalidates_context_recompute_cache(temp_db) -> None:
    _seed_business_data()
    export_service.clear_all_local_data(confirm=True)
    from worktrace.services import activity_service as act_svc
    activities = act_svc.get_activities_by_range(
        "2026-06-18", "2026-06-18"
    )
    assert activities == []


def test_clear_all_guard_enter_and_exit_set_setting_sequence(
    temp_db, monkeypatch
) -> None:
    calls: list[tuple[str, str]] = []

    real_set_setting = set_setting

    def _spy_set_setting(key: str, value: str) -> None:
        calls.append((key, value))
        real_set_setting(key, value)

    monkeypatch.setattr(
        "worktrace.services.settings_service.set_setting", _spy_set_setting
    )

    export_service.clear_all_local_data(confirm=True)

    enter_keys = [(k, v) for (k, v) in calls if k == "secure_import_in_progress"]
    assert ("secure_import_in_progress", "true") in enter_keys, (
        "guard enter must set secure_import_in_progress=true"
    )
    assert enter_keys[-1] == ("secure_import_in_progress", "false"), (
        "guard success exit must set secure_import_in_progress=false; "
        f"got {enter_keys[-1]}"
    )
    user_paused_calls = [(k, v) for (k, v) in calls if k == "user_paused"]
    assert ("user_paused", "true") in user_paused_calls, (
        "guard enter must set user_paused=true"
    )
    assert user_paused_calls[-1] == ("user_paused", "true"), (
        "guard success exit must leave user_paused=true; "
        f"got {user_paused_calls[-1]}"
    )
    status_calls = [(k, v) for (k, v) in calls if k == "collector_status"]
    assert ("collector_status", "paused") in status_calls, (
        "guard enter must set collector_status=paused"
    )
    assert status_calls[-1] == ("collector_status", "paused"), (
        "guard success exit must leave collector_status=paused; "
        f"got {status_calls[-1]}"
    )
