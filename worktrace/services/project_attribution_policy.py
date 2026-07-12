"""Project attribution policy — single source of truth for
``activity_project_assignment.source``.

Separates internal effective attribution (system inference, context
inheritance, suggested candidates) from official visible attribution
(user-confirmed project facts). Official sources are the ONLY sources
that may appear as direct user/rule attribution.

Official: ``manual`` / ``keyword_rule`` / ``folder_rule``.
Candidate: ``suggested_project_name``.
Derived internal: ``anchor_context`` / ``same_project_context`` /
``clipboard_transition_context`` / ``midnight_anchor``.
Non-project: ``uncategorized``.

Report-visible attribution is a separate reporting/history contract.
Context-derived sources can be visible in reports when they carry a
concrete normal project, but they are never official direct attribution.

This is the ONLY module that maps source strings to UI attribution
semantics. Timeline / Statistics / Export / Live Display MUST defer to
``official_project_fields`` / ``report_project_fields`` /
``candidate_project_fields``.
"""

from __future__ import annotations

from typing import Any

from ..constants import UNCATEGORIZED_PROJECT

# --- Source classification ---

OFFICIAL_PROJECT_SOURCES = frozenset({"manual", "keyword_rule", "folder_rule"})
CANDIDATE_PROJECT_SOURCES = frozenset({"suggested_project_name"})
REPORT_VISIBLE_CONTEXT_PROJECT_SOURCES = frozenset(
    {
        "same_project_context",
        "anchor_context",
        "clipboard_transition_context",
        "midnight_anchor",
    }
)
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


def is_report_visible_project_source(source: str | None) -> bool:
    """Return True when ``source`` can surface in report/history project fields."""
    if not source:
        return False
    cleaned = str(source).strip()
    return cleaned in OFFICIAL_PROJECT_SOURCES or cleaned in REPORT_VISIBLE_CONTEXT_PROJECT_SOURCES


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
    effective_project_is_deleted = bool(int(row.get("effective_project_is_deleted") or 0))
    effective_project_is_archived = bool(int(row.get("effective_project_is_archived") or 0))
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
        and not effective_project_is_deleted
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
            and not effective_project_is_deleted
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
        "effective_project_is_deleted": effective_project_is_deleted,
        "effective_project_is_archived": effective_project_is_archived,
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


_REPORT_ATTRIBUTION_KIND_BY_SOURCE = {
    "manual": "official_direct",
    "keyword_rule": "official_direct",
    "folder_rule": "official_direct",
    "same_project_context": "report_context_same_project",
    "anchor_context": "report_context_short_gap",
    "clipboard_transition_context": "report_context_clipboard",
    "midnight_anchor": "report_context_continuation",
    "suggested_project_name": "candidate",
}


def report_project_fields(row: dict, uncategorized_id: int) -> dict:
    """Return report-visible project fields without changing official semantics."""
    attribution = resolve_project_attribution(row, uncategorized_id)
    source = attribution["source"]
    kind = _REPORT_ATTRIBUTION_KIND_BY_SOURCE.get(source, "none")
    effective_project_id = int(attribution["effective_project_id"] or uncategorized_id)
    effective_project_name = str(attribution["effective_project_name"] or "").strip()
    effective_project_is_deleted = bool(attribution["effective_project_is_deleted"])
    is_report_project = (
        is_report_visible_project_source(source)
        and effective_project_id > 0
        and effective_project_id != int(uncategorized_id)
        and bool(effective_project_name)
    )
    if is_report_project and effective_project_is_deleted:
        report_id = effective_project_id
        report_name = ""
        report_desc = ""
        report_key = f"deleted_project:{report_id}"
    elif is_report_project:
        report_id = effective_project_id
        report_name = effective_project_name
        report_desc = attribution["effective_project_description"]
        report_key = f"project:{report_id}"
    else:
        report_id = int(uncategorized_id)
        report_name = UNCATEGORIZED_PROJECT
        report_desc = ""
        report_key = f"uncategorized:{uncategorized_id}"
    return {
        "report_project_id": report_id,
        "report_project_name": report_name,
        "report_project_description": report_desc,
        "report_project_key": report_key,
        "report_project_is_deleted": effective_project_is_deleted and is_report_project,
        "report_project_is_archived": bool(attribution["effective_project_is_archived"]),
        "report_attribution_kind": kind,
        "is_report_project": is_report_project,
        "is_report_classified": is_report_project,
        "is_report_uncategorized": not is_report_project,
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
    "REPORT_VISIBLE_CONTEXT_PROJECT_SOURCES",
    "candidate_project_fields",
    "is_candidate_project_source",
    "is_derived_internal_project_source",
    "is_official_project_source",
    "is_report_visible_project_source",
    "official_project_fields",
    "report_project_fields",
    "resolve_project_attribution",
]
