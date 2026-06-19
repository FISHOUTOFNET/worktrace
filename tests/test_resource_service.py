from worktrace.resource_patterns import infer_resource_identity
from worktrace.db import get_connection, now_str
from worktrace.services import activity_service, resource_service, timeline_service


def test_anchor_file_resources_are_stable(temp_db):
    word = infer_resource_identity("Word", "winword.exe", "合同.docx - Word")
    pdf = infer_resource_identity("Adobe Acrobat", "acrobat.exe", "产品实际结构.pdf")
    excel = infer_resource_identity("Excel", "excel.exe", "费用表.xlsx - Excel")
    ppt = infer_resource_identity("PowerPoint", "powerpnt.exe", "答辩材料.pptx")
    assert word.resource_role == "anchor"
    assert pdf.resource_role == "anchor"
    assert excel.resource_role == "anchor"
    assert ppt.resource_role == "anchor"
    assert word.canonical_key == "file:合同.docx"


def test_infer_resource_identity_prefers_file_path_hint(temp_db):
    resource = infer_resource_identity(
        "Word",
        "winword.exe",
        "另一个.docx - Word",
        "D:\\CaseA\\Spec.docx",
    )
    assert resource.canonical_key == "file_path:d:\\casea\\spec.docx"
    assert resource.display_name == "Spec.docx"
    assert resource.full_path == "D:\\CaseA\\Spec.docx"
    assert resource.parent_dir == "D:\\CaseA"
    assert resource.file_stem == "Spec"


def test_title_full_path_populates_resource_path_fields(temp_db):
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "D:\\CaseA\\合同.docx - Word",
        start_time="2026-06-18 09:00:00",
    )
    resource = resource_service.ensure_activity_resource(aid)
    assert resource["canonical_key"] == "file_path:d:\\casea\\合同.docx"
    assert resource["full_path"] == "D:\\CaseA\\合同.docx"
    assert resource["parent_dir"] == "D:\\CaseA"
    assert resource["file_stem"] == "合同"


def test_file_name_fallback_still_works_without_full_path(temp_db):
    resource = infer_resource_identity("Word", "winword.exe", "合同.docx - Word")
    assert resource.canonical_key == "file:合同.docx"
    assert resource.full_path is None
    assert resource.file_stem == "合同"


def test_existing_resource_path_is_not_overwritten_by_none(temp_db):
    resource = resource_service.infer_or_create_resource(
        {"app_name": "Edge", "process_name": "msedge.exe", "window_title": "Search"}
    )
    with get_connection() as conn:
        conn.execute(
            "UPDATE resource SET full_path = ?, parent_dir = ?, file_stem = ?, updated_at = ? WHERE id = ?",
            ("D:\\CaseA\\Spec.docx", "D:\\CaseA", "Spec", now_str(), resource["id"]),
        )
    updated = resource_service.infer_or_create_resource(
        {"app_name": "Edge", "process_name": "msedge.exe", "window_title": "Search"}
    )
    assert updated["canonical_key"] == "app:edge-msedge.exe"
    assert updated["full_path"] == "D:\\CaseA\\Spec.docx"


def test_auxiliary_apps_keep_own_resource_identity_and_display_name(temp_db):
    keys = {
        infer_resource_identity("Chrome", "chrome.exe", "A").canonical_key,
        infer_resource_identity("Microsoft Edge", "msedge.exe", "B").canonical_key,
        infer_resource_identity("Firefox", "firefox.exe", "C").canonical_key,
    }
    assert len(keys) == 3
    assert all(key.startswith("app:") for key in keys)
    resource = infer_resource_identity("Edge", "msedge.exe", "Search")
    assert resource.display_name == "Edge"
    assert resource.resource_type == "app"
    assert resource.resource_role == "auxiliary"


def test_communication_apps_are_general_auxiliary_apps(temp_db):
    wechat = infer_resource_identity("微信", "WeChat.exe", "聊天")
    dingtalk = infer_resource_identity("钉钉", "DingTalk.exe", "项目群")
    assert wechat.display_name == "微信"
    assert dingtalk.display_name == "钉钉"
    assert wechat.resource_type == "app"
    assert dingtalk.resource_type == "app"
    assert wechat.canonical_key != dingtalk.canonical_key


def test_can_remember_for_future_depends_on_resource_role(temp_db):
    aid = activity_service.create_activity("Word", "winword.exe", "Spec.docx", start_time="2026-06-18 09:00:00")
    anchor = resource_service.ensure_activity_resource(aid)
    browser_id = activity_service.create_activity("Edge", "msedge.exe", "Search", start_time="2026-06-18 09:10:00")
    browser = resource_service.ensure_activity_resource(browser_id)
    summary = timeline_service.get_session_resource_summary([aid, browser_id])
    by_id = {row["resource_id"]: row for row in summary}
    assert by_id[anchor["id"]]["can_remember_for_future"] is True
    assert by_id[browser["id"]]["can_remember_for_future"] is False
