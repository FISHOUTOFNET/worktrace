from worktrace.platforms.windows_adapter import _is_valid_com_path, _match_open_file_path, _office_candidates


def test_office_com_path_is_discarded_when_title_is_unrelated():
    assert not _is_valid_com_path("D:\\CaseA\\Spec.docx", "Budget.xlsx - Excel")


def test_office_com_path_is_accepted_when_title_matches_file_name():
    assert _is_valid_com_path("D:\\CaseA\\Spec.docx", "Spec.docx - Word")


def test_wps_candidates_include_kingsoft_prog_ids():
    candidates = _office_candidates("wps.exe")
    assert ("KWps.Application", "ActiveDocument.FullName") in candidates
    assert ("KET.Application", "ActiveWorkbook.FullName") in candidates
    assert ("KWPP.Application", "ActivePresentation.FullName") in candidates


def test_open_file_match_returns_unique_exact_file_name():
    assert _match_open_file_path(
        "quantile_export_20260612_2.xlsx",
        [
            "C:\\PycharmProjects\\Finance\\notes.txt",
            "C:\\PycharmProjects\\Finance\\quantile_export_20260612_2.xlsx",
        ],
    ) == "C:\\PycharmProjects\\Finance\\quantile_export_20260612_2.xlsx"


def test_open_file_match_ignores_ambiguous_matches():
    assert _match_open_file_path(
        "quantile_export_20260612_2.xlsx",
        [
            "C:\\PycharmProjects\\Finance\\quantile_export_20260612_2.xlsx",
            "D:\\Downloads\\quantile_export_20260612_2.xlsx",
        ],
    ) is None
