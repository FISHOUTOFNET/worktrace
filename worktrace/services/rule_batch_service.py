"""Selected-rule batch operations service."""

from __future__ import annotations

from typing import Any

from ..db import get_connection, now_str
from . import folder_rule_service, rule_impact_service
from .rule_impact_service import (
    ERR_NOT_FOUND,
    ERR_OPERATION_FAILED,
    ERR_PROJECT_NOT_AVAILABLE,
    ERR_RULE_DISABLED,
    ERR_TOO_MANY_MATCHES,
    RuleImpactError,
)

MAX_BATCH_PROJECT_RULES = 20
MAX_BATCH_BACKFILL_ACTIVITIES = 100
MAX_BATCH_SAMPLE_ROWS = 20

# Batch-specific stable error codes. ``invalid_input`` / ``not_found`` /
# ``too_many_matches`` / ``operation_failed`` are reused from
# ``rule_impact_service`` (re-exported above) so the API layer maps them
# via the shared ``_write_contract`` codes.
ERR_TOO_MANY_RULES = "too_many_rules"


class RuleBatchError(Exception):
    """Stable batch-operation error. ``code`` is one of the ``ERR_*`` literals."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


# Input normalization + validation


def _normalize_rules(rules: Any) -> list[dict[str, Any]]:
    """Validate + normalize the ``rules`` input.

    Returns a list of ``{"rule_type": "folder"|"keyword", "rule_id": int}``
    dicts with bool-as-int ids rejected. Raises ``RuleBatchError`` with a
    stable code on any validation failure:

    - ``invalid_input`` — ``rules`` is not a non-empty list, an item is not
      a dict, an item is missing required keys, ``rule_type`` is not
      ``"folder"`` / ``"keyword"``, or ``rule_id`` is not a real positive
      ``int`` (bool / float / numeric string / ``None`` / container / zero
      / negative).
    - ``too_many_rules`` — after de-duplication the rule count exceeds
      ``MAX_BATCH_PROJECT_RULES``.
    """
    if not isinstance(rules, list) or not rules:
        raise RuleBatchError("invalid_input")
    normalized: list[dict[str, Any]] = []
    for item in rules:
        if not isinstance(item, dict):
            raise RuleBatchError("invalid_input")
        rule_type = item.get("rule_type")
        rule_id = item.get("rule_id")
        # ``isinstance(rule_type, str)`` short-circuits the set membership
        # check so unhashable non-string types collapse to invalid_input.
        if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
            raise RuleBatchError("invalid_input")
        if type(rule_id) is not int or rule_id <= 0:
            raise RuleBatchError("invalid_input")
        normalized.append({"rule_type": rule_type, "rule_id": int(rule_id)})
    # De-duplicate preserving first occurrence order. The stable selection
    # order is what the batch apply uses for first-rule-wins.
    seen: set[tuple[str, int]] = set()
    deduped: list[dict[str, Any]] = []
    for entry in normalized:
        key = (entry["rule_type"], entry["rule_id"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    if len(deduped) > MAX_BATCH_PROJECT_RULES:
        raise RuleBatchError(ERR_TOO_MANY_RULES)
    return deduped


# Rule resolution (reuses rule_impact_service helpers)


def _resolve_rule(conn, rule_type: str, rule_id: int) -> dict | None:
    if rule_type == "folder":
        return rule_impact_service._resolve_folder_rule(conn, rule_id)
    return rule_impact_service._resolve_keyword_rule(conn, rule_id)


def _rule_summary(rule: dict, rule_type: str, *, project_available: bool) -> dict[str, Any]:
    return rule_impact_service._rule_summary(
        rule, rule_type, project_available=project_available
    )


def _classify_for_rule(
    activities: list[dict], rule: dict, rule_type: str, conn
) -> dict:
    return rule_impact_service._classify_activities(activities, rule, rule_type, conn)


# Public API: batch preview


def preview_project_rules_batch_impact(rules: Any) -> dict[str, Any]:
    """Read-only aggregate impact preview across the selected rules.

    Returns the impact dict::

        {
            "rules": [<per-rule summary>],
            "counts": {<aggregate counts>},
            "samples": [<up to MAX_BATCH_SAMPLE_ROWS display-safe rows>],
        }

    Raises ``RuleBatchError`` with a stable ``code`` for ``invalid_input``
    / ``too_many_rules`` / ``not_found``. Disabled rules and unavailable
    target projects return zero counts for that rule (availability is
    surfaced in the per-rule summary), matching the single-rule preview.
    """
    normalized = _normalize_rules(rules)
    aggregate = {
        "matched_count": 0,
        "eligible_count": 0,
        "would_update_count": 0,
        "already_target_count": 0,
        "manual_skipped_count": 0,
        "hidden_skipped_count": 0,
        "deleted_skipped_count": 0,
        "in_progress_skipped_count": 0,
        "non_normal_skipped_count": 0,
    }
    rule_summaries: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    with get_connection() as conn:
        activities = rule_impact_service._fetch_activities(conn)
        for entry in normalized:
            rule_type = entry["rule_type"]
            rule_id = entry["rule_id"]
            rule = _resolve_rule(conn, rule_type, rule_id)
            if not rule:
                raise RuleBatchError(ERR_NOT_FOUND)
            project_avail = rule_impact_service._project_available(rule)
            summary = _rule_summary(rule, rule_type, project_available=project_avail)
            rule_summaries.append(summary)
            # Disabled rule / unavailable project: informational zero
            # contribution, matching the single-rule preview behavior.
            if not int(rule.get("enabled") or 0) or not project_avail:
                summary["counts"] = {
                    "matched_count": 0,
                    "eligible_count": 0,
                    "would_update_count": 0,
                    "already_target_count": 0,
                    "manual_skipped_count": 0,
                    "hidden_skipped_count": 0,
                    "deleted_skipped_count": 0,
                    "in_progress_skipped_count": 0,
                    "non_normal_skipped_count": 0,
                }
                continue
            classified = _classify_for_rule(activities, rule, rule_type, conn)
            counts = {
                "matched_count": classified["matched_count"],
                "eligible_count": classified["eligible_count"],
                "would_update_count": classified["would_update_count"],
                "already_target_count": classified["already_target_count"],
                "manual_skipped_count": classified["manual_skipped_count"],
                "hidden_skipped_count": classified["hidden_skipped_count"],
                "deleted_skipped_count": classified["deleted_skipped_count"],
                "in_progress_skipped_count": classified["in_progress_skipped_count"],
                "non_normal_skipped_count": classified["non_normal_skipped_count"],
            }
            summary["counts"] = counts
            for key, value in counts.items():
                aggregate[key] = aggregate.get(key, 0) + value
            # Append up to the remaining sample budget for this rule.
            remaining = MAX_BATCH_SAMPLE_ROWS - len(samples)
            if remaining > 0:
                samples.extend(
                    rule_impact_service._sample_rows(
                        classified["would_update"], rule, rule_type, remaining
                    )
                )
    return {
        "rules": rule_summaries,
        "counts": aggregate,
        "samples": samples,
    }


# Public API: batch backfill


def backfill_project_rules_batch(rules: Any) -> dict[str, Any]:
    """Explicit safe batch backfill of the selected rules.

    Returns the result dict with aggregate ``updated_count`` /
    ``collision_skipped_count`` / per-rule ``counts`` summaries. Raises
    ``RuleBatchError`` with a stable ``code`` for ``invalid_input`` /
    ``too_many_rules`` / ``not_found`` / ``rule_disabled`` /
    ``project_not_available`` / ``too_many_matches`` / ``operation_failed``.
    Writes nothing on any error.
    """
    normalized = _normalize_rules(rules)
    # Pre-resolve every rule and run the full preflight (existence /
    # enabled / project available) before opening the write transaction.
    # Any preflight failure -> stable code -> no writes.
    with get_connection() as conn:
        activities = rule_impact_service._fetch_activities(conn)
        resolved: list[dict[str, Any]] = []
        for entry in normalized:
            rule_type = entry["rule_type"]
            rule_id = entry["rule_id"]
            rule = _resolve_rule(conn, rule_type, rule_id)
            if not rule:
                raise RuleBatchError(ERR_NOT_FOUND)
            if not int(rule.get("enabled") or 0):
                raise RuleBatchError(ERR_RULE_DISABLED)
            if not rule_impact_service._project_available(rule):
                raise RuleBatchError(ERR_PROJECT_NOT_AVAILABLE)
            classified = _classify_for_rule(activities, rule, rule_type, conn)
            resolved.append(
                {
                    "rule_type": rule_type,
                    "rule_id": rule_id,
                    "rule": rule,
                    "classified": classified,
                }
            )
    # Total cap across the whole batch.
    total_would_update = sum(
        int(item["classified"]["would_update_count"]) for item in resolved
    )
    if total_would_update > MAX_BATCH_BACKFILL_ACTIVITIES:
        raise RuleBatchError(ERR_TOO_MANY_MATCHES)
    # First-rule-wins: an activity updated by an earlier rule is skipped
    # by later rules (counted as collision_skipped for that later rule).
    updated_activity_ids: set[int] = set()
    aggregate = {
        "updated_count": 0,
        "matched_count": 0,
        "eligible_count": 0,
        "would_update_count": 0,
        "already_target_count": 0,
        "collision_skipped_count": 0,
        "manual_skipped_count": 0,
        "hidden_skipped_count": 0,
        "deleted_skipped_count": 0,
        "in_progress_skipped_count": 0,
        "non_normal_skipped_count": 0,
    }
    per_rule: list[dict[str, Any]] = []
    with get_connection() as conn:
        ts = now_str()
        for item in resolved:
            rule_type = item["rule_type"]
            rule = item["rule"]
            classified = item["classified"]
            project_id = int(rule.get("project_id") or 0)
            source = "folder_rule" if rule_type == "folder" else "keyword_rule"
            confidence = (
                rule_impact_service._FOLDER_RULE_CONFIDENCE
                if rule_type == "folder"
                else rule_impact_service._KEYWORD_RULE_CONFIDENCE
            )
            rule_updated = 0
            rule_collision = 0
            for activity in classified["would_update"]:
                activity_id = int(activity.get("id") or 0)
                if activity_id in updated_activity_ids:
                    rule_collision += 1
                    continue
                cursor = conn.execute(
                    """
                    INSERT INTO activity_project_assignment(
                        activity_id, project_id, confidence, source, is_manual,
                        suggested_project_name, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, 0, NULL, ?, ?)
                    ON CONFLICT(activity_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        confidence = excluded.confidence,
                        source = excluded.source,
                        is_manual = 0,
                        suggested_project_name = NULL,
                        updated_at = excluded.updated_at
                    WHERE activity_project_assignment.is_manual = 0
                    """,
                    (activity_id, project_id, confidence, source, ts, ts),
                )
                if cursor.rowcount != 1:
                    continue
                updated_activity_ids.add(activity_id)
                rule_updated += 1
            counts = classified
            per_rule.append(
                {
                    "rule": _rule_summary(rule, rule_type, project_available=True),
                    "counts": {
                        "matched_count": counts["matched_count"],
                        "eligible_count": counts["eligible_count"],
                        "would_update_count": counts["would_update_count"],
                        "already_target_count": counts["already_target_count"],
                        "manual_skipped_count": counts["manual_skipped_count"],
                        "hidden_skipped_count": counts["hidden_skipped_count"],
                        "deleted_skipped_count": counts["deleted_skipped_count"],
                        "in_progress_skipped_count": counts["in_progress_skipped_count"],
                        "non_normal_skipped_count": counts["non_normal_skipped_count"],
                        "updated_count": rule_updated,
                        "collision_skipped_count": rule_collision,
                    },
                }
            )
            aggregate["updated_count"] += rule_updated
            aggregate["matched_count"] += counts["matched_count"]
            aggregate["eligible_count"] += counts["eligible_count"]
            aggregate["would_update_count"] += counts["would_update_count"]
            aggregate["already_target_count"] += counts["already_target_count"]
            aggregate["manual_skipped_count"] += counts["manual_skipped_count"]
            aggregate["hidden_skipped_count"] += counts["hidden_skipped_count"]
            aggregate["deleted_skipped_count"] += counts["deleted_skipped_count"]
            aggregate["in_progress_skipped_count"] += counts["in_progress_skipped_count"]
            aggregate["non_normal_skipped_count"] += counts["non_normal_skipped_count"]
            aggregate["collision_skipped_count"] += rule_collision
        # Context manager commits on clean exit; any raise above rolls back.
    return {
        "rules": per_rule,
        "counts": aggregate,
        "too_many_matches": False,
    }


# Public API: batch enable / disable


def set_project_rules_batch_enabled(rules: Any, enabled: Any) -> dict[str, Any]:
    """All-or-nothing batch enable / disable of the selected rules.

    Returns the result dict with per-rule summaries. Raises
    ``RuleBatchError`` with a stable ``code`` for ``invalid_input`` /
    ``too_many_rules`` / ``not_found`` / ``operation_failed``. Writes
    nothing on any error. ``enabled`` must be a real ``bool``.

    The UPDATEs run in one transaction. After commit, the existing
    keyword rule cache / privacy exclude cache / folder rule cache
    invalidation hooks fire so the automatic-rules engine and privacy
    exclude logic pick up the new enabled state. Folder index rebuild is
    intentionally NOT triggered (enable/disable does not change the
    folder path / key, matching the single-rule toggle behavior).
    """
    normalized = _normalize_rules(rules)
    if type(enabled) is not bool:
        raise RuleBatchError("invalid_input")
    # Preflight: every rule must exist (folder id on keyword path / vice
    # versa -> not_found). Done before any write so the batch is
    # all-or-nothing on existence.
    with get_connection() as conn:
        for entry in normalized:
            rule = _resolve_rule(conn, entry["rule_type"], entry["rule_id"])
            if not rule:
                raise RuleBatchError(ERR_NOT_FOUND)
    # Write phase: one transaction, UPDATE each rule's enabled flag.
    ts = now_str()
    has_folder = False
    has_keyword = False
    try:
        with get_connection() as conn:
            for entry in normalized:
                if entry["rule_type"] == "folder":
                    cur = conn.execute(
                        "UPDATE folder_project_rule SET enabled = ?, updated_at = ? "
                        "WHERE id = ?",
                        (int(enabled), ts, entry["rule_id"]),
                    )
                    has_folder = True
                else:
                    cur = conn.execute(
                        "UPDATE project_rule SET enabled = ?, updated_at = ? "
                        "WHERE id = ? AND rule_type = 'keyword'",
                        (int(enabled), ts, entry["rule_id"]),
                    )
                    has_keyword = True
                if cur.rowcount != 1:
                    raise RuleBatchError(ERR_OPERATION_FAILED)
    except RuleBatchError:
        raise
    except Exception:
        raise RuleBatchError(ERR_OPERATION_FAILED)
    # Post-commit cache invalidation. These are idempotent clears, so
    # firing them once after the batch commit preserves the single-rule
    # toggle semantics without per-row overhead.
    if has_keyword:
        from .project_inference_service import invalidate_keyword_rule_cache

        invalidate_keyword_rule_cache()
    if has_folder:
        folder_rule_service.invalidate_folder_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()
    # Re-resolve for the per-rule summaries (post-commit state).
    summaries: list[dict[str, Any]] = []
    with get_connection() as conn:
        for entry in normalized:
            rule = _resolve_rule(conn, entry["rule_type"], entry["rule_id"])
            if not rule:
                # Should not happen — the rule existed in preflight and we
                # only flipped enabled. Defensive: collapse to not_found.
                raise RuleBatchError(ERR_NOT_FOUND)
            project_avail = rule_impact_service._project_available(rule)
            summary = _rule_summary(rule, entry["rule_type"], project_available=project_avail)
            summary["enabled"] = bool(enabled)
            summaries.append(summary)
    return {
        "rules": summaries,
        "enabled": bool(enabled),
        "count": len(summaries),
    }


__all__ = [
    "ERR_TOO_MANY_RULES",
    "MAX_BATCH_BACKFILL_ACTIVITIES",
    "MAX_BATCH_PROJECT_RULES",
    "MAX_BATCH_SAMPLE_ROWS",
    "RuleBatchError",
    "backfill_project_rules_batch",
    "preview_project_rules_batch_impact",
    "set_project_rules_batch_enabled",
]
