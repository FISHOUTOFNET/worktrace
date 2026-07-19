import pytest

pytestmark = [pytest.mark.integration, pytest.mark.db]

from tests.support import activity_factory as activity_service
from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.db import get_connection
from worktrace.services import (
    activity_inference_job_service,
    folder_rule_service,
    project_inference_service,
    project_service,
    timeline_service,
)
from worktrace.services.activity_lifecycle_service import close_activity as lifecycle_close_activity


def close_and_consume_inference_for_test(app, process, title, path=None):
    """Persist, close, and explicitly consume one durable inference job."""

    activity_id = activity_service.create_activity(
        app,
        process,
        title,
        file_path_hint=path,
        start_time="2026-06-18 09:00:00",
    )
    activity_service.finalize_created_activity(activity_id)
    lifecycle_close_activity(activity_id, "2026-06-18 09:10:00")
    with get_connection() as conn:
        job = conn.execute(
            "SELECT status FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    assert job is not None
    assert job["status"] == "pending"

    assert activity_inference_job_service.process_pending_inference_jobs(
        project_inference_service.assign_project_for_activity_in_transaction,
        limit=1,
        activity_ids=[activity_id],
    ) == 1
    with get_connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM activity_inference_job WHERE activity_id = ?",
            (activity_id,),
        ).fetchone() is None
    return activity_id


def test_wps_word_file_path_classifies_as_anchor_file_project_and_summary(temp_db):
    aid = close_and_consume_inference_for_test(
        "WPS Writer",
        "wps.exe",
        "合同审查意见.docx - WPS",
        "D:\\ClientA\\合同审查意见.docx",
    )
    activity = activity_service.get_activity(aid)

    assert activity["resource_is_anchor"] is True
    assert activity["activity_display_name"] == "合同审查意见.docx"
    assert activity["resource_path_hint"] == "D:\\ClientA\\合同审查意见.docx"
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
    assert timeline_service.get_project_sessions_by_date("2026-06-18")[0]["project_name"] == UNCATEGORIZED_PROJECT
    assert "wps.exe" not in timeline_service.get_project_sessions_by_date("2026-06-18")[0]["status_summary"]


def test_et_excel_file_path_uses_file_name_in_summary(temp_db):
    aid = close_and_consume_inference_for_test(
        "WPS Spreadsheets",
        "et.exe",
        "项目清单.xlsx - WPS",
        "D:\\ClientA\\项目清单.xlsx",
    )
    activity = activity_service.get_activity(aid)
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
    summary = timeline_service.get_project_sessions_by_date("2026-06-18")[0]["status_summary"]
    assert timeline_service.get_project_sessions_by_date("2026-06-18")[0]["project_name"] == UNCATEGORIZED_PROJECT
    assert "项目清单.xlsx" in summary
    assert "et.exe" not in summary


def test_wps_excel_file_path_matches_folder_rule_project(temp_db):
    project = project_service.create_project("Percentile")
    folder_rule_service.create_or_update_folder_rule("C:\\PycharmProjects\\Finance", project)
    aid = close_and_consume_inference_for_test(
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
    aid = close_and_consume_inference_for_test(
        "WPS Presentation",
        "wpp.exe",
        "汇报材料.pptx - WPS 演示",
    )
    activity = activity_service.get_activity(aid)
    assert activity["resource_is_anchor"] is True
    assert activity["activity_display_name"] == "汇报材料.pptx"
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
    summary = timeline_service.get_project_sessions_by_date("2026-06-18")[0]["status_summary"]
    assert timeline_service.get_project_sessions_by_date("2026-06-18")[0]["project_name"] == UNCATEGORIZED_PROJECT
    assert "汇报材料.pptx" in summary
    assert "wpp.exe" not in summary


def test_generic_downloads_folder_does_not_use_file_stem_for_fallback_project(temp_db):
    aid = close_and_consume_inference_for_test(
        "WPS Writer",
        "wps.exe",
        "临时合同.docx - WPS",
        "D:\\Downloads\\临时合同.docx",
    )
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
    aid = close_and_consume_inference_for_test("WPS Office", "wps.exe", "WPS 首页")
    activity = activity_service.get_activity(aid)
    assert activity["resource_is_anchor"] is False
    assert activity["activity_display_name"] == "WPS Office"
    assert activity["project_name"] == UNCATEGORIZED_PROJECT
