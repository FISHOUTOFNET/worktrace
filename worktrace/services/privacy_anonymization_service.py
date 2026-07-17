from __future__ import annotations

from ..constants import STATUS_EXCLUDED
from ..data_generation_repository import DataGenerationNamespace
from ..domain_unit_of_work import DomainUnitOfWork
from ..db import now_str
from ..platforms.base import ActiveWindow
from ..resources.resource_builders import make_system_resource
from . import activity_service, privacy_service
from .resource_service import create_or_update_activity_resource


def path_requires_exclusion(activity_id: int, file_path_hint: str) -> bool:
    """Evaluate a newly resolved path before any real path is persisted."""
    activity = activity_service.get_activity(int(activity_id))
    if not activity:
        return False
    return privacy_service.is_excluded(
        ActiveWindow(
            app_name=str(activity.get("app_name") or ""),
            process_name=str(activity.get("process_name") or ""),
            window_title=str(activity.get("window_title") or ""),
            file_path_hint=file_path_hint,
        )
    )


def update_path_or_anonymize(activity_id: int, file_path_hint: str) -> bool:
    """Persist a safe path, or atomically redact the activity if it is excluded.

    Returns ``True`` when the activity was converted to the anonymous excluded
    representation. Privacy evaluation occurs before the path is written.
    Exceptions intentionally propagate so the collector fails closed.
    """
    if not (file_path_hint or "").strip():
        return False
    if not path_requires_exclusion(activity_id, file_path_hint):
        activity_service.update_activity_file_path_hint(activity_id, file_path_hint)
        return False
    anonymize_activity(activity_id)
    return True


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


__all__ = [
    "anonymize_activity",
    "path_requires_exclusion",
    "update_path_or_anonymize",
]
