"""Public rule-history commands backed by recoverable cursor jobs."""

from __future__ import annotations

from . import (
    folder_rule_service,
    history_mutation_job_service,
    rule_impact_service,
    rule_service,
)


def apply_rule_to_history(rule_type: str, rule_id: int) -> dict:
    return _submit("rule_backfill", rule_type, rule_id)


def remove_rule_from_history(rule_type: str, rule_id: int) -> dict:
    return _submit("rule_remove", rule_type, rule_id)


def delete_rule(rule_type: str, rule_id: int, apply_to_history: bool) -> dict:
    _validate(rule_type, rule_id)
    if type(apply_to_history) is not bool:
        raise rule_impact_service.RuleImpactError(
            rule_impact_service.ERR_OPERATION_FAILED
        )
    if apply_to_history:
        return _submit("rule_delete", rule_type, rule_id)

    deleted = (
        folder_rule_service.delete_folder_rule(rule_id)
        if rule_type == "folder"
        else rule_service.delete_rule(rule_id)
    )
    if not deleted:
        raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_NOT_FOUND)
    return {
        "updated_count": 0,
        "matched_count": 0,
        "skipped_count": 0,
        "affected_dates": 0,
        "queued": False,
        "status": "completed",
    }


def _validate(rule_type: str, rule_id: int) -> None:
    if (
        rule_type not in {"folder", "keyword"}
        or type(rule_id) is not int
        or rule_id <= 0
    ):
        raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_NOT_FOUND)


def _submit(kind: str, rule_type: str, rule_id: int) -> dict:
    _validate(rule_type, rule_id)
    try:
        result = history_mutation_job_service.submit_rule_job(
            rule_type,
            rule_id,
            kind=kind,
            synchronous_scan_limit=100,
        )
        if str(result.get("status") or "") == "failed" and not bool(
            result.get("queued")
        ):
            history_mutation_job_service.compensate_failed_synchronous_job(
                int(result.get("job_id") or 0)
            )
            raise rule_impact_service.RuleImpactError(
                rule_impact_service.ERR_OPERATION_FAILED
            )
        return result
    except rule_impact_service.RuleImpactError:
        raise
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


__all__ = ["apply_rule_to_history", "delete_rule", "remove_rule_from_history"]
