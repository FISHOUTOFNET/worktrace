"""Display-safe policy metadata for automatic Project Rules."""

from __future__ import annotations

from typing import Any

# Folder / keyword inference confidences, exposed as module constants so
# tests can lock them without reaching into the inference module's privates.
FOLDER_RULE_CONFIDENCE = 85
KEYWORD_RULE_CONFIDENCE = 80

FOLDER_RULE_SOURCE = "folder_rule"
KEYWORD_RULE_SOURCE = "keyword_rule"

# Deterministic priority: folder rules before keyword rules. Within each
# kind, ordering is stable (created_at, id for keyword; first match for
# folder); the first matching rule wins and later matches are ignored.
AUTOMATIC_RULE_PRIORITY = (FOLDER_RULE_SOURCE, KEYWORD_RULE_SOURCE)


def automatic_rules_status() -> dict[str, Any]:
    """Return a display-safe status payload describing the automatic-rules
    foundation for the Project Rules page.

    The payload is intentionally narrow and display-safe: it only carries
    boolean / string fields that the frontend needs to render a status
    note. It never exposes raw rule rows, project rows, window titles,
    file paths, notes, clipboard text, SQL, or tracebacks.
    """
    return {
        "supported": True,
        "scope": "enabled_folder_keyword_rules",
        "priority": "folder_before_keyword",
        "confidence": {
            "folder_rule": FOLDER_RULE_CONFIDENCE,
            "keyword_rule": KEYWORD_RULE_CONFIDENCE,
        },
        "skips": [
            "is_manual",
            "hidden",
            "deleted",
            "in_progress",
            "non_normal",
            "already_target",
            "disabled_rule",
            "disabled_project",
            "archived_project",
            "excluded_project",
        ],
        "writes": {
            "activity_project_assignment": True,
            "activity_log": False,
        },
    }


__all__ = [
    "AUTOMATIC_RULE_PRIORITY",
    "FOLDER_RULE_CONFIDENCE",
    "FOLDER_RULE_SOURCE",
    "KEYWORD_RULE_CONFIDENCE",
    "KEYWORD_RULE_SOURCE",
    "automatic_rules_status",
]
