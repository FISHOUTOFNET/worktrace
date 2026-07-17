from __future__ import annotations

from ..db import get_connection
from .activity_status_policy import is_project_attributable_status


def is_project_editable_activity(row: dict | None) -> bool:
    return bool(
        row
        and int(row.get("is_deleted") or 0) == 0
        and int(row.get("is_hidden") or 0) == 0
        and row.get("end_time") is not None
        and is_project_attributable_status(str(row.get("status") or ""))
    )


def project_editability_code(row: dict | None) -> str:
    if not row:
        return "activity_not_found"
    if int(row.get("is_deleted") or 0):
        return "activity_deleted"
    if int(row.get("is_hidden") or 0):
        return "activity_hidden"
    if row.get("end_time") is None:
        return "activity_in_progress"
    if not is_project_attributable_status(str(row.get("status") or "")):
        return "activity_not_project_activity"
    return ""


def require_project_editable_activity(activity_id: int, *, conn=None) -> dict:
    if isinstance(activity_id, bool) or not isinstance(activity_id, int) or activity_id <= 0:
        raise ValueError("activity_not_found")

    def _load_row(connection) -> dict | None:
        row = connection.execute(
            """
            SELECT id, is_deleted, is_hidden, end_time, status
            FROM activity_log
            WHERE id = ?
            """,
            (activity_id,),
        ).fetchone()
        return dict(row) if row else None

    if conn is not None:
        result = _load_row(conn)
    else:
        with get_connection() as own_conn:
            result = _load_row(own_conn)

    code = project_editability_code(result)
    if code:
        raise ValueError(code)
    return result
