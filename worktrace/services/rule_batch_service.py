"""Selected-rule validation, preview and command delegation."""

from __future__ import annotations

from typing import Any

from ..db import get_connection
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
        if not isinstance(rule_type, str) or rule_type not in {
            "folder",
            "keyword",
        }:
            raise RuleBatchError("invalid_input")
        if type(rule_id) is not int or rule_id <= 0:
            raise RuleBatchError("invalid_input")
        key = (rule_type, int(rule_id))
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
    """Submit one durable ordered history job; this facade never writes facts."""

    normalized = _normalize_rules(rules)
    from . import history_mutation_job_service

    try:
        result = history_mutation_job_service.submit_rule_batch_job(
            normalized,
            max_updates=MAX_BATCH_BACKFILL_ACTIVITIES,
            synchronous_scan_limit=MAX_BATCH_BACKFILL_ACTIVITIES + 1,
        )
    except ValueError as exc:
        code = str(exc)
        allowed = {
            ERR_NOT_FOUND,
            ERR_RULE_DISABLED,
            ERR_PROJECT_NOT_AVAILABLE,
            ERR_TOO_MANY_MATCHES,
        }
        raise RuleBatchError(code if code in allowed else ERR_OPERATION_FAILED) from exc
    error = str(result.get("error") or "")
    if error:
        allowed = {
            ERR_NOT_FOUND,
            ERR_RULE_DISABLED,
            ERR_PROJECT_NOT_AVAILABLE,
            ERR_TOO_MANY_MATCHES,
        }
        raise RuleBatchError(error if error in allowed else ERR_OPERATION_FAILED)
    return result


def set_project_rules_batch_enabled(rules: Any, enabled: Any) -> dict[str, Any]:
    normalized = _normalize_rules(rules)
    if type(enabled) is not bool:
        raise RuleBatchError("invalid_input")
    from .rule_catalog_command_service import set_rules_enabled

    try:
        set_rules_enabled(normalized, bool(enabled))
        summaries: list[dict[str, Any]] = []
        with get_connection() as conn:
            for entry in normalized:
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
    except RuleBatchError:
        raise
    except ValueError as exc:
        code = str(exc)
        raise RuleBatchError(
            code if code in {ERR_NOT_FOUND, ERR_OPERATION_FAILED} else ERR_OPERATION_FAILED
        ) from exc
    except Exception as exc:
        raise RuleBatchError(ERR_OPERATION_FAILED) from exc
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
