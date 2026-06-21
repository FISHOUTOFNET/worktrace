from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.db import get_connection
from worktrace.services import activity_service, folder_rule_service, project_service, timeline_service


def _create_finalized(app, process, title, path=None):
    aid = activity_service.create_activity(
        app,
        process,
        title,
        file_path_hint=path,
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(aid)
    activity_service.close_activity(aid, "2026-06-18 09:10:00")
    return aid


def test_wps_word_file_path_classifies_as_anchor_file_project_and_summary(temp_db):
    aid = _create_finalized("WPS Writer", "wps.exe", "合同审查意见.docx - WPS", "D:\\ClientA\\合同审查意见.docx")
    activity = activity_service.get_activity(aid)

    assert activity["is_anchor_file"] is True
    assert activity["activity_display_name"] == "合同审查意见.docx"
    assert activity["anchor_full_path"] == "D:\\ClientA\\合同审查意见.docx"
    assert activity["anchor_parent_dir"] == "D:\\ClientA"
    assert activity["anchor_file_stem"] == "合同审查意见"
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
    assert timeline_service.get_project_sessions_by_date("2026-06-18")[0]["project_name"] == "ClientA"
    assert "wps.exe" not in timeline_service.get_project_sessions_by_date("2026-06-18")[0]["status_summary"]


def test_et_excel_file_path_uses_file_name_in_summary(temp_db):
    aid = _create_finalized("WPS Spreadsheets", "et.exe", "项目清单.xlsx - WPS", "D:\\ClientA\\项目清单.xlsx")
    activity = activity_service.get_activity(aid)
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
    summary = timeline_service.get_project_sessions_by_date("2026-06-18")[0]["status_summary"]
    assert timeline_service.get_project_sessions_by_date("2026-06-18")[0]["project_name"] == "ClientA"
    assert "项目清单.xlsx" in summary
    assert "et.exe" not in summary


def test_wps_excel_file_path_matches_folder_rule_project(temp_db):
    project = project_service.create_project("Percentile")
    folder_rule_service.create_or_update_folder_rule("C:\\PycharmProjects\\Finance", project)
    aid = _create_finalized(
        "WPS Office",
        "wps.exe",
        "quantile_export_20260612_2.xlsx - WPS Office",
        "C:\\PycharmProjects\\Finance\\quantile_export_20260612_2.xlsx",
    )

    activity = activity_service.get_activity(aid)

    assert activity["project_id"] == project
    assert activity["project_name"] == "Percentile"
    with get_connection() as conn:
        assignment = conn.execute(
            "SELECT source FROM activity_project_assignment WHERE activity_id = ?",
            (aid,),
        ).fetchone()
    assert assignment["source"] == "folder_rule"


def test_wpp_title_file_name_without_path_is_anchor_and_not_process_summary(temp_db):
    aid = _create_finalized("WPS Presentation", "wpp.exe", "汇报材料.pptx - WPS 演示")
    activity = activity_service.get_activity(aid)
    assert activity["is_anchor_file"] is True
    assert activity["activity_display_name"] == "汇报材料.pptx"
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
    summary = timeline_service.get_project_sessions_by_date("2026-06-18")[0]["status_summary"]
    assert timeline_service.get_project_sessions_by_date("2026-06-18")[0]["project_name"] == UNCATEGORIZED_PROJECT
    assert "汇报材料.pptx" in summary
    assert "wpp.exe" not in summary


def test_generic_downloads_folder_does_not_use_file_stem_for_fallback_project(temp_db):
    aid = _create_finalized("WPS Writer", "wps.exe", "临时合同.docx - WPS", "D:\\Downloads\\临时合同.docx")
    activity = activity_service.get_activity(aid)
    session = timeline_service.get_project_sessions_by_date("2026-06-18")[0]
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
    assert session["project_name"] == UNCATEGORIZED_PROJECT
    with get_connection() as conn:
        downloads = conn.execute("SELECT * FROM project WHERE name = 'Downloads'").fetchone()
        file_stem = conn.execute("SELECT * FROM project WHERE name = '临时合同'").fetchone()
    assert downloads is None
    assert file_stem is None


def test_wps_without_file_information_remains_auxiliary_activity_and_uncategorized(temp_db):
    aid = _create_finalized("WPS Office", "wps.exe", "WPS 首页")
    activity = activity_service.get_activity(aid)
    assert activity["is_anchor_file"] is False
    assert activity["activity_display_name"] == "WPS Office"
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
