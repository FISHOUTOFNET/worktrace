"""Transactional history application, removal, and deletion for one rule."""

from __future__ import annotations

from ..db import get_connection
from . import context_service, rule_impact_service
from .project_inference_service import (
    _infer_project_resource_first,
    _resource_for_activity,
    _upsert_assignment,
)


def apply_rule_to_history(rule_type: str, rule_id: int) -> dict:
    return rule_impact_service.backfill_rule_impact(rule_type, rule_id)


def remove_rule_from_history(rule_type: str, rule_id: int) -> dict:
    if rule_type not in {"folder", "keyword"} or type(rule_id) is not int or rule_id <= 0:
        raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_NOT_FOUND)
    with get_connection() as conn:
        result = _remove_rule_from_history_in_transaction(conn, rule_type, rule_id)
    _invalidate_rule_delete_caches(result["affected_date_values"])
    return _public_history_result(result)


def delete_rule(rule_type: str, rule_id: int, apply_to_history: bool) -> dict:
    """Delete a folder/keyword rule and optional history impact in one DB transaction."""
    if rule_type not in {"folder", "keyword"} or type(rule_id) is not int or rule_id <= 0:
        raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_NOT_FOUND)
    if type(apply_to_history) is not bool:
        raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_OPERATION_FAILED)
    history_result = {
        "updated_count": 0,
        "matched_count": 0,
        "skipped_count": 0,
        "affected_date_values": [],
    }
    with get_connection() as conn:
        if _load_rule_for_delete(conn, rule_type, rule_id) is None:
            raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_NOT_FOUND)
        if apply_to_history:
            affected_rows = _load_assignments_for_rule(conn, rule_type, rule_id)
        _delete_rule_in_transaction(conn, rule_type, rule_id)
        if apply_to_history:
            # The rule is absent in this transaction snapshot, so direct and
            # context re-inference cannot accidentally select it again.
            history_result = _reassign_deleted_rule_history(conn, affected_rows)
    _invalidate_rule_delete_caches(history_result["affected_date_values"])
    return _public_history_result(history_result)


def _remove_rule_from_history_in_transaction(conn, rule_type: str, rule_id: int) -> dict:
    rows = _load_assignments_for_rule(conn, rule_type, rule_id)
    return _reassign_deleted_rule_history(conn, rows, exclude_rule=(rule_type, rule_id))


def _load_assignments_for_rule(conn, rule_type: str, rule_id: int) -> list:
    return conn.execute(
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


def _reassign_deleted_rule_history(conn, rows: list, exclude_rule=None) -> dict:
    affected_dates: set[str] = set()
    updated_count = 0
    for row in rows:
        activity = dict(row)
        activity_id = int(activity["id"])
        resource = _resource_for_activity(conn, activity_id, activity)
        decision = _infer_project_resource_first(conn, activity, resource, exclude_rule=exclude_rule)
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
        affected_dates.update(_context_dates_for_activity(activity))
        updated_count += 1
    for affected_date in sorted(affected_dates):
        context_service._recompute_context_assignments_for_date_in_transaction(
            conn, affected_date, use_cache=False
        )
    return {
        "updated_count": updated_count,
        "matched_count": updated_count,
        "skipped_count": 0,
        "affected_date_values": sorted(affected_dates),
    }


def _load_rule_for_delete(conn, rule_type: str, rule_id: int) -> dict | None:
    if rule_type == "folder":
        row = conn.execute(
            "SELECT * FROM folder_project_rule WHERE id = ?",
            (rule_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM project_rule WHERE id = ? AND rule_type = 'keyword'",
            (rule_id,),
        ).fetchone()
    return dict(row) if row else None


def _delete_rule_in_transaction(conn, rule_type: str, rule_id: int) -> None:
    if rule_type == "folder":
        from .folder_index_service import delete_index_for_rule

        delete_index_for_rule(rule_id, conn=conn)
        cur = conn.execute("DELETE FROM folder_project_rule WHERE id = ?", (rule_id,))
    else:
        cur = conn.execute(
            "DELETE FROM project_rule WHERE id = ? AND rule_type = 'keyword'",
            (rule_id,),
        )
    if cur.rowcount != 1:
        raise rule_impact_service.RuleImpactError(rule_impact_service.ERR_NOT_FOUND)


def _context_dates_for_activity(activity: dict) -> set[str]:
    values = {
        str(activity.get("start_time") or "")[:10],
        str(activity.get("end_time") or "")[:10],
    }
    return {value for value in values if value}


def _invalidate_rule_delete_caches(affected_dates: list[str]) -> None:
    from .folder_rule_service import invalidate_folder_rule_cache
    from .privacy_service import clear_exclude_rules_cache
    from .project_inference_service import invalidate_keyword_rule_cache

    invalidate_folder_rule_cache()
    invalidate_keyword_rule_cache()
    clear_exclude_rules_cache()
    for affected_date in affected_dates:
        context_service.invalidate_context_recompute_cache(affected_date)


def _public_history_result(result: dict) -> dict:
    affected_dates = list(result.get("affected_date_values") or [])
    return {
        "updated_count": int(result.get("updated_count") or 0),
        "matched_count": int(result.get("matched_count") or 0),
        "skipped_count": int(result.get("skipped_count") or 0),
        "affected_dates": len(affected_dates),
    }


__all__ = ["apply_rule_to_history", "delete_rule", "remove_rule_from_history"]
