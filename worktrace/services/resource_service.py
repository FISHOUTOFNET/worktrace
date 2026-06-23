from __future__ import annotations

from ..constants import EXCLUDED_APP_NAME, EXCLUDED_PROCESS_NAME, EXCLUDED_WINDOW_TITLE, STATUS_EXCLUDED
from ..db import get_connection, now_str
from ..path_utils import normalize_path_key
from ..resources.resource_policy import safe_metadata_json
from ..resources.types import DetectedResource


def create_or_update_activity_resource(activity_id: int, resource: DetectedResource) -> None:
    # Security: if the activity's status is excluded, always force an anonymous
    # resource regardless of what the caller passed in. This prevents real
    # resource metadata from being persisted for excluded activities.
    resource = _enforce_anonymous_if_excluded(activity_id, resource)
    ts = now_str()
    path_key = normalize_path_key(resource.path_hint) if resource.path_hint else None
    metadata = safe_metadata_json(
        _parse_metadata_json(resource.metadata_json) if resource.metadata_json else None
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO activity_resource(
                activity_id, resource_kind, resource_subtype, display_name, identity_key,
                is_anchor, confidence, source, app_name, process_name, window_title,
                path_hint, path_key, uri_scheme, uri_host, uri_hint, metadata_json,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                resource_kind = excluded.resource_kind,
                resource_subtype = excluded.resource_subtype,
                display_name = excluded.display_name,
                identity_key = excluded.identity_key,
                is_anchor = excluded.is_anchor,
                confidence = excluded.confidence,
                source = excluded.source,
                app_name = excluded.app_name,
                process_name = excluded.process_name,
                window_title = excluded.window_title,
                path_hint = excluded.path_hint,
                path_key = excluded.path_key,
                uri_scheme = excluded.uri_scheme,
                uri_host = excluded.uri_host,
                uri_hint = excluded.uri_hint,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            (
                activity_id,
                resource.resource_kind,
                resource.resource_subtype,
                resource.display_name,
                resource.identity_key,
                int(resource.is_anchor),
                resource.confidence,
                resource.source,
                resource.app_name,
                resource.process_name,
                resource.window_title,
                resource.path_hint,
                path_key,
                resource.uri_scheme,
                resource.uri_host,
                resource.uri_hint,
                metadata,
                ts,
                ts,
            ),
        )


def get_resource_for_activity(activity_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return dict(row) if row else None


def attach_resource(row: dict) -> dict:
    item = dict(row)
    activity_id = item.get("id")
    if activity_id is None:
        return item
    resource = get_resource_for_activity(int(activity_id))
    if resource is not None:
        item["resource_kind"] = resource["resource_kind"]
        item["resource_subtype"] = resource["resource_subtype"]
        item["resource_display_name"] = resource["display_name"]
        item["resource_identity_key"] = resource["identity_key"]
        item["resource_is_anchor"] = bool(resource["is_anchor"])
        item["resource_path_hint"] = resource.get("path_hint")
        item["resource_uri_host"] = resource.get("uri_host")
        # Derive legacy path fields from resource path_hint
        path_hint = resource.get("path_hint")
        if path_hint:
            from ..path_utils import split_file_path
            full_path, parent_dir, file_stem = split_file_path(path_hint)
            item["anchor_parent_dir"] = parent_dir
            item["anchor_file_stem"] = file_stem
            item["anchor_title_hint"] = resource.get("display_name") or ""
        else:
            item["anchor_parent_dir"] = ""
            item["anchor_file_stem"] = ""
            item["anchor_title_hint"] = resource.get("display_name") or ""
    else:
        from ..activity_identity import attach_activity_identity
        item = attach_activity_identity(item)
    item["activity_display_name"] = item.get("resource_display_name") or item.get("activity_display_name") or item.get("app_name", "")
    item["activity_identity_key"] = item.get("resource_identity_key") or item.get("activity_identity_key") or ""
    item["is_anchor_file"] = item.get("resource_is_anchor") if item.get("resource_is_anchor") is not None else item.get("is_anchor_file", False)
    item["anchor_full_path"] = item.get("resource_path_hint") or item.get("anchor_full_path") or ""
    return item


def backfill_missing_resources() -> int:
    count = 0
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.app_name, a.process_name, a.window_title,
                   a.file_path_hint, a.status
            FROM activity_log a
            LEFT JOIN activity_resource r ON r.activity_id = a.id
            WHERE r.id IS NULL
            ORDER BY a.id
            """
        ).fetchall()
    for row in rows:
        activity = dict(row)
        if activity.get("status") == STATUS_EXCLUDED:
            resource = DetectedResource(
                resource_kind="system",
                resource_subtype="excluded",
                display_name=EXCLUDED_APP_NAME,
                identity_key="system:excluded",
                is_anchor=False,
                confidence=100,
                source="backfill_excluded",
                app_name=EXCLUDED_APP_NAME,
                process_name=EXCLUDED_PROCESS_NAME,
                window_title=EXCLUDED_WINDOW_TITLE,
            )
        else:
            from ..services.activity_service import _resource_from_activity_identity
            resource = _resource_from_activity_identity(
                activity.get("app_name", ""),
                activity.get("process_name", ""),
                activity.get("window_title", ""),
                activity.get("file_path_hint"),
                activity.get("status", "normal"),
            )
        create_or_update_activity_resource(int(activity["id"]), resource)
        count += 1
    return count


def _enforce_anonymous_if_excluded(activity_id: int, resource: DetectedResource) -> DetectedResource:
    """Return an anonymous excluded resource if the activity is excluded.

    This is a safety net: even if a caller passes a real resource, we never
    persist real resource metadata for an excluded activity.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
    if not row or row["status"] != STATUS_EXCLUDED:
        return resource
    return DetectedResource(
        resource_kind="system",
        resource_subtype="excluded",
        display_name=EXCLUDED_APP_NAME,
        identity_key="system:excluded",
        is_anchor=False,
        confidence=100,
        source="auto_excluded",
        app_name=EXCLUDED_APP_NAME,
        process_name=EXCLUDED_PROCESS_NAME,
        window_title=EXCLUDED_WINDOW_TITLE,
        path_hint=None,
        uri_scheme=None,
        uri_host=None,
        uri_hint=None,
        metadata_json=None,
    )


def _parse_metadata_json(value: str) -> dict | None:
    import json
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None
