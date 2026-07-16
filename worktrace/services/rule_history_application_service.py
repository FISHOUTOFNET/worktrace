"""Public rule-history commands backed by recoverable cursor jobs."""

from __future__ import annotations

from ..db import get_connection
from . import history_mutation_job_service, rule_impact_service


def apply_rule_to_history(rule_type: str, rule_id: int) -> dict:
    return _submit("rule_backfill", rule_type, rule_id)


def remove_rule_from_history(rule_type: str, rule_id: int) -> dict:
    return _submit("rule_remove", rule_type, rule_id)


def delete_rule(rule_type: str, rule_id: int, apply_to_history: bool) -> dict:
    if rule_type not in {"folder", "keyword"} or type(rule_id) is not int or rule_id <= 0:
        raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_NOT_FOUND)
    if type(apply_to_history) is not bool:
        raise rule_impact_service.RuleImpactError(
            rule_impact_service.ERR_OPERATION_FAILED
        )
    if apply_to_history:
        return _submit("rule_delete", rule_type, rule_id)

    with get_connection() as conn:
        table = "folder_project_rule" if rule_type == "folder" else "project_rule"
        clause = "" if rule_type == "folder" else " AND rule_type = 'keyword'"
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE id = ?{clause}",
            (int(rule_id),),
        )
        if cursor.rowcount != 1:
            raise rule_impact_service.RuleImpactError(
                rule_impact_service.ERR_NOT_FOUND
            )
    _invalidate_caches(rule_type)
    return {
        "updated_count": 0,
        "matched_count": 0,
        "skipped_count": 0,
        "affected_dates": 0,
        "queued": False,
        "status": "completed",
    }


def _submit(kind: str, rule_type: str, rule_id: int) -> dict:
    if rule_type not in {"folder", "keyword"} or type(rule_id) is not int or rule_id <= 0:
        raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_NOT_FOUND)
    try:
        return history_mutation_job_service.submit_rule_job(
            kind,
            rule_type,
            rule_id,
        )
    except ValueError as exc:
        code = str(exc)
        allowed = {
            rule_impact_service.ERR_NOT_FOUND,
            rule_impact_service.ERR_RULE_DISABLED,
            rule_impact_service.ERR_PROJECT_NOT_AVAILABLE,
        }
        raise rule_impact_service.RuleImpactError(
            code if code in allowed else rule_impact_service.ERR_OPERATION_FAILED
        ) from exc


def _invalidate_caches(rule_type: str) -> None:
    if rule_type == "folder":
        from .folder_rule_service import invalidate_folder_rule_cache

        invalidate_folder_rule_cache()
    else:
        from .project_inference_service import invalidate_keyword_rule_cache

        invalidate_keyword_rule_cache()
    from .privacy_service import clear_exclude_rules_cache

    clear_exclude_rules_cache()


__all__ = ["apply_rule_to_history", "delete_rule", "remove_rule_from_history"]
