"""Canonical Statistics project-scope policy.

A single, pure policy that normalises the transport-level project filter and
matches canonical snapshot entries against the normalised scope.  Both the
summary projection and the CSV export path use this module so that ``未归类``
never silently includes ``已排除`` standalone-status rows.
"""

from __future__ import annotations

from typing import Any

from ..constants import STATUS_EXCLUDED, UNCATEGORIZED_PROJECT

_UNCLASSIFIED_SCOPE = "unclassified"


def normalize_statistics_project_scope(value: Any) -> str:
    """Normalise the transport-level project filter to a canonical scope.

    Accepted transport values:
      * ``None`` / ``""``        -> ``""``        (全部项目)
      * ``"unclassified"``       -> ``"unclassified"`` (未归类)
      * positive int / int-str   -> ``str(int)``  (具体项目)

    Anything else raises ``ValueError("invalid_project")``.
    """

    if value is None:
        return ""
    scope = str(value).strip()
    if scope == "":
        return ""
    if scope == _UNCLASSIFIED_SCOPE:
        return _UNCLASSIFIED_SCOPE
    try:
        parsed = int(scope)
    except (TypeError, ValueError):
        raise ValueError("invalid_project")
    if parsed <= 0:
        raise ValueError("invalid_project")
    return str(parsed)


def is_standalone_excluded_entry(entry: dict[str, Any]) -> bool:
    """Return True for standalone-status rows that represent excluded time."""

    if str(entry.get("row_kind") or "") != "standalone_status":
        return False
    if bool(entry.get("privacy_redacted")):
        return True
    status = str(entry.get("status") or entry.get("status_code") or "")
    return status == STATUS_EXCLUDED


def _is_concrete_project_entry(entry: dict[str, Any], entry_project_id: int) -> bool:
    """Return True when the entry has a concrete user project attribution.

    Mirrors the ``is_concrete_project`` computation in the projection layer so
    that the system ``未归类`` bucket and deleted-project records are never
    treated as a concrete project.
    """

    if is_standalone_excluded_entry(entry):
        return False
    if entry_project_id <= 0:
        return False
    project_name = str(entry.get("project_name") or UNCATEGORIZED_PROJECT)
    if project_name == UNCATEGORIZED_PROJECT:
        return False
    if bool(entry.get("project_is_deleted")):
        return False
    return True


def entry_matches_statistics_project_scope(
    entry: dict[str, Any],
    normalized_scope: str,
) -> bool:
    """Match a canonical snapshot entry against a normalised scope.

    ``""`` — all reportable records (including excluded standalone status).

    ``"unclassified"`` — only truly unclassified ordinary report records.
    Excludes:
      * ``row_kind == "standalone_status"`` (excluded/idle/error markers)
      * ``privacy_redacted == True``
      * entries with any concrete project attribution
      * deleted-project invisible records
      * any specific project record

    ``"<positive-int>"`` — only records whose final report attribution is
    that concrete project ID.
    """

    if normalized_scope == "":
        return True
    entry_project_id = int(
        entry.get("report_project_id") or entry.get("project_id") or 0
    )
    if normalized_scope == _UNCLASSIFIED_SCOPE:
        if str(entry.get("row_kind") or "") == "standalone_status":
            return False
        if bool(entry.get("privacy_redacted")):
            return False
        if bool(entry.get("project_is_deleted")):
            return False
        return not _is_concrete_project_entry(entry, entry_project_id)
    try:
        target = int(normalized_scope)
    except (TypeError, ValueError):
        return False
    return _is_concrete_project_entry(entry, entry_project_id) and entry_project_id == target


__all__ = [
    "normalize_statistics_project_scope",
    "is_standalone_excluded_entry",
    "entry_matches_statistics_project_scope",
]
