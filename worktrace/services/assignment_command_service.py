"""Single command boundary for activity project assignment writes."""

from __future__ import annotations

import logging

from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork

INFERENCE_RETRY_CONFIDENCE = -1


def _normalized_rule_identity(
    source: str,
    source_rule_type: str | None,
    source_rule_id: int | None,
) -> tuple[str | None, int | None]:
    if source not in {"folder_rule", "keyword_rule"}:
        return None, None
    return source_rule_type, int(source_rule_id) if source_rule_id is not None else None


def upsert_assignment(
    conn,
    *,
    activity_id: int,
    project_id: int | None,
    source: str,
    confidence: int,
    is_manual: bool = False,
    suggested_project_name: str | None = None,
    source_rule_type: str | None = None,
    source_rule_id: int | None = None,
    protect_manual: bool = False,
) -> bool:
    """Persist one assignment and report whether its durable value changed."""

    activity_id = int(activity_id)
    source_rule_type, source_rule_id = _normalized_rule_identity(
        source,
        source_rule_type,
        source_rule_id,
    )
    desired = (
        int(project_id) if project_id is not None else None,
        int(confidence),
        str(source),
        int(bool(is_manual)),
        suggested_project_name or None,
        source_rule_type,
        source_rule_id,
    )
    existing = conn.execute(
        """
        SELECT project_id, confidence, source, is_manual,
               suggested_project_name, source_rule_type, source_rule_id
        FROM activity_project_assignment
        WHERE activity_id = ?
        """,
        (activity_id,),
    ).fetchone()
    if existing is not None:
        if protect_manual and int(existing["is_manual"] or 0):
            return False
        current = (
            int(existing["project_id"]) if existing["project_id"] is not None else None,
            int(existing["confidence"] or 0),
            str(existing["source"] or ""),
            int(existing["is_manual"] or 0),
            existing["suggested_project_name"] or None,
            existing["source_rule_type"] or None,
            int(existing["source_rule_id"])
            if existing["source_rule_id"] is not None
            else None,
        )
        if current == desired:
            return False
        conn.execute(
            """
            UPDATE activity_project_assignment
            SET project_id = ?, confidence = ?, source = ?, is_manual = ?,
                suggested_project_name = ?, source_rule_type = ?,
                source_rule_id = ?, updated_at = ?
            WHERE activity_id = ?
            """,
            (*desired, now_str(), activity_id),
        )
        return True

    timestamp = now_str()
    conn.execute(
        """
        INSERT INTO activity_project_assignment(
            activity_id, project_id, confidence, source, is_manual,
            suggested_project_name, source_rule_type, source_rule_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (activity_id, *desired, timestamp, timestamp),
    )
    return True


def assign_with_uow(
    *,
    activity_id: int,
    project_id: int | None,
    source: str,
    confidence: int,
    is_manual: bool = False,
    suggested_project_name: str | None = None,
    source_rule_type: str | None = None,
    source_rule_id: int | None = None,
    protect_manual: bool = False,
) -> bool:
    """Run a standalone assignment command in the canonical report UoW."""

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        changed = upsert_assignment(
            uow.connection,
            activity_id=activity_id,
            project_id=project_id,
            source=source,
            confidence=confidence,
            is_manual=is_manual,
            suggested_project_name=suggested_project_name,
            source_rule_type=source_rule_type,
            source_rule_id=source_rule_id,
            protect_manual=protect_manual,
        )
        if changed:
            uow.mark_changed()
        return changed


def mark_inference_retry(conn, activity_id: int, uncategorized_project_id: int) -> bool:
    """Mark a closed activity for bounded opportunity-based inference retry."""

    changed = upsert_assignment(
        conn,
        activity_id=activity_id,
        project_id=uncategorized_project_id,
        source="uncategorized",
        confidence=INFERENCE_RETRY_CONFIDENCE,
        protect_manual=True,
    )
    if not changed:
        logging.info("inference retry marker unchanged for activity %s", activity_id)
    return changed


def mark_inference_retry_with_uow(activity_id: int) -> bool:
    """Persist a retry marker through the canonical assignment transaction."""

    from .system_project_service import require_uncategorized_project_id

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        project_id = require_uncategorized_project_id(uow.connection)
        changed = mark_inference_retry(uow.connection, int(activity_id), project_id)
        if changed:
            uow.mark_changed()
        return changed


def retry_pending_inference(limit: int = 100) -> int:
    """Retry a bounded set of prior transient inference failures."""

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.id
            FROM activity_log a
            JOIN activity_project_assignment apa ON apa.activity_id = a.id
            WHERE a.end_time IS NOT NULL
              AND a.status = 'normal'
              AND a.is_hidden = 0
              AND a.is_deleted = 0
              AND apa.is_manual = 0
              AND apa.source = 'uncategorized'
              AND apa.confidence = ?
            ORDER BY a.id
            LIMIT ?
            """,
            (INFERENCE_RETRY_CONFIDENCE, max(0, int(limit))),
        ).fetchall()
    updated = 0
    from . import project_inference_service

    for row in rows:
        try:
            result = project_inference_service.assign_project_for_activity(int(row["id"]))
            if int(result.get("confidence") or 0) != INFERENCE_RETRY_CONFIDENCE:
                updated += 1
        except Exception:
            logging.exception("assignment inference retry failed for activity %s", row["id"])
    return updated


__all__ = [
    "INFERENCE_RETRY_CONFIDENCE",
    "assign_with_uow",
    "mark_inference_retry",
    "mark_inference_retry_with_uow",
    "retry_pending_inference",
    "upsert_assignment",
]
