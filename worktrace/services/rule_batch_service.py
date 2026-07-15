"""Selected-rule batch planning and transactional application."""

from __future__ import annotations

from typing import Any

from ..db import get_connection, now_str
from . import assignment_command_service, folder_rule_service, rule_impact_service
from .rule_impact_service import (
    ERR_NOT_FOUND,
    ERR_OPERATION_FAILED,
    ERR_PROJECT_NOT_AVAILABLE,
    ERR_RULE_DISABLED,
    ERR_TOO_MANY_MATCHES,
)

MAX_BATCH_PROJECT_RULES = 20
MAX_BATCH_BACKFILL_ACTIVITIES = 100
MAX_BATCH_SAMPLE_ROWS = 20
ERR_TOO_MANY_RULES = "too_many_rules"


class RuleBatchError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _normalize_rules(rules: Any) -> list[dict[str, Any]]:
    if not isinstance(rules, list) or not rules:
        raise RuleBatchError("invalid_input")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for item in rules:
        if not isinstance(item, dict):
            raise RuleBatchError("invalid_input")
        rule_type = item.get("rule_type")
        rule_id = item.get("rule_id")
        if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
            raise RuleBatchError("invalid_input")
        if type(rule_id) is not int or rule_id <= 0:
            raise RuleBatchError("invalid_input")
        key = (rule_type, rule_id)
        if key not in seen:
            seen.add(key)
            result.append({"rule_type": rule_type, "rule_id": rule_id})
    if len(result) > MAX_BATCH_PROJECT_RULES:
        raise RuleBatchError(ERR_TOO_MANY_RULES)
    return result


def _resolve_rule(conn, rule_type: str, rule_id: int) -> dict | None:
    if rule_type == "folder":
        return rule_impact_service._resolve_folder_rule(conn, rule_id)
    return rule_impact_service._resolve_keyword_rule(conn, rule_id)


def _rule_summary(rule: dict, rule_type: str, *, project_available: bool) -> dict[str, Any]:
    return rule_impact_service._rule_summary(
        rule,
        rule_type,
        project_available=project_available,
    )


def _classify_for_rule(activities, rule, rule_type, conn) -> dict:
    return rule_impact_service._classify_activities(
        activities,
        rule,
        rule_type,
        conn,
    )


