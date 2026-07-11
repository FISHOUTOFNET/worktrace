"""Transactional history application and removal for one project rule.

This is the only write service used by the Project Rules UI for applying a
new rule to history or undoing the historical assignments made by a deleted
rule.  The activity log remains immutable; only assignment/projection rows
are changed.
"""

from __future__ import annotations

from ..db import get_connection
from . import context_service, rule_impact_service
from .project_inference_service import (
    _infer_project_resource_first,
    _resource_for_activity,
    _upsert_assignment,
)


def apply_rule_to_history(rule_type: str, rule_id: int) -> dict:
    """Apply one enabled rule to eligible closed non-manual history.

    ``rule_impact_service`` owns the matching/eligibility and cap checks; its
    backfill write now records this exact rule's origin columns.
    """
    return rule_impact_service.backfill_rule_impact(rule_type, rule_id)


def remove_rule_from_history(rule_type: str, rule_id: int) -> dict:
    """Remove only assignments produced by this exact rule, then re-infer.

    The row is re-inferred while the rule is explicitly excluded, so another
    matching rule can immediately take over.  Context is invalidated and
    recomputed per affected date after the direct assignments have committed.
    """
    if rule_type not in {"folder", "keyword"} or type(rule_id) is not int or rule_id <= 0:
        raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_NOT_FOUND)

    affected_dates: set[str] = set()
    updated_count = 0
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.*
            FROM activity_project_assignment apa
            JOIN activity_log a ON a.id = apa.activity_id
            WHERE apa.is_manual = 0
              AND apa.source_rule_type = ?
              AND apa.source_rule_id = ?
            ORDER BY a.id
            """,
            (rule_type, rule_id),
        ).fetchall()
        for row in rows:
            activity = dict(row)
            activity_id = int(activity["id"])
            resource = _resource_for_activity(conn, activity_id, activity)
            decision = _infer_project_resource_first(
                conn, activity, resource, exclude_rule=(rule_type, rule_id)
            )
            _upsert_assignment(
                conn,
                activity_id,
                decision.project_id,
                decision.source,
                decision.confidence,
                False,
                decision.suggested_project_name,
                decision.source_rule_type,
                decision.source_rule_id,
            )
            date = str(activity.get("start_time") or "")[:10]
            if date:
                affected_dates.add(date)
            updated_count += 1

    # The direct assignment change can alter context anchors.  These helpers
    # write only derived assignment rows and never activity_log facts.
    for date in sorted(affected_dates):
        context_service.invalidate_context_recompute_cache(date)
        context_service.recompute_context_assignments_for_date(date)

    return {
        "updated_count": updated_count,
        "matched_count": updated_count,
        "skipped_count": 0,
        "affected_dates": len(affected_dates),
    }


__all__ = ["apply_rule_to_history", "remove_rule_from_history"]
