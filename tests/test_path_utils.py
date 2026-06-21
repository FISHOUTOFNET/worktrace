from worktrace.constants import ANCHOR_FILE_EXTENSIONS
from worktrace import activity_identity, path_utils
from worktrace.path_utils import (
    extract_file_path_from_title,
    is_path_under_folder,
    looks_like_anchor_file_path,
    normalize_folder_key,
    split_file_path,
)


def test_anchor_extensions_are_shared():
    assert activity_identity.ANCHOR_FILE_EXTENSIONS is ANCHOR_FILE_EXTENSIONS
    assert path_utils.ANCHOR_FILE_EXTENSIONS is ANCHOR_FILE_EXTENSIONS


def test_normalize_folder_key_handles_case_slashes_and_trailing_separator():
    assert normalize_folder_key("D:/CaseA/客户/") == normalize_folder_key("d:\\casea\\客户")


def test_is_path_under_folder_respects_directory_boundary():
    assert is_path_under_folder("D:\\CaseA\\合同.docx", "D:\\CaseA")
    assert not is_path_under_folder("D:\\CaseABC\\合同.docx", "D:\\CaseA")


def test_non_recursive_only_matches_direct_child_files():
    assert is_path_under_folder("D:\\CaseA\\合同.docx", "D:\\CaseA", recursive=False)
    assert not is_path_under_folder("D:\\CaseA\\Sub\\合同.docx", "D:\\CaseA", recursive=False)


def test_anchor_path_detection_and_splitting():
    assert looks_like_anchor_file_path("C:\\Users\\me\\OneDrive\\客户 A\\方案.PDF")
    assert looks_like_anchor_file_path("\\\\server\\share\\客户 A\\方案.docx")
    assert not looks_like_anchor_file_path("C:\\Users\\me\\image.png")
    assert split_file_path("C:/Users/me/客户 A/方案.PDF") == (
        "C:\\Users\\me\\客户 A\\方案.PDF",
        "C:\\Users\\me\\客户 A",
        "方案",
    )


def test_extract_file_path_from_title_prefers_full_path():
    title = "C:\\Users\\me\\客户 A\\方案.docx - Word"
    assert extract_file_path_from_title(title) == "C:\\Users\\me\\客户 A\\方案.docx"
    assert extract_file_path_from_title("方案.docx - Word") is None
