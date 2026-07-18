"""History, batch, and automation-status API for Project Rules."""

from __future__ import annotations

from typing import Any

from ._write_contract import (
    ERROR_INVALID_INPUT,
    ERROR_OPERATION_FAILED,
    fail_payload,
    ok_payload,
    valid_bool,
    valid_int,
)


def preview_project_rule_impact(rule_type: Any, rule_id: Any) -> dict[str, Any]:
    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_impact_service

        return ok_payload(
            impact=rule_impact_service.preview_rule_impact(rule_type, rule_id)
        )
    except rule_impact_service.RuleImpactError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def backfill_project_rule(rule_type: Any, rule_id: Any) -> dict[str, Any]:
    if not isinstance(rule_type, str) or rule_type not in {"folder", "keyword"}:
        return fail_payload(ERROR_INVALID_INPUT)
    if not valid_int(rule_id):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_history_application_service, rule_impact_service

        result = rule_history_application_service.apply_rule_to_history(
            rule_type, rule_id
        )
        return ok_payload(result=result)
    except rule_impact_service.RuleImpactError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def preview_project_rules_batch_impact(rules: Any) -> dict[str, Any]:
    if not isinstance(rules, list):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_batch_service

        return ok_payload(
            impact=rule_batch_service.preview_project_rules_batch_impact(rules)
        )
    except rule_batch_service.RuleBatchError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def backfill_project_rules_batch(rules: Any) -> dict[str, Any]:
    if not isinstance(rules, list):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_batch_service

        return ok_payload(result=rule_batch_service.backfill_project_rules_batch(rules))
    except rule_batch_service.RuleBatchError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def set_project_rules_batch_enabled(rules: Any, enabled: Any) -> dict[str, Any]:
    if not isinstance(rules, list) or not valid_bool(enabled):
        return fail_payload(ERROR_INVALID_INPUT)
    try:
        from ..services import rule_batch_service

        return ok_payload(
            result=rule_batch_service.set_project_rules_batch_enabled(rules, enabled)
        )
    except rule_batch_service.RuleBatchError as exc:
        return fail_payload(exc.code)
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


def automatic_rules_status() -> dict[str, Any]:
    try:
        from ..services import rule_automation_service

        return ok_payload(status=rule_automation_service.automatic_rules_status())
    except Exception:
        return fail_payload(ERROR_OPERATION_FAILED)


__all__ = [
    "automatic_rules_status",
    "backfill_project_rule",
    "backfill_project_rules_batch",
    "preview_project_rule_impact",
    "preview_project_rules_batch_impact",
    "set_project_rules_batch_enabled",
]
