"""Selected-rule planning outside write locks and bounded application."""

from __future__ import annotations

from typing import Any

from ..db import get_connection, now_str
from . import assignment_command_service, folder_rule_service
from . import rule_planning_service as planner

MAX_BATCH_PROJECT_RULES = 20
MAX_BATCH_BACKFILL_ACTIVITIES = 100
MAX_BATCH_SAMPLE_ROWS = 20
ERR_TOO_MANY_RULES = "too_many_rules"
ERR_NOT_FOUND = "not_found"
ERR_RULE_DISABLED = "rule_disabled"
ERR_PROJECT_NOT_AVAILABLE = "project_not_available"
ERR_TOO_MANY_MATCHES = "too_many_matches"
ERR_OPERATION_FAILED = "operation_failed"


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
        if rule_type not in {"folder", "keyword"}:
            raise RuleBatchError("invalid_input")
        if type(rule_id) is not int or rule_id <= 0:
            raise RuleBatchError("invalid_input")
        key = (str(rule_type), int(rule_id))
        if key not in seen:
            seen.add(key)
            result.append({"rule_type": key[0], "rule_id": key[1]})
    if len(result) > MAX_BATCH_PROJECT_RULES:
        raise RuleBatchError(ERR_TOO_MANY_RULES)
    return result


