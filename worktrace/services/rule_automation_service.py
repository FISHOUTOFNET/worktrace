"""Automatic Project Rules application foundation.

This module is the **named, documented entry point** for the automatic
application of enabled folder / keyword Project Rules to new eligible
activities. It does NOT re-implement matching or inference: the real work
lives in :mod:`worktrace.services.project_inference_service`, which the
collector / activity_service hook (``finalize_created_activity`` ->
``process_new_activity`` -> ``assign_project_for_activity``) calls
when an activity is persisted.
the supported automatic-rules contract and ships regression locks + docs
rather than a second divergent matcher.

Why a thin facade (and not a re-implementation)?

- ``assign_project_for_activity`` already reuses the single folder / keyword
  matching code paths
  (``folder_rule_service.find_matching_folder_rule`` for folder rules and
  ``_enabled_keyword_rules`` + ``_safe_classification_text`` +
  ``keyword_pattern_matches`` for keyword rules), so there is no second
  matcher to maintain.
- It already implements the deterministic priority: folder rules before
  keyword rules; within each kind, rules are read in ``created_at, id``
  order (stable). The first match wins and no later rule overwrites it.
  rule overwrites it.
- It already skips ``manual_override = 1`` / ``is_manual = 1`` activities
  and non-normal activities, never sets ``manual_override = 1``, writes
  ``auto_classified = 1`` for ``folder_rule`` / ``keyword_rule`` sources,
  and upserts the assignment with ``is_manual = 0``, the rule source, and
  the inference confidence (85 folder / 80 keyword).
  5H single-rule backfill contract.
- The enabled-rule / available-project gating is already enforced by the
  read paths: ``_enabled_keyword_rules`` filters on
  ``pr.enabled = 1 AND p.enabled = 1 AND p.name <> EXCLUDED_PROJECT``;
  ``find_matching_folder_rule`` only returns enabled rules on enabled,
  non-excluded projects.

Scope (locked by ``tests/test_project_rules_automatic_rules.py``):

- Automatic application of enabled folder / keyword rules to future
  eligible closed activities is SUPPORTED. The hook fires at activity
  persistence (``finalize_created_activity``), which is when a closed
  activity is written to ``activity_log``.
- Disabled rules, disabled / archived / excluded target projects,
  ``manual_override = 1`` / ``is_manual = 1`` activities, hidden / deleted
  / in-progress / non-normal activities, and activities already on the
  target project are skipped / not overwritten.
- No DB schema change, no new dependency, no new table / column.
- No WebView toggle is added: the foundation is always-on for enabled
  rules. The Project Rules page surfaces this as a status note.
"""

from __future__ import annotations

from typing import Any

from . import project_inference_service

# Folder / keyword inference confidences — identical to the values used by
# ``project_inference_service._infer_project_resource_first`` and the
# single-rule backfill. Exposed as module constants so tests can lock
# them without reaching into the inference module's privates.
FOLDER_RULE_CONFIDENCE = 85
KEYWORD_RULE_CONFIDENCE = 80

# Stable source strings written to ``activity_project_assignment.source``.
FOLDER_RULE_SOURCE = "folder_rule"
KEYWORD_RULE_SOURCE = "keyword_rule"

# Deterministic priority: folder rules before keyword rules. Within each
# kind, ``project_inference_service._enabled_keyword_rules`` orders by
# ``created_at, id`` and ``folder_rule_service.find_matching_folder_rule``
# returns the first match in its own stable order. The first matching rule
# wins and no later rule overwrites it.
AUTOMATIC_RULE_PRIORITY = (FOLDER_RULE_SOURCE, KEYWORD_RULE_SOURCE)


def apply_automatic_rules_to_activity(activity_id: int) -> dict[str, Any]:
    """Apply enabled folder / keyword Project Rules to one activity.

    Thin, documented delegation to
    ``project_inference_service.process_new_activity`` (the automatic-rules
    entry point). The automatic path applies narrow skip guards for hidden /
    facade. The automatic path applies narrow skip guards for hidden /
    deleted / in-progress activities before delegating to
    ``assign_project_for_activity``; the inference itself reuses the
    single folder / keyword matching code paths, skips
    ``manual_override = 1`` / ``is_manual = 1`` / non-normal activities,
    never sets ``manual_override = 1``, writes ``auto_classified = 1`` for
    rule-driven assignments, and upserts the assignment with
    ``is_manual = 0`` and the rule source + confidence (85 folder /
    80 keyword).

    Returns the assignment row dict (the same shape
    ``assign_project_for_activity`` returns). Raises ``ValueError`` if the
    activity does not exist (mirroring the underlying inference function).
    """
    return project_inference_service.process_new_activity(activity_id)


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
            "manual_override",
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
            "auto_classified": True,
            "manual_override": False,
            "is_manual": False,
        },
    }


__all__ = [
    "AUTOMATIC_RULE_PRIORITY",
    "FOLDER_RULE_CONFIDENCE",
    "FOLDER_RULE_SOURCE",
    "KEYWORD_RULE_CONFIDENCE",
    "KEYWORD_RULE_SOURCE",
    "apply_automatic_rules_to_activity",
    "automatic_rules_status",
]