def _zero_counts() -> dict[str, int]:
    return {
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


def _begin_immediate_after_generation_refresh(conn) -> None:
    """Refresh the thread's DB generation before acquiring the write lock.

    A database replacement between the read and ``BEGIN IMMEDIATE`` still
    changes the generation and is rejected by the process write gate.
    """

    conn.execute("SELECT 1").fetchone()
    conn.execute("BEGIN IMMEDIATE")


def _build_plan(
    conn,
    normalized: list[dict[str, Any]],
    *,
    require_applicable: bool,
) -> dict[str, Any]:
    activities = rule_impact_service._fetch_activities(conn)
    resolved: list[dict[str, Any]] = []
    winners: dict[int, int] = {}
    collision_counts: dict[int, int] = {}

    for index, entry in enumerate(normalized):
        rule = _resolve_rule(conn, entry["rule_type"], entry["rule_id"])
        if not rule:
            raise RuleBatchError(ERR_NOT_FOUND)
        enabled = bool(int(rule.get("enabled") or 0))
        available = rule_impact_service._project_available(rule)
        if require_applicable and not enabled:
            raise RuleBatchError(ERR_RULE_DISABLED)
        if require_applicable and not available:
            raise RuleBatchError(ERR_PROJECT_NOT_AVAILABLE)

        if enabled and available:
            classified = _classify_for_rule(
                activities,
                rule,
                entry["rule_type"],
                conn,
            )
        else:
            classified = _zero_counts()
            classified["would_update"] = []
        resolved.append(
            {
                "entry": entry,
                "rule": rule,
                "available": available,
                "classified": classified,
            }
        )
        collision_counts[index] = 0
        for activity in classified.get("would_update") or []:
            activity_id = int(activity.get("id") or 0)
            if activity_id in winners:
                collision_counts[index] += 1
            else:
                winners[activity_id] = index

    aggregate = _zero_counts()
    for item in resolved:
        for key in _zero_counts():
            aggregate[key] += int(item["classified"].get(key) or 0)
    aggregate["would_update_count"] = len(winners)
    aggregate["collision_skipped_count"] = sum(collision_counts.values())
    return {
        "resolved": resolved,
        "winners": winners,
        "collision_counts": collision_counts,
        "aggregate": aggregate,
    }


def preview_project_rules_batch_impact(rules: Any) -> dict[str, Any]:
    normalized = _normalize_rules(rules)
    samples: list[dict[str, Any]] = []
    with get_connection() as conn:
        plan = _build_plan(conn, normalized, require_applicable=False)
        summaries: list[dict[str, Any]] = []
        winner_ids = set(plan["winners"])
        for index, item in enumerate(plan["resolved"]):
            counts = {
                key: int(item["classified"].get(key) or 0)
                for key in _zero_counts()
            }
            counts["collision_skipped_count"] = int(
                plan["collision_counts"].get(index) or 0
            )
            summary = _rule_summary(
                item["rule"],
                item["entry"]["rule_type"],
                project_available=bool(item["available"]),
            )
            summary["counts"] = counts
            summaries.append(summary)

            remaining = MAX_BATCH_SAMPLE_ROWS - len(samples)
            if remaining > 0:
                owned = [
                    row
                    for row in item["classified"].get("would_update") or []
                    if int(row.get("id") or 0) in winner_ids
                    and plan["winners"].get(int(row.get("id") or 0)) == index
                ]
                samples.extend(
                    rule_impact_service._sample_rows(
                        owned,
                        item["rule"],
                        item["entry"]["rule_type"],
                        remaining,
                    )
                )
    return {
        "rules": summaries,
        "counts": plan["aggregate"],
        "samples": samples,
    }


def backfill_project_rules_batch(rules: Any) -> dict[str, Any]:
    normalized = _normalize_rules(rules)
    conn = get_connection()
    try:
        _begin_immediate_after_generation_refresh(conn)
        plan = _build_plan(conn, normalized, require_applicable=True)
        winners = plan["winners"]
        if len(winners) > MAX_BATCH_BACKFILL_ACTIVITIES:
            raise RuleBatchError(ERR_TOO_MANY_MATCHES)

        updated_by_rule = {index: 0 for index in range(len(plan["resolved"]))}
        for activity_id, index in winners.items():
            item = plan["resolved"][index]
            entry = item["entry"]
            rule = item["rule"]
            source = (
                "folder_rule"
                if entry["rule_type"] == "folder"
                else "keyword_rule"
            )
            confidence = (
                rule_impact_service._FOLDER_RULE_CONFIDENCE
                if entry["rule_type"] == "folder"
                else rule_impact_service._KEYWORD_RULE_CONFIDENCE
            )
            if not assignment_command_service.upsert_assignment(
                conn,
                activity_id=activity_id,
                project_id=int(rule.get("project_id") or 0),
                confidence=confidence,
                source=source,
                source_rule_type=entry["rule_type"],
                source_rule_id=int(rule.get("id") or 0),
                protect_manual=True,
            ):
                raise RuleBatchError(ERR_OPERATION_FAILED)
            updated_by_rule[index] += 1

        aggregate = dict(plan["aggregate"])
        aggregate["updated_count"] = sum(updated_by_rule.values())
        per_rule: list[dict[str, Any]] = []
        for index, item in enumerate(plan["resolved"]):
            counts = {
                key: int(item["classified"].get(key) or 0)
                for key in _zero_counts()
            }
            counts["updated_count"] = updated_by_rule[index]
            counts["collision_skipped_count"] = int(
                plan["collision_counts"].get(index) or 0
            )
            per_rule.append(
                {
                    "rule": _rule_summary(
                        item["rule"],
                        item["entry"]["rule_type"],
                        project_available=True,
                    ),
                    "counts": counts,
                }
            )
        conn.commit()
        return {
            "rules": per_rule,
            "counts": aggregate,
            "too_many_matches": False,
        }
    except RuleBatchError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise RuleBatchError(ERR_OPERATION_FAILED) from exc
    finally:
        conn.close()


def set_project_rules_batch_enabled(rules: Any, enabled: Any) -> dict[str, Any]:
    normalized = _normalize_rules(rules)
    if type(enabled) is not bool:
        raise RuleBatchError("invalid_input")
    conn = get_connection()
    has_folder = has_keyword = False
    try:
        _begin_immediate_after_generation_refresh(conn)
        resolved = []
        for entry in normalized:
            rule = _resolve_rule(conn, entry["rule_type"], entry["rule_id"])
            if not rule:
                raise RuleBatchError(ERR_NOT_FOUND)
            resolved.append((entry, rule))
        timestamp = now_str()
        for entry, _rule in resolved:
            if entry["rule_type"] == "folder":
                cursor = conn.execute(
                    "UPDATE folder_project_rule SET enabled = ?, updated_at = ? WHERE id = ?",
                    (int(enabled), timestamp, entry["rule_id"]),
                )
                has_folder = True
            else:
                cursor = conn.execute(
                    "UPDATE project_rule SET enabled = ?, updated_at = ? WHERE id = ? AND rule_type = 'keyword'",
                    (int(enabled), timestamp, entry["rule_id"]),
                )
                has_keyword = True
            if cursor.rowcount != 1:
                raise RuleBatchError(ERR_OPERATION_FAILED)
        summaries = []
        for entry, _rule in resolved:
            current = _resolve_rule(conn, entry["rule_type"], entry["rule_id"])
            if not current:
                raise RuleBatchError(ERR_NOT_FOUND)
            summary = _rule_summary(
                current,
                entry["rule_type"],
                project_available=rule_impact_service._project_available(current),
            )
            summary["enabled"] = bool(enabled)
            summaries.append(summary)
        conn.commit()
    except RuleBatchError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise RuleBatchError(ERR_OPERATION_FAILED) from exc
    finally:
        conn.close()

    if has_keyword:
        from .project_inference_service import invalidate_keyword_rule_cache

        invalidate_keyword_rule_cache()
    if has_folder:
        folder_rule_service.invalidate_folder_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()
    return {"rules": summaries, "enabled": bool(enabled), "count": len(summaries)}


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
