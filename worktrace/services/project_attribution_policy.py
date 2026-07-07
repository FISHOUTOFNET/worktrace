"""Project attribution policy — single source of truth for
``activity_project_assignment.source``.

Separates internal effective attribution (system inference, context
inheritance, suggested candidates) from official visible attribution
(user-confirmed project facts). Official sources are the ONLY sources
that may appear in the formal project column, project statistics,
project details, and the exported ``项目`` field.

Official: ``manual`` / ``keyword_rule`` / ``folder_rule``.
Candidate: ``suggested_project_name``.
Derived internal: ``anchor_context`` / ``same_project_context`` /
``clipboard_transition_context`` / ``midnight_anchor``.
Non-project: ``uncategorized``.

This is the ONLY module that maps source strings to UI attribution
semantics. Timeline / Statistics / Export / Live Display MUST defer to
``official_project_fields`` / ``candidate_project_fields``.
"""

from __future__ import annotations

from typing import Any

from ..constants import UNCATEGORIZED_PROJECT

# --- Source classification ---

OFFICIAL_PROJECT_SOURCES = frozenset({"manual", "keyword_rule", "folder_rule"})
CANDIDATE_PROJECT_SOURCES = frozenset({"suggested_project_name"})
DERIVED_INTERNAL_PROJECT_SOURCES = frozenset(
    {
        "anchor_context",
        "same_project_context",
        "clipboard_transition_context",
        "midnight_anchor",
    }
)
NON_PROJECT_SOURCES = frozenset({"uncategorized"})


def is_official_project_source(source: str | None, is_manual: bool = False) -> bool:
    """Return True when ``source`` represents a user-confirmed project attribution.

    Official sources are ``manual`` / ``keyword_rule`` / ``folder_rule``.
    The ``is_manual`` flag is accepted for the required signature but the
    source string is the authoritative check — a row with
    ``source="manual"`` is official regardless of the manual flag.
    """
    if not source:
        return False
    return str(source).strip() in OFFICIAL_PROJECT_SOURCES


def is_candidate_project_source(source: str | None) -> bool:
    """Return True when ``source`` is a suggested (not user-confirmed) candidate."""
    if not source:
        return False
    return str(source).strip() in CANDIDATE_PROJECT_SOURCES


def is_derived_internal_project_source(source: str | None) -> bool:
    """Return True when ``source`` is a context-derived internal attribution.

    Derived sources are used for internal continuity / carry only and
    MUST NOT appear as official project attribution in the UI.
    """
    if not source:
        return False
    return str(source).strip() in DERIVED_INTERNAL_PROJECT_SOURCES


def resolve_project_attribution(row: dict, uncategorized_id: int) -> dict:
    """Resolve full attribution for a report/timeline row.

    ``row`` exposes ``assignment_source``, ``effective_project_id``,
    ``effective_project_name``, ``effective_project_description``,
    ``suggested_project_name``. Missing fields are tolerated.

    Returns ``attribution_kind`` (official/candidate/derived/none),
    ``is_official_project``, official/candidate/derived project fields,
    and preserved ``effective_project_*`` for internal use.
    """
    uncategorized_id = int(uncategorized_id)
    source = str(row.get("assignment_source") or "").strip()
    effective_project_id = int(row.get("effective_project_id") or uncategorized_id)
    effective_project_name = str(row.get("effective_project_name") or "").strip()
    effective_project_description = str(
        row.get("effective_project_description") or ""
    ).strip()
    suggested = str(row.get("suggested_project_name") or "").strip()

    if is_official_project_source(source):
        kind = "official"
    elif is_candidate_project_source(source):
        kind = "candidate"
    elif is_derived_internal_project_source(source):
        kind = "derived"
    else:
        kind = "none"

    is_official = kind == "official"
    concrete = (
        is_official
        and effective_project_id != uncategorized_id
        and effective_project_id > 0
        and bool(effective_project_name)
    )

    if concrete:
        official_id = effective_project_id
        official_name = effective_project_name
        official_desc = effective_project_description
        official_key = f"project:{official_id}"
    else:
        official_id = uncategorized_id
        official_name = UNCATEGORIZED_PROJECT
        official_desc = ""
        official_key = f"uncategorized:{uncategorized_id}"

    candidate_name = suggested if kind == "candidate" else ""
    derived_name = (
        effective_project_name
        if (
            kind == "derived"
            and effective_project_name
            and effective_project_id != uncategorized_id
        )
        else ""
    )

    return {
        "attribution_kind": kind,
        "is_official_project": concrete,
        "official_project_id": official_id,
        "official_project_name": official_name,
        "official_project_description": official_desc,
        "official_project_key": official_key,
        "candidate_project_name": candidate_name,
        "derived_project_name": derived_name,
        "effective_project_id": effective_project_id,
        "effective_project_name": effective_project_name,
        "effective_project_description": effective_project_description,
        "source": source,
    }


def official_project_fields(row: dict, uncategorized_id: int) -> dict:
    """Return the official display-safe project fields for a row.

    Used by Timeline / Statistics / Export / Details to project the
    FORMAL project column. Non-official sources always resolve to
    uncategorized so the formal project column never leaks a suggested /
    context-derived project name.
    """
    attribution = resolve_project_attribution(row, uncategorized_id)
    return {
        "display_project_id": attribution["official_project_id"],
        "display_project_name": attribution["official_project_name"],
        "display_project_description": attribution["official_project_description"],
        "display_project_key": attribution["official_project_key"],
        "project_attribution_kind": attribution["attribution_kind"],
        "is_official_project": attribution["is_official_project"],
        "is_classified": attribution["is_official_project"],
        "is_uncategorized": not attribution["is_official_project"],
        "is_suggested_project": False,
        "candidate_project_name": attribution["candidate_project_name"],
        "derived_project_name": attribution["derived_project_name"],
    }


def candidate_project_fields(row: dict, uncategorized_id: int) -> dict:
    """Return the candidate project label fields for a row.

    Used by live display to expose ``candidate_project`` separately from
    the official display project. The candidate is the suggested name
    when source is candidate, or the effective project when source is
    official. Returns an uncategorized label when no candidate applies.
    """
    attribution = resolve_project_attribution(row, uncategorized_id)
    if attribution["attribution_kind"] == "candidate":
        return {
            "id": None,
            "name": attribution["candidate_project_name"],
            "description": "",
            "source": "suggested_project_name",
            "is_uncategorized": False,
            "is_suggested_project": True,
        }
    if attribution["is_official_project"]:
        return {
            "id": attribution["official_project_id"],
            "name": attribution["official_project_name"],
            "description": attribution["official_project_description"],
            "source": attribution["source"],
            "is_uncategorized": False,
            "is_suggested_project": False,
        }
    return {
        "id": None,
        "name": "",
        "description": "",
        "source": attribution["source"] or "uncategorized",
        "is_uncategorized": True,
        "is_suggested_project": False,
    }


__all__ = [
    "CANDIDATE_PROJECT_SOURCES",
    "DERIVED_INTERNAL_PROJECT_SOURCES",
    "NON_PROJECT_SOURCES",
    "OFFICIAL_PROJECT_SOURCES",
    "candidate_project_fields",
    "is_candidate_project_source",
    "is_derived_internal_project_source",
    "is_official_project_source",
    "official_project_fields",
    "resolve_project_attribution",
]
