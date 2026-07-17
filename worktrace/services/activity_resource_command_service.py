"""Command owner for activity path and resource-fact mutations."""

from __future__ import annotations

import logging
import ntpath

from ..constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED
from ..data_generation_repository import DataGenerationNamespace
from ..db import get_connection, now_str
from ..domain_unit_of_work import DomainUnitOfWork
from ..path_utils import looks_like_local_file_path, normalize_path_key
from ..platforms.base import ActiveWindow
from ..resources.resource_builders import make_system_resource
from ..resources.types import DetectedResource
from .resource_service import create_or_update_activity_resource

logger = logging.getLogger(__name__)

_ACTIVITY_REVISION_FIELDS = (
    "id",
    "app_name",
    "process_name",
    "window_title",
    "status",
    "start_time",
    "file_path_hint",
    "updated_at",
)
_RESOURCE_REVISION_FIELDS = (
    "resource_kind",
    "resource_subtype",
    "display_name",
    "identity_key",
    "is_anchor",
    "path_hint",
    "updated_at",
)


def _revision(row: dict | None, fields: tuple[str, ...]) -> tuple | None:
    if row is None:
        return None
    return tuple(row.get(field) for field in fields)


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


def _finalize_pending_inference(activity_id: int) -> None:
    """Run post-commit derivation without changing the main command result."""

    try:
        from .project_inference_service import assign_project_for_activity

        assign_project_for_activity(int(activity_id))
    except Exception:
        # The durable path/resource facts and their retry marker already
        # committed. The opportunity worker can retry without the caller being
        # told that the main command failed.
        logger.exception("path-update inference failed for activity_id=%s", activity_id)


def update_activity_file_path_hint(activity_id: int, file_path_hint: str) -> bool:
    """Atomically update path/resource facts and persist pending derivation."""

    cleaned = str(file_path_hint or "").strip()
    if not cleaned:
        return False
    with get_connection() as read_conn:
        row = read_conn.execute(
            """
            SELECT id, app_name, process_name, window_title, status, start_time,
                   file_path_hint, updated_at
            FROM activity_log
            WHERE id = ? AND is_deleted = 0
            """,
            (int(activity_id),),
        ).fetchone()
        if row is None:
            return False
        activity = dict(row)
        existing_row = read_conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (int(activity_id),),
        ).fetchone()
        existing = dict(existing_row) if existing_row else None

    expected_activity_revision = _revision(activity, _ACTIVITY_REVISION_FIELDS)
    expected_resource_revision = _revision(existing, _RESOURCE_REVISION_FIELDS)
    status = str(activity.get("status") or "")
    effective_path = None if status == STATUS_EXCLUDED else cleaned
    resource = _detect_resource(activity, cleaned)
    if status != STATUS_EXCLUDED:
        resource = _upgrade_path_identity(resource, existing, cleaned)

    with DomainUnitOfWork((DataGenerationNamespace.REPORT_STRUCTURE,)) as uow:
        conn = uow.connection
        current_row = conn.execute(
            """
            SELECT id, app_name, process_name, window_title, status, start_time,
                   file_path_hint, updated_at
            FROM activity_log
            WHERE id = ? AND is_deleted = 0
            """,
            (int(activity_id),),
        ).fetchone()
        if current_row is None:
            return False
        current = dict(current_row)
        current_resource_row = conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (int(activity_id),),
        ).fetchone()
        current_resource = dict(current_resource_row) if current_resource_row else None
        if (
            _revision(current, _ACTIVITY_REVISION_FIELDS) != expected_activity_revision
            or _revision(current_resource, _RESOURCE_REVISION_FIELDS)
            != expected_resource_revision
        ):
            raise ValueError("activity_changed_during_path_update")

        conn.execute(
            """
            UPDATE activity_log
            SET file_path_hint = ?, updated_at = ?
            WHERE id = ?
              AND file_path_hint IS NOT ?
            """,
            (effective_path, now_str(), int(activity_id), effective_path),
        )
        create_or_update_activity_resource(int(activity_id), resource, conn=conn)

        from .assignment_command_service import mark_inference_retry
        from .system_project_service import require_uncategorized_project_id

        mark_inference_retry(
            conn,
            int(activity_id),
            require_uncategorized_project_id(conn),
        )
        uow.mark_changed()

    _finalize_pending_inference(int(activity_id))
    return True


__all__ = ["update_activity_file_path_hint"]
