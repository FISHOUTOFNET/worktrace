"""Single command boundary for activity project assignment writes."""

from __future__ import annotations

import logging

from ..db import get_connection, now_str

INFERENCE_RETRY_CONFIDENCE = -1


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
    """Write one assignment and return whether the expected row was owned.

    Automatic batch callers use ``protect_manual=True`` so a concurrent manual
    classification turns the entire enclosing transaction into a conflict.
    """

    if source not in {"folder_rule", "keyword_rule"}:
        source_rule_type = None
        source_rule_id = None
    timestamp = now_str()
    manual_guard = "WHERE activity_project_assignment.is_manual = 0" if protect_manual else ""
    cursor = conn.execute(
        f"""
        INSERT INTO activity_project_assignment(
            activity_id, project_id, confidence, source, is_manual,
            suggested_project_name, source_rule_type, source_rule_id,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(activity_id) DO UPDATE SET
            project_id = excluded.project_id,
            confidence = excluded.confidence,
            source = excluded.source,
            is_manual = excluded.is_manual,
            suggested_project_name = excluded.suggested_project_name,
            source_rule_type = excluded.source_rule_type,
            source_rule_id = excluded.source_rule_id,
            updated_at = excluded.updated_at
        {manual_guard}
        """,
        (
            int(activity_id),
            project_id,
            int(confidence),
            source,
            int(is_manual),
            suggested_project_name,
            source_rule_type,
            source_rule_id,
            timestamp,
            timestamp,
        ),
    )
    return cursor.rowcount == 1


def mark_inference_retry(conn, activity_id: int, uncategorized_project_id: int) -> None:
    """Mark a closed activity for opportunity-based retry without new schema."""

    if not upsert_assignment(
        conn,
        activity_id=activity_id,
        project_id=uncategorized_project_id,
        source="uncategorized",
        confidence=INFERENCE_RETRY_CONFIDENCE,
        protect_manual=True,
    ):
        logging.info("inference retry marker skipped for manual activity %s", activity_id)


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
            result = project_inference_service.assign_project_for_activity(
                int(row["id"])
            )
            if int(result.get("confidence") or 0) != INFERENCE_RETRY_CONFIDENCE:
                updated += 1
        except Exception:
            logging.exception("assignment inference retry failed for activity %s", row["id"])
    return updated


__all__ = [
    "INFERENCE_RETRY_CONFIDENCE",
    "mark_inference_retry",
    "retry_pending_inference",
    "upsert_assignment",
]