def preview_project_rules_batch_impact(rules: Any) -> dict[str, Any]:
    normalized = _normalize_rules(rules)
    with get_connection() as conn:
        plan = _build_plan(conn, normalized, require_applicable=False)
    samples: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    winner_ids = set(plan["winners"])
    for index, item in enumerate(plan["resolved"]):
        counts = _public_counts(item["classified"])
        counts["collision_skipped_count"] = int(
            plan["collision_counts"].get(index) or 0
        )
        summaries.append(
            {
                **planner.rule_summary(
                    item["rule"],
                    item["entry"]["rule_type"],
                    available=bool(item["available"]),
                ),
                "counts": counts,
            }
        )
        remaining = MAX_BATCH_SAMPLE_ROWS - len(samples)
        if remaining <= 0:
            continue
        owned = [
            row
            for row in item["classified"].get("would_update") or []
            if int(row.get("id") or 0) in winner_ids
            and plan["winners"].get(int(row.get("id") or 0)) == index
        ]
        samples.extend(
            planner.sample_rows(
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
    """Plan with a read transaction, then apply only a bounded immutable set."""

    normalized = _normalize_rules(rules)
    with get_connection() as read_conn:
        plan = _build_plan(read_conn, normalized, require_applicable=True)
    winners = dict(plan["winners"])
    if len(winners) > MAX_BATCH_BACKFILL_ACTIVITIES:
        raise RuleBatchError(ERR_TOO_MANY_MATCHES)

    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        _revalidate_plan(conn, plan)
        updated_by_rule = {
            index: 0 for index in range(len(plan["resolved"]))
        }
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
                planner.FOLDER_RULE_CONFIDENCE
                if entry["rule_type"] == "folder"
                else planner.KEYWORD_RULE_CONFIDENCE
            )
            if not assignment_command_service.upsert_assignment(
                conn,
                activity_id=int(activity_id),
                project_id=int(rule.get("project_id") or 0),
                confidence=confidence,
                source=source,
                source_rule_type=entry["rule_type"],
                source_rule_id=int(rule.get("id") or 0),
                protect_manual=True,
            ):
                raise RuleBatchError(ERR_OPERATION_FAILED)
            updated_by_rule[index] += 1
        conn.commit()
    except RuleBatchError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise RuleBatchError(ERR_OPERATION_FAILED) from exc
    finally:
        conn.close()

    per_rule: list[dict[str, Any]] = []
    for index, item in enumerate(plan["resolved"]):
        counts = _public_counts(item["classified"])
        counts["updated_count"] = updated_by_rule[index]
        counts["collision_skipped_count"] = int(
            plan["collision_counts"].get(index) or 0
        )
        per_rule.append(
            {
                "rule": planner.rule_summary(
                    item["rule"],
                    item["entry"]["rule_type"],
                    available=True,
                ),
                "counts": counts,
            }
        )
    aggregate = dict(plan["aggregate"])
    aggregate["updated_count"] = sum(updated_by_rule.values())
    return {
        "rules": per_rule,
        "counts": aggregate,
        "too_many_matches": False,
    }


def set_project_rules_batch_enabled(rules: Any, enabled: Any) -> dict[str, Any]:
    normalized = _normalize_rules(rules)
    if type(enabled) is not bool:
        raise RuleBatchError("invalid_input")
    conn = get_connection()
    has_folder = has_keyword = False
    try:
        conn.execute("BEGIN IMMEDIATE")
        resolved: list[tuple[dict[str, Any], dict]] = []
        for entry in normalized:
            rule = planner.resolve_rule(
                conn,
                entry["rule_type"],
                entry["rule_id"],
            )
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
                    "UPDATE project_rule SET enabled = ?, updated_at = ? "
                    "WHERE id = ? AND rule_type = 'keyword'",
                    (int(enabled), timestamp, entry["rule_id"]),
                )
                has_keyword = True
            if cursor.rowcount != 1:
                raise RuleBatchError(ERR_OPERATION_FAILED)
        summaries = []
        for entry, _rule in resolved:
            current = planner.resolve_rule(
                conn,
                entry["rule_type"],
                entry["rule_id"],
            )
            if not current:
                raise RuleBatchError(ERR_NOT_FOUND)
            summary = planner.rule_summary(
                current,
                entry["rule_type"],
                available=planner.project_available(current),
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


def _build_plan(
    conn,
    normalized: list[dict[str, Any]],
    *,
    require_applicable: bool,
) -> dict[str, Any]:
    activities = planner.load_candidate_activities(conn)
    resolved: list[dict[str, Any]] = []
    winners: dict[int, int] = {}
    collision_counts: dict[int, int] = {}
    for index, entry in enumerate(normalized):
        rule = planner.resolve_rule(
            conn,
            entry["rule_type"],
            entry["rule_id"],
        )
        if not rule:
            raise RuleBatchError(ERR_NOT_FOUND)
        enabled = bool(int(rule.get("enabled") or 0))
        available = planner.project_available(rule)
        if require_applicable and not enabled:
            raise RuleBatchError(ERR_RULE_DISABLED)
        if require_applicable and not available:
            raise RuleBatchError(ERR_PROJECT_NOT_AVAILABLE)
        if enabled and available:
            classified = planner.classify_activities(
                conn,
                activities,
                rule,
                entry["rule_type"],
            )
        else:
            classified = planner.zero_counts()
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
    aggregate = planner.zero_counts()
    for item in resolved:
        for key in planner.zero_counts():
            aggregate[key] += int(item["classified"].get(key) or 0)
    aggregate["would_update_count"] = len(winners)
    aggregate["collision_skipped_count"] = sum(collision_counts.values())
    return {
        "resolved": resolved,
        "winners": winners,
        "collision_counts": collision_counts,
        "aggregate": aggregate,
    }


def _revalidate_plan(conn, plan: dict[str, Any]) -> None:
    for item in plan["resolved"]:
        entry = item["entry"]
        current = planner.resolve_rule(
            conn,
            entry["rule_type"],
            entry["rule_id"],
        )
        if not current:
            raise RuleBatchError(ERR_NOT_FOUND)
        if str(current.get("updated_at") or "") != str(
            item["rule"].get("updated_at") or ""
        ):
            raise RuleBatchError(ERR_OPERATION_FAILED)
        if not int(current.get("enabled") or 0):
            raise RuleBatchError(ERR_RULE_DISABLED)
        if not planner.project_available(current):
            raise RuleBatchError(ERR_PROJECT_NOT_AVAILABLE)


def _public_counts(classified: dict[str, Any]) -> dict[str, int]:
    return {
        key: int(classified.get(key) or 0)
        for key in planner.zero_counts()
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
