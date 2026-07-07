from __future__ import annotations

from .activity_continuity_service import is_normal_project_status


def is_project_editable_activity(row: dict | None) -> bool:
    return bool(
        row
        and int(row.get("is_deleted") or 0) == 0
        and int(row.get("is_hidden") or 0) == 0
        and row.get("end_time") is not None
        and is_normal_project_status(str(row.get("status") or ""))
    )
