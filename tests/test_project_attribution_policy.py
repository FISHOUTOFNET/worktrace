"""Unit tests for the centralized project attribution policy module.

These tests verify the source classification contract and the
``resolve_project_attribution`` / ``official_project_fields`` /
``candidate_project_fields`` helpers without touching the database.
The policy module is the SINGLE source of truth for interpreting
``activity_project_assignment.source`` — Timeline / Statistics /
Export / Live Display all defer to it.
"""

from __future__ import annotations

import pytest

from worktrace.constants import UNCATEGORIZED_PROJECT
from worktrace.services.project_attribution_policy import (
    CANDIDATE_PROJECT_SOURCES,
    DERIVED_INTERNAL_PROJECT_SOURCES,
    NON_PROJECT_SOURCES,
    OFFICIAL_PROJECT_SOURCES,
    candidate_project_fields,
    is_candidate_project_source,
    is_derived_internal_project_source,
    is_official_project_source,
    official_project_fields,
    resolve_project_attribution,
)

UNCATEGORIZED_ID = 999


# --- Source classification sets ---


def test_official_sources_are_manual_keyword_folder():
    assert OFFICIAL_PROJECT_SOURCES == frozenset({"manual", "keyword_rule", "folder_rule"})


def test_candidate_sources_are_suggested_only():
    assert CANDIDATE_PROJECT_SOURCES == frozenset({"suggested_project_name"})


def test_derived_internal_sources_include_all_context_types():
    assert DERIVED_INTERNAL_PROJECT_SOURCES == frozenset(
        {
            "anchor_context",
            "same_project_context",
            "clipboard_transition_context",
            "midnight_anchor",
        }
    )


def test_non_project_sources_are_uncategorized_only():
    assert NON_PROJECT_SOURCES == frozenset({"uncategorized"})


def test_source_sets_are_disjoint():
    all_sources = OFFICIAL_PROJECT_SOURCES | CANDIDATE_PROJECT_SOURCES | DERIVED_INTERNAL_PROJECT_SOURCES | NON_PROJECT_SOURCES
    total = (
        len(OFFICIAL_PROJECT_SOURCES)
        + len(CANDIDATE_PROJECT_SOURCES)
        + len(DERIVED_INTERNAL_PROJECT_SOURCES)
        + len(NON_PROJECT_SOURCES)
    )
    assert len(all_sources) == total, "source sets must be disjoint"


# --- is_official_project_source ---


@pytest.mark.parametrize("source", ["manual", "keyword_rule", "folder_rule"])
def test_is_official_project_source_true_for_official(source):
    assert is_official_project_source(source) is True


@pytest.mark.parametrize(
    "source",
    [
        "suggested_project_name",
        "anchor_context",
        "same_project_context",
        "clipboard_transition_context",
        "midnight_anchor",
        "uncategorized",
        "",
        None,
    ],
)
def test_is_official_project_source_false_for_non_official(source):
    assert is_official_project_source(source) is False


def test_is_official_project_source_strips_whitespace():
    assert is_official_project_source("  manual  ") is True
    assert is_official_project_source("  suggested_project_name  ") is False


def test_is_official_project_source_ignores_is_manual_flag():
    """The is_manual flag is accepted but the source string is authoritative."""
    assert is_official_project_source("manual", is_manual=True) is True
    assert is_official_project_source("suggested_project_name", is_manual=True) is False


# --- is_candidate_project_source ---


def test_is_candidate_project_source_true_for_suggested():
    assert is_candidate_project_source("suggested_project_name") is True


@pytest.mark.parametrize(
    "source",
    ["manual", "keyword_rule", "folder_rule", "anchor_context", "uncategorized", "", None],
)
def test_is_candidate_project_source_false_for_non_candidate(source):
    assert is_candidate_project_source(source) is False


# --- is_derived_internal_project_source ---


@pytest.mark.parametrize(
    "source",
    ["anchor_context", "same_project_context", "clipboard_transition_context", "midnight_anchor"],
)
def test_is_derived_internal_project_source_true_for_context(source):
    assert is_derived_internal_project_source(source) is True


