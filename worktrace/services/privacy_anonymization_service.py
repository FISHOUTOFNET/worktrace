from __future__ import annotations

from ..constants import STATUS_EXCLUDED
from ..data_generation_repository import DataGenerationNamespace
from ..domain_unit_of_work import DomainUnitOfWork
from ..db import now_str
from ..resources.resource_builders import make_system_resource
from . import privacy_service
from .activity_resource_command_service import (
    update_path_or_anonymize as persist_path_or_anonymize,
)
from .resource_service import create_or_update_activity_resource


def update_path_or_anonymize(activity_id: int, file_path_hint: str) -> bool:
    """Persist or redact using the path command's transaction snapshot."""
    if not (file_path_hint or "").strip():
        return False
    return persist_path_or_anonymize(int(activity_id), file_path_hint)


def anonymize_activity(activity_id: int) -> None:
    payload = privacy_service.make_excluded_activity_payload()
    with DomainUnitOfWork(
        (DataGenerationNamespace.REPORT_STRUCTURE,)
    ) as uow:
        conn = uow.connection
        row = conn.execute(
            "SELECT id FROM activity_log WHERE id = ?",
            (int(activity_id),),
        ).fetchone()
        if not row:
            return
        conn.execute(
            """
            UPDATE activity_log
            SET app_name = ?, process_name = ?, window_title = ?,
                file_path_hint = NULL, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                payload["app_name"],
                payload["process_name"],
                payload["window_title"],
                STATUS_EXCLUDED,
                now_str(),
                int(activity_id),
            ),
        )
        conn.execute(
            "DELETE FROM activity_clipboard_event WHERE activity_id = ?",
            (int(activity_id),),
        )
        create_or_update_activity_resource(
            int(activity_id),
            make_system_resource(STATUS_EXCLUDED),
            conn=conn,
        )
        uow.mark_changed(DataGenerationNamespace.REPORT_STRUCTURE)


__all__ = [
    "anonymize_activity",
    "update_path_or_anonymize",
]
