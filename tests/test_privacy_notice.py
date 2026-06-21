from worktrace.constants import PRIVACY_NOTICE_TEXT
from worktrace.platforms.base import ActiveWindow


def test_active_window_supports_file_path_hint():
    window = ActiveWindow("Word", "winword.exe", "Spec.docx - Word", "D:\\CaseA\\Spec.docx")
    assert window.file_path_hint == "D:\\CaseA\\Spec.docx"


def test_privacy_notice_mentions_local_file_paths_and_exclusion_matching():
    assert "完整本地路径" in PRIVACY_NOTICE_TEXT
    assert "本地文件路径" in PRIVACY_NOTICE_TEXT
    assert "排除规则支持文件夹和关键词" in PRIVACY_NOTICE_TEXT
    assert "关键词会同时匹配应用名称、进程名称、窗口标题和本地文件路径" in PRIVACY_NOTICE_TEXT
