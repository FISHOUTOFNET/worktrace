from __future__ import annotations

import pytest

from worktrace.services import folder_rule_matching_policy as policy

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def _rule(
    rule_id: int,
    folder: str,
    project_id: int,
    *,
    recursive: bool = True,
) -> dict:
    return {
        "id": rule_id,
        "folder_rule_id": rule_id,
        "folder_path": folder,
        "normalized_folder_key": folder.casefold().rstrip("\\/"),
        "project_id": project_id,
        "recursive": int(recursive),
    }


def test_automatic_matching_prefers_the_most_specific_folder() -> None:
    parent = _rule(1, "D:\\Client", 10)
    child = _rule(2, "D:\\Client\\Matter", 20)

    selected = policy.select_automatic_rule(
        "D:\\Client\\Matter\\brief.docx",
        [parent, child],
    )

    assert selected["id"] == child["id"]


def test_non_recursive_rule_matches_only_direct_children() -> None:
    rule = _rule(1, "D:\\Client", 10, recursive=False)

    assert policy.target_matches_rule("D:\\Client\\brief.docx", rule) is True
    assert policy.target_matches_rule(
        "D:\\Client\\Matter\\brief.docx",
        rule,
    ) is False


def test_indexed_automatic_matching_refuses_cross_project_ambiguity() -> None:
    first = {
        **_rule(1, "D:\\Alpha", 10),
        "file_path": "D:\\Alpha\\brief.docx",
        "normalized_path_key": "d:\\alpha\\brief.docx",
    }
    second = {
        **_rule(2, "D:\\Beta", 20),
        "file_path": "D:\\Beta\\brief.docx",
        "normalized_path_key": "d:\\beta\\brief.docx",
    }

    assert policy.select_automatic_indexed_rule([first, second]) is None


def test_indexed_same_name_in_one_project_keeps_automatic_result() -> None:
    first = {
        **_rule(1, "D:\\Alpha", 10),
        "file_path": "D:\\Alpha\\brief.docx",
        "normalized_path_key": "d:\\alpha\\brief.docx",
    }
    second = {
        **_rule(2, "D:\\Beta", 10),
        "file_path": "D:\\Beta\\brief.docx",
        "normalized_path_key": "d:\\beta\\brief.docx",
    }

    selected = policy.select_automatic_indexed_rule([first, second])

    assert selected is not None
    assert selected["project_id"] == 10


def test_explicit_history_rule_may_select_any_actual_candidate() -> None:
    candidates = [
        {
            **_rule(1, "D:\\Client", 10),
            "file_path": "D:\\Client\\Matter\\brief.docx",
        },
        {
            **_rule(2, "D:\\Client\\Matter", 20),
            "file_path": "D:\\Client\\Matter\\brief.docx",
        },
    ]

    assert policy.select_automatic_indexed_rule(candidates)["folder_rule_id"] == 2
    assert policy.rule_is_candidate(1, candidates) is True
    assert policy.rule_is_candidate(2, candidates) is True
    assert policy.rule_is_candidate(999, candidates) is False
