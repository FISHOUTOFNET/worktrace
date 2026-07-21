"""Single command boundary for activity project assignment writes."""

from __future__ import annotations

from ..data_generation_repository import DataGenerationNamespace
from ..db import now_str
from ..domain_unit_of_work import DomainUnitOfWork


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
            uow.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)
        return changed


__all__ = [
    "assign_with_uow",
    "upsert_assignment",
]
