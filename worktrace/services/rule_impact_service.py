"""Read-only rule impact preview facade."""

from __future__ import annotations

from typing import Any

from ..db import get_connection
from . import rule_planning_service as planner

MAX_RULE_BACKFILL_ACTIVITIES = 100
DEFAULT_SAMPLE_LIMIT = 20

ERR_NOT_FOUND = "not_found"
ERR_RULE_DISABLED = "rule_disabled"
ERR_PROJECT_NOT_AVAILABLE = "project_not_available"
ERR_TOO_MANY_MATCHES = "too_many_matches"
ERR_OPERATION_FAILED = "operation_failed"


class RuleImpactError(Exception):
    """Stable rule-impact error. ``code`` is one of the ``ERR_*`` literals."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def preview_rule_impact(
    rule_type: str,
    rule_id: int,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    """Preview one rule without creating jobs or mutating assignments."""

    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        raise RuleImpactError(ERR_NOT_FOUND)
    if type(rule_id) is not int or rule_id <= 0:
        raise RuleImpactError(ERR_NOT_FOUND)

    with get_connection() as conn:
        rule = planner.resolve_rule(conn, rule_type, rule_id)
        if not rule:
            raise RuleImpactError(ERR_NOT_FOUND)
        available = planner.project_available(rule)
        summary = planner.rule_summary(
            rule,
            rule_type,
            available=available,
        )
        if not int(rule.get("enabled") or 0) or not available:
            return {
                "rule": summary,
                "counts": planner.zero_counts(),
                "samples": [],
            }
        activities = planner.load_candidate_activities(conn)
        classified = planner.classify_activities(
            conn,
            activities,
            rule,
            rule_type,
        )
        return {
            "rule": summary,
            "counts": {
                key: int(value)
                for key, value in classified.items()
                if key != "would_update"
            },
            "samples": planner.sample_rows(
                list(classified.get("would_update") or []),
                rule,
                rule_type,
                int(sample_limit),
            ),
        }


__all__ = [
    "DEFAULT_SAMPLE_LIMIT",
    "ERR_NOT_FOUND",
    "ERR_OPERATION_FAILED",
    "ERR_PROJECT_NOT_AVAILABLE",
    "ERR_RULE_DISABLED",
    "ERR_TOO_MANY_MATCHES",
    "MAX_RULE_BACKFILL_ACTIVITIES",
    "RuleImpactError",
    "preview_rule_impact",
]
