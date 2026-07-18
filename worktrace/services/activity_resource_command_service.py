"""Command owner for activity path and resource-fact mutations."""

from __future__ import annotations

import logging
import ntpath

from ..constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED
from ..data_generation_repository import DataGenerationNamespace
from ..db import now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..path_utils import looks_like_local_file_path, normalize_path_key
from ..platforms.base import ActiveWindow
from ..resources.resource_builders import make_system_resource
from ..resources.types import DetectedResource
from . import activity_inference_job_repository, privacy_service
from .resource_service import create_or_update_activity_resource

logger = logging.getLogger(__name__)


def _detect_resource(activity: dict, file_path_hint: str) -> DetectedResource:
    status = str(activity.get("status") or "")
    if status in {STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR, STATUS_EXCLUDED}:
        return make_system_resource(
            status,
            str(activity.get("app_name") or ""),
            str(activity.get("process_name") or ""),
            str(activity.get("window_title") or ""),
        )
    from ..resources.detectors import detect_resource

    return detect_resource(
        ActiveWindow(
            app_name=str(activity.get("app_name") or ""),
            process_name=str(activity.get("process_name") or ""),
            window_title=str(activity.get("window_title") or ""),
            file_path_hint=file_path_hint,
            activity_start_time=str(activity.get("start_time") or "") or None,
        )
    )


def _upgrade_path_identity(
    resource: DetectedResource,
    existing: dict | None,
    file_path_hint: str,
) -> DetectedResource:
    if not looks_like_local_file_path(file_path_hint) or resource.path_hint:
        return resource
    if not existing:
        return resource

    existing_kind = str(existing.get("resource_kind") or "")
    existing_subtype = str(existing.get("resource_subtype") or "")
    existing_identity = str(existing.get("identity_key") or "")
    normalized = normalize_path_key(file_path_hint)
    kind = resource.resource_kind
    subtype = resource.resource_subtype
    identity = resource.identity_key

    if existing_kind == "office_document":
        kind, subtype, identity = existing_kind, existing_subtype, f"office_file:{normalized}"
    elif existing_kind == "ide_file":
        kind, subtype, identity = existing_kind, existing_subtype, f"ide_file:{normalized}"
    elif existing_kind == "email":
        kind, subtype, identity = existing_kind, existing_subtype, f"email_file:{normalized}"
    elif existing_kind == "local_file":
        kind, subtype, identity = existing_kind, existing_subtype, f"file_path:{normalized}"
    elif existing_identity.startswith(
        ("office_file_name:", "ide_file_name:", "email_file_name:", "file_name:")
    ):
        kind, subtype, identity = "local_file", "unknown", f"file_path:{normalized}"
    else:
        return resource

    return DetectedResource(
        resource_kind=kind,
        resource_subtype=subtype,
        display_name=ntpath.basename(file_path_hint) or resource.display_name,
        identity_key=identity,
        is_anchor=resource.is_anchor,
        confidence=resource.confidence,
        source=resource.source,
        app_name=resource.app_name,
        process_name=resource.process_name,
        window_title=resource.window_title,
        path_hint=file_path_hint,
        uri_scheme=resource.uri_scheme,
        uri_host=resource.uri_host,
        uri_hint=resource.uri_hint,
        metadata_json=resource.metadata_json,
    )


def _sync_open_activity_project_safely(activity_id: int) -> None:
    try:
        from .project_inference_service import sync_persisted_open_activity_project

        sync_persisted_open_activity_project(int(activity_id))
    except Exception:
        logger.exception("path open-row project sync failed activity_id=%s", activity_id)


def _persist_activity_path(
    activity_id: int,
    file_path_hint: str,
) -> tuple[bool, bool]:
    """Persist a path after transaction-snapshot privacy authorization."""

    cleaned = str(file_path_hint or "").strip()
    if not cleaned:
        return False, False

    activity_closed = False
    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        conn = uow.connection
        current_row = conn.execute(
            """
            SELECT id, app_name, process_name, window_title, status, start_time,
                   end_time, file_path_hint, updated_at
            FROM activity_log
            WHERE id = ? AND is_deleted = 0
            """,
            (int(activity_id),),
        ).fetchone()
        if current_row is None:
            return False, False
        activity = dict(current_row)
        current_resource_row = conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (int(activity_id),),
        ).fetchone()
        existing = dict(current_resource_row) if current_resource_row else None
        excluded = privacy_service.is_excluded(
            ActiveWindow(
                app_name=str(activity.get("app_name") or ""),
                process_name=str(activity.get("process_name") or ""),
                window_title=str(activity.get("window_title") or ""),
                file_path_hint=cleaned,
                activity_start_time=str(activity.get("start_time") or "") or None,
            ),
            conn=conn,
        )
        # Privacy evaluation may execute policy callbacks that change this row.
        # Re-read the authoritative status before any path or resource write.
        latest_row = conn.execute(
            """
            SELECT status, end_time
            FROM activity_log
            WHERE id = ? AND is_deleted = 0
            """,
            (int(activity_id),),
        ).fetchone()
        if latest_row is None:
            return False, False
        activity["status"] = latest_row["status"]
        activity["end_time"] = latest_row["end_time"]
        activity_closed = latest_row["end_time"] is not None
        status = str(latest_row["status"] or "")
        excluded = excluded or status == STATUS_EXCLUDED
        if excluded:
            payload = privacy_service.make_excluded_activity_payload()
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
            resource = make_system_resource(STATUS_EXCLUDED)
        else:
            resource = _upgrade_path_identity(
                _detect_resource(activity, cleaned),
                existing,
                cleaned,
            )

        conn.execute(
            """
            UPDATE activity_log
            SET file_path_hint = ?, updated_at = ?
            WHERE id = ?
              AND file_path_hint IS NOT ?
            """,
            (
                None if excluded else cleaned,
                now_str(),
                int(activity_id),
                None if excluded else cleaned,
            ),
        )
        create_or_update_activity_resource(int(activity_id), resource, conn=conn)

        if not excluded and activity_closed:
            activity_inference_job_repository.enqueue_closed_activity_ids(
                conn,
                [int(activity_id)],
            )
        uow.mark_changed()

    if not excluded and not activity_closed:
        _sync_open_activity_project_safely(int(activity_id))
    return True, excluded


def update_activity_file_path_hint(activity_id: int, file_path_hint: str) -> bool:
    """Atomically update path/resource facts and schedule derived state."""

    updated, _excluded = _persist_activity_path(activity_id, file_path_hint)
    return updated


def update_path_or_anonymize(activity_id: int, file_path_hint: str) -> bool:
    """Return whether the transaction converted the activity to excluded."""

    _updated, excluded = _persist_activity_path(activity_id, file_path_hint)
    return excluded


__all__ = ["update_activity_file_path_hint", "update_path_or_anonymize"]