@pytest.mark.parametrize(
    "source",
    ["manual", "keyword_rule", "folder_rule", "suggested_project_name", "uncategorized", "", None],
)
def test_is_derived_internal_project_source_false_for_non_derived(source):
    assert is_derived_internal_project_source(source) is False


# --- resolve_project_attribution ---


def _row(source, project_id=1, project_name="ProjectA", description="desc", suggested=""):
    return {
        "assignment_source": source,
        "effective_project_id": project_id,
        "effective_project_name": project_name,
        "effective_project_description": description,
        "suggested_project_name": suggested,
    }


def test_resolve_official_source():
    row = _row("manual", project_id=10, project_name="MyProject")
    result = resolve_project_attribution(row, UNCATEGORIZED_ID)
    assert result["attribution_kind"] == "official"
    assert result["is_official_project"] is True
    assert result["official_project_id"] == 10
    assert result["official_project_name"] == "MyProject"
    assert result["official_project_key"] == "project:10"
    assert result["candidate_project_name"] == ""
    assert result["derived_project_name"] == ""


def test_resolve_candidate_source():
    row = _row(
        "suggested_project_name",
        project_id=UNCATEGORIZED_ID,
        project_name=UNCATEGORIZED_PROJECT,
        suggested="SuggestedClient",
    )
    result = resolve_project_attribution(row, UNCATEGORIZED_ID)
    assert result["attribution_kind"] == "candidate"
    assert result["is_official_project"] is False
    assert result["official_project_id"] == UNCATEGORIZED_ID
    assert result["official_project_name"] == UNCATEGORIZED_PROJECT
    assert result["official_project_key"] == f"uncategorized:{UNCATEGORIZED_ID}"
    assert result["candidate_project_name"] == "SuggestedClient"
    assert result["derived_project_name"] == ""


def test_resolve_derived_source():
    row = _row("anchor_context", project_id=10, project_name="InternalCarry")
    result = resolve_project_attribution(row, UNCATEGORIZED_ID)
    assert result["attribution_kind"] == "derived"
    assert result["is_official_project"] is False
    assert result["official_project_id"] == UNCATEGORIZED_ID
    assert result["official_project_name"] == UNCATEGORIZED_PROJECT
    assert result["official_project_key"] == f"uncategorized:{UNCATEGORIZED_ID}"
    assert result["candidate_project_name"] == ""
    assert result["derived_project_name"] == "InternalCarry"


def test_resolve_midnight_anchor_is_derived_not_official():
    """midnight_anchor is a context-direct anchor but NOT official."""
    row = _row("midnight_anchor", project_id=10, project_name="CrossMidnight")
    result = resolve_project_attribution(row, UNCATEGORIZED_ID)
    assert result["attribution_kind"] == "derived"
    assert result["is_official_project"] is False
    assert result["derived_project_name"] == "CrossMidnight"


def test_resolve_uncategorized_source():
    row = _row("uncategorized", project_id=UNCATEGORIZED_ID, project_name=UNCATEGORIZED_PROJECT)
    result = resolve_project_attribution(row, UNCATEGORIZED_ID)
    assert result["attribution_kind"] == "none"
    assert result["is_official_project"] is False
    assert result["official_project_id"] == UNCATEGORIZED_ID
    assert result["official_project_name"] == UNCATEGORIZED_PROJECT
    assert result["candidate_project_name"] == ""
    assert result["derived_project_name"] == ""


def test_resolve_no_source_treated_as_none():
    row = _row("", project_id=UNCATEGORIZED_ID, project_name="")
    result = resolve_project_attribution(row, UNCATEGORIZED_ID)
    assert result["attribution_kind"] == "none"
    assert result["is_official_project"] is False


def test_resolve_preserves_effective_project_fields():
    """Internal effective project id/name are preserved even for non-official."""
    row = _row("anchor_context", project_id=42, project_name="InternalP")
    result = resolve_project_attribution(row, UNCATEGORIZED_ID)
    assert result["effective_project_id"] == 42
    assert result["effective_project_name"] == "InternalP"


