"""Shared anchor predicates for context_service and timeline_service.

This module centralizes the file-based context-anchor judgment that was
previously duplicated between ``context_service._is_context_anchor`` and
``timeline_service._is_project_anchor``. It also exposes a direct
assignment anchor predicate used by context inference to propagate
project context from high-confidence direct assignments
(``manual`` / ``folder_rule`` / ``keyword_rule`` / ``midnight_anchor``).

The helpers operate on plain ``dict`` rows produced by ``attach_resource``
or by SQL that includes the ``activity_resource`` / ``activity_project_assignment``
columns. They never touch the database directly.

Source semantics (see ``activity_project_assignment.source``):

- ``anchor_context`` — file-type context anchor produced context carry;
- ``same_project_context`` — direct assignment anchor produced context carry;
- ``clipboard_transition_context`` — clipboard transition;
- ``suggested_project_name`` — low-confidence candidate;
- ``uncategorized`` — no project.
"""

from __future__ import annotations

import ntpath

from ..constants import ANCHOR_FILE_EXTENSIONS, STATUS_NORMAL

DIRECT_ASSIGNMENT_SOURCES = frozenset(
    {"manual", "folder_rule", "keyword_rule", "midnight_anchor"}
)

# Sources that represent already-derived context and must NOT chain onward
# as direct assignment anchors (avoids low-confidence propagation).
_CONTEXT_DERIVED_SOURCES = frozenset(
    {
        "anchor_context",
        "same_project_context",
        "clipboard_transition_context",
        "suggested_project_name",
        "uncategorized",
    }
)

_ANCHOR_EXT_SET = frozenset(ext.casefold() for ext in ANCHOR_FILE_EXTENSIONS)


def row_project_id(row: dict) -> int:
    """Return the effective project id for a row.

    Priority: ``assignment_project_id`` -> ``effective_project_id`` ->
    ``project_id`` -> 0.
    """
    for key in ("assignment_project_id", "effective_project_id", "project_id"):
        value = row.get(key)
        if value is not None and value != "":
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


def is_concrete_project(row: dict, uncategorized_id: int) -> bool:
    """True when the row has a project id that is not the uncategorized
    project id."""
    project_id = row_project_id(row)
    if project_id <= 0:
        return False
    return project_id != int(uncategorized_id)


def _split_ext(name: str) -> str:
    _, ext = ntpath.splitext(name)
    return ext


def is_file_context_anchor(row: dict) -> bool:
    """True when the row is a file-type context anchor.

    Conditions:
      - ``status == STATUS_NORMAL``;
      - ``resource_is_anchor`` is truthy;
      - ``resource_kind`` is not ``browser_tab`` / ``email``;
      - the resource display name (or fallback activity display name) has
        an extension in ``ANCHOR_FILE_EXTENSIONS``.

    This deliberately does NOT widen ``ANCHOR_FILE_EXTENSIONS`` and does NOT
    treat browser tabs / email / code files as context anchors.
    """
    if row.get("status") != STATUS_NORMAL:
        return False
    if not row.get("resource_is_anchor"):
        return False
    if row.get("resource_kind") in ("browser_tab", "email"):
        return False
    display_name = str(row.get("resource_display_name") or "").strip()
    if not display_name:
        display_name = str(row.get("activity_display_name") or "").strip()
    if not display_name:
        return False
    ext = _split_ext(display_name)
    if not ext:
        return False
    return ext.casefold() in _ANCHOR_EXT_SET


def is_direct_assignment_anchor(row: dict, uncategorized_id: int) -> bool:
    """True when the row is a high-confidence direct assignment anchor.

    Conditions:
      - ``status == STATUS_NORMAL``;
      - ``assignment_source`` is one of ``DIRECT_ASSIGNMENT_SOURCES``;
      - the row's project is a concrete project (not uncategorized).

    ``anchor_context`` / ``same_project_context`` /
    ``suggested_project_name`` / ``clipboard_transition_context`` /
    ``uncategorized`` are NOT direct assignment anchors and must not
    chain onward as direct anchors.
    """
    if row.get("status") != STATUS_NORMAL:
        return False
    source = row.get("assignment_source")
    if source not in DIRECT_ASSIGNMENT_SOURCES:
        return False
    # Defensive: context-derived sources must never be treated as direct
    # assignment anchors, even if a future source string overlaps.
    if source in _CONTEXT_DERIVED_SOURCES:
        return False
    if not is_concrete_project(row, uncategorized_id):
        return False
    return True
