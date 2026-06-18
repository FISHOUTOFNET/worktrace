from worktrace.platforms.windows_adapter import _is_valid_com_path


def test_office_com_path_is_discarded_when_title_is_unrelated():
    assert not _is_valid_com_path("D:\\CaseA\\Spec.docx", "Budget.xlsx - Excel")


def test_office_com_path_is_accepted_when_title_matches_file_name():
    assert _is_valid_com_path("D:\\CaseA\\Spec.docx", "Spec.docx - Word")
