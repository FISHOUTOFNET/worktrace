from __future__ import annotations

import pytest

from worktrace.integrations.fd_work.case_identity import (
    case_label_hash,
    case_search_query,
    extract_case_number,
)


pytestmark = [
    pytest.mark.unit,
    pytest.mark.contract,
    pytest.mark.parallel_safe,
]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("#26IP0165 IPDD_Miragene", "26IP0165"),
        ("26IP0165 IPDD_Miragene", "26IP0165"),
        ("#26IP0165", "26IP0165"),
        ("26IP0165", "26IP0165"),
        ("  #26IP0165 IPDD_Miragene  ", "26IP0165"),
        ("\u3000#26ip0165\u00a0IPDD_Miragene\u202f", "26IP0165"),
        ("#21ip0201 Matter", "21IP0201"),
    ],
)
def test_extract_case_number_from_supported_fd_work_label(label, expected):
    assert extract_case_number(label) == expected


@pytest.mark.parametrize(
    "label",
    [
        "CASE A",
        "Matter #26IP0165",
        "#26IP0165_suffix",
        "##26IP0165 Matter",
        "26I0165 Matter",
        "",
        " \u3000 ",
    ],
)
def test_extract_case_number_rejects_non_prefix_or_non_fd_work_format(label):
    assert extract_case_number(label) == ""


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("#26IP0165 IPDD_Miragene", "26IP0165"),
        ("CASE A", "CASE A"),
        (" Matter #26IP0165 ", "Matter #26IP0165"),
        ("\u3000CASE\u00a0A\u202f", "CASE A"),
        ("", ""),
    ],
)
def test_case_search_query_uses_canonical_number_or_normalized_label_fallback(
    label,
    expected,
):
    assert case_search_query(label) == expected


def test_search_query_never_replaces_full_label_binding_identity():
    label = "#26IP0165 IPDD_Miragene"

    assert case_search_query(label) == "26IP0165"
    assert case_label_hash(label) != case_label_hash(case_search_query(label))