def test_resolve_official_with_uncategorized_project_id_falls_back():
    """An official source whose effective_project_id IS the uncategorized id
    is treated as not concrete: is_official_project is False because the
    resolved project IS the uncategorized project (no real classification)."""
    row = _row("manual", project_id=UNCATEGORIZED_ID, project_name=UNCATEGORIZED_PROJECT)
    result = resolve_project_attribution(row, UNCATEGORIZED_ID)
    assert result["attribution_kind"] == "official"
    assert result["is_official_project"] is False
    assert result["official_project_id"] == UNCATEGORIZED_ID
    assert result["official_project_name"] == UNCATEGORIZED_PROJECT


# --- official_project_fields ---


def test_official_project_fields_for_official_source():
    row = _row("manual", project_id=10, project_name="MyProject", description="Desc")
    fields = official_project_fields(row, UNCATEGORIZED_ID)
    assert fields["display_project_id"] == 10
    assert fields["display_project_name"] == "MyProject"
    assert fields["display_project_description"] == "Desc"
    assert fields["display_project_key"] == "project:10"
    assert fields["project_attribution_kind"] == "official"
    assert fields["is_official_project"] is True
    assert fields["is_classified"] is True
    assert fields["is_uncategorized"] is False
    assert fields["is_suggested_project"] is False


def test_official_project_fields_for_candidate_source():
    row = _row("suggested_project_name", project_id=UNCATEGORIZED_ID, suggested="Suggested")
    fields = official_project_fields(row, UNCATEGORIZED_ID)
    assert fields["display_project_name"] == UNCATEGORIZED_PROJECT
    assert fields["display_project_key"] == f"uncategorized:{UNCATEGORIZED_ID}"
    assert fields["project_attribution_kind"] == "candidate"
    assert fields["is_official_project"] is False
    assert fields["is_classified"] is False
    assert fields["is_uncategorized"] is True
    assert fields["candidate_project_name"] == "Suggested"
    assert fields["derived_project_name"] == ""


def test_official_project_fields_for_derived_source():
    row = _row("anchor_context", project_id=10, project_name="InternalCarry")
    fields = official_project_fields(row, UNCATEGORIZED_ID)
    assert fields["display_project_name"] == UNCATEGORIZED_PROJECT
    assert fields["display_project_key"] == f"uncategorized:{UNCATEGORIZED_ID}"
    assert fields["project_attribution_kind"] == "derived"
    assert fields["is_official_project"] is False
    assert fields["is_classified"] is False
    assert fields["is_uncategorized"] is True
    assert fields["candidate_project_name"] == ""
    assert fields["derived_project_name"] == "InternalCarry"


def test_official_project_fields_for_uncategorized_source():
    row = _row("uncategorized", project_id=UNCATEGORIZED_ID, project_name=UNCATEGORIZED_PROJECT)
    fields = official_project_fields(row, UNCATEGORIZED_ID)
    assert fields["display_project_name"] == UNCATEGORIZED_PROJECT
    assert fields["project_attribution_kind"] == "none"
    assert fields["is_official_project"] is False
    assert fields["is_classified"] is False
    assert fields["is_uncategorized"] is True


# --- candidate_project_fields ---


def test_candidate_project_fields_for_candidate_source():
    row = _row("suggested_project_name", project_id=UNCATEGORIZED_ID, suggested="Suggested")
    fields = candidate_project_fields(row, UNCATEGORIZED_ID)
    assert fields["name"] == "Suggested"
    assert fields["source"] == "suggested_project_name"
    assert fields["is_suggested_project"] is True
    assert fields["is_uncategorized"] is False


def test_candidate_project_fields_for_official_source():
    row = _row("manual", project_id=10, project_name="MyProject", description="Desc")
    fields = candidate_project_fields(row, UNCATEGORIZED_ID)
    assert fields["name"] == "MyProject"
    assert fields["source"] == "manual"
    assert fields["is_suggested_project"] is False
    assert fields["is_uncategorized"] is False


def test_candidate_project_fields_for_uncategorized_source():
    row = _row("uncategorized", project_id=UNCATEGORIZED_ID, project_name=UNCATEGORIZED_PROJECT)
    fields = candidate_project_fields(row, UNCATEGORIZED_ID)
    assert fields["name"] == ""
    assert fields["is_uncategorized"] is True
    assert fields["is_suggested_project"] is False
