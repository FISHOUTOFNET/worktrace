from worktrace.resource_patterns import infer_resource_identity
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


def test_browsers_share_one_auxiliary_resource(temp_db):
    keys = {
        infer_resource_identity("Chrome", "chrome.exe", "A").canonical_key,
        infer_resource_identity("Microsoft Edge", "msedge.exe", "B").canonical_key,
        infer_resource_identity("Firefox", "firefox.exe", "C").canonical_key,
    }
    assert keys == {"web:browser"}
    resource = infer_resource_identity("Edge", "msedge.exe", "Search")
    assert resource.display_name == "浏览器 / 检索网页"
    assert resource.resource_role == "auxiliary"


def test_can_remember_for_future_depends_on_resource_role(temp_db):
    aid = activity_service.create_activity("Word", "winword.exe", "Spec.docx", start_time="2026-06-18 09:00:00")
    anchor = resource_service.ensure_activity_resource(aid)
    browser_id = activity_service.create_activity("Edge", "msedge.exe", "Search", start_time="2026-06-18 09:10:00")
    browser = resource_service.ensure_activity_resource(browser_id)
    summary = timeline_service.get_session_resource_summary([aid, browser_id])
    by_id = {row["resource_id"]: row for row in summary}
    assert by_id[anchor["id"]]["can_remember_for_future"] is True
    assert by_id[browser["id"]]["can_remember_for_future"] is False
