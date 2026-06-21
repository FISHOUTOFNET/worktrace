from worktrace.activity_identity import infer_activity_identity
from worktrace.services import activity_service


def test_anchor_file_activities_are_identified_from_titles(temp_db):
    word = infer_activity_identity("Word", "winword.exe", "合同.docx - Word")
    pdf = infer_activity_identity("Adobe Acrobat", "acrobat.exe", "产品实际结构.pdf")
    excel = infer_activity_identity("Excel", "excel.exe", "费用表.xlsx - Excel")
    ppt = infer_activity_identity("PowerPoint", "powerpnt.exe", "答辩材料.pptx")

    assert all(item.is_anchor_file for item in [word, pdf, excel, ppt])
    assert word.identity_key == "file:合同.docx"


def test_activity_identity_prefers_file_path_hint(temp_db):
    identity = infer_activity_identity(
        "Word",
        "winword.exe",
        "另一个.docx - Word",
        "D:\\CaseA\\Spec.docx",
    )

    assert identity.identity_key == "file_path:d:\\casea\\spec.docx"
    assert identity.display_name == "Spec.docx"
    assert identity.full_path == "D:\\CaseA\\Spec.docx"
    assert identity.parent_dir == "D:\\CaseA"
    assert identity.file_stem == "Spec"


def test_activity_rows_include_derived_file_identity(temp_db):
    aid = activity_service.create_activity(
        "Word",
        "winword.exe",
        "D:\\CaseA\\合同.docx - Word",
        start_time="2026-06-18 09:00:00",
    )

    activity = activity_service.get_activity(aid)

    assert activity["is_anchor_file"] is True
    assert activity["activity_identity_key"] == "file_path:d:\\casea\\合同.docx"
    assert activity["activity_display_name"] == "合同.docx"
    assert activity["anchor_full_path"] == "D:\\CaseA\\合同.docx"
    assert activity["anchor_parent_dir"] == "D:\\CaseA"
    assert activity["anchor_file_stem"] == "合同"


def test_file_name_fallback_still_works_without_full_path(temp_db):
    identity = infer_activity_identity("Word", "winword.exe", "合同.docx - Word")

    assert identity.identity_key == "file:合同.docx"
    assert identity.full_path is None
    assert identity.file_stem == "合同"


def test_auxiliary_apps_keep_own_activity_identity_and_display_name(temp_db):
    keys = {
        infer_activity_identity("Chrome", "chrome.exe", "A").identity_key,
        infer_activity_identity("Microsoft Edge", "msedge.exe", "B").identity_key,
        infer_activity_identity("Firefox", "firefox.exe", "C").identity_key,
    }
    identity = infer_activity_identity("Edge", "msedge.exe", "Search")

    assert len(keys) == 3
    assert all(key.startswith("app:") for key in keys)
    assert identity.display_name == "Edge"
    assert identity.is_anchor_file is False


def test_communication_apps_are_general_auxiliary_activities(temp_db):
    wechat = infer_activity_identity("微信", "WeChat.exe", "聊天")
    dingtalk = infer_activity_identity("钉钉", "DingTalk.exe", "项目群")

    assert wechat.display_name == "微信"
    assert dingtalk.display_name == "钉钉"
    assert wechat.is_anchor_file is False
    assert dingtalk.is_anchor_file is False
    assert wechat.identity_key != dingtalk.identity_key
