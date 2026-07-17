"""Batch rule command facade."""

from __future__ import annotations

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection
from ..domain_unit_of_work import DomainUnitOfWork
from ..mutation_effects import classification_catalog_mutation
from ..service_facade import bind_core_facade
from ..write_gate import DATABASE_WRITE_GATE
from . import rule_batch_service_core as _core

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)


def backfill_project_rules_batch(rules):
    """Plan outside the write lock, then revalidate and apply in one report UoW."""

    normalized = _core._normalize_rules(rules)
    with get_connection() as read_conn:
        plan = _core._build_plan(read_conn, normalized, require_applicable=True)
    winners = dict(plan["winners"])
    if len(winners) > _core.MAX_BATCH_BACKFILL_ACTIVITIES:
        raise _core.RuleBatchError(_core.ERR_TOO_MANY_MATCHES)

    # A drained/replaced database between planning and admission is safe because
    # the plan is fully revalidated after BEGIN IMMEDIATE on the current DB.
    DATABASE_WRITE_GATE.note_current_thread_read()
    try:
        with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)):
            with get_connection() as conn:
                _core._revalidate_plan(conn, plan)
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
                        _core.planner.FOLDER_RULE_CONFIDENCE
                        if entry["rule_type"] == "folder"
                        else _core.planner.KEYWORD_RULE_CONFIDENCE
                    )
                    if not _core.assignment_command_service.upsert_assignment(
                        conn,
                        activity_id=int(activity_id),
                        project_id=int(rule.get("project_id") or 0),
                        confidence=confidence,
                        source=source,
                        source_rule_type=entry["rule_type"],
                        source_rule_id=int(rule.get("id") or 0),
                        protect_manual=True,
                    ):
                        raise _core.RuleBatchError(_core.ERR_OPERATION_FAILED)
                    updated_by_rule[index] += 1
    except _core.RuleBatchError:
        raise
    except Exception as exc:
        raise _core.RuleBatchError(_core.ERR_OPERATION_FAILED) from exc

    per_rule = []
    for index, item in enumerate(plan["resolved"]):
        counts = _core._public_counts(item["classified"])
        counts["updated_count"] = updated_by_rule[index]
        counts["collision_skipped_count"] = int(
            plan["collision_counts"].get(index) or 0
        )
        per_rule.append(
            {
                "rule": _core.planner.rule_summary(
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


set_project_rules_batch_enabled = classification_catalog_mutation(
    _core.set_project_rules_batch_enabled
)

_core.backfill_project_rules_batch = backfill_project_rules_batch
_core.set_project_rules_batch_enabled = set_project_rules_batch_enabled
bind_core_facade(__name__, _core)
