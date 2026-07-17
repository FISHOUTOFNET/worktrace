from __future__ import annotations

import sqlite3

from ..constants import STATUS_EXCLUDED
from ..db import get_connection, now_str
from ..mutation_effects import report_structure_mutation
from ..path_utils import normalize_path_key
from ..resources.resource_builders import make_system_resource, parse_metadata_json
from ..resources.resource_policy import safe_metadata_json
from ..resources.types import DetectedResource


@report_structure_mutation
def create_or_update_activity_resource(
    activity_id: int,
    resource: DetectedResource,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Persist one resource, avoiding writes when semantic fields are unchanged."""

    resource = _enforce_anonymous_if_excluded(activity_id, resource, conn)
    ts = now_str()
    path_key = normalize_path_key(resource.path_hint) if resource.path_hint else None
    metadata = safe_metadata_json(parse_metadata_json(resource.metadata_json))

    def _upsert(c: sqlite3.Connection) -> None:
        c.execute(
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
            WHERE activity_resource.resource_kind IS NOT excluded.resource_kind
               OR activity_resource.resource_subtype IS NOT excluded.resource_subtype
               OR activity_resource.display_name IS NOT excluded.display_name
               OR activity_resource.identity_key IS NOT excluded.identity_key
               OR activity_resource.is_anchor IS NOT excluded.is_anchor
               OR activity_resource.confidence IS NOT excluded.confidence
               OR activity_resource.source IS NOT excluded.source
               OR activity_resource.app_name IS NOT excluded.app_name
               OR activity_resource.process_name IS NOT excluded.process_name
               OR activity_resource.window_title IS NOT excluded.window_title
               OR activity_resource.path_hint IS NOT excluded.path_hint
               OR activity_resource.path_key IS NOT excluded.path_key
               OR activity_resource.uri_scheme IS NOT excluded.uri_scheme
               OR activity_resource.uri_host IS NOT excluded.uri_host
               OR activity_resource.uri_hint IS NOT excluded.uri_hint
               OR activity_resource.metadata_json IS NOT excluded.metadata_json
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

    if conn is not None:
        _upsert(conn)
    else:
        with get_connection() as own_conn:
            _upsert(own_conn)


def get_resource_for_activity(
    activity_id: int,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict | None:
    if conn is not None:
        row = conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        return dict(row) if row else None
    with get_connection() as read_conn:
        row = read_conn.execute(
            "SELECT * FROM activity_resource WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
    return dict(row) if row else None


def attach_resource(
    row: dict,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Attach only persisted resource facts to an activity row."""

    item = dict(row)
    activity_id = item.get("id")
    if activity_id is None:
        return item
    resource = get_resource_for_activity(int(activity_id), conn=conn)
    if resource is None:
        item["resource_kind"] = "unknown"
        item["resource_subtype"] = "unknown"
        item["resource_display_name"] = (
            item.get("app_name") or item.get("process_name") or "未知"
        )
        item["resource_identity_key"] = f"activity:{int(activity_id)}"
        item["resource_is_anchor"] = False
        item["resource_path_hint"] = None
        item["resource_uri_host"] = None
    else:
        item["resource_kind"] = resource["resource_kind"]
        item["resource_subtype"] = resource["resource_subtype"]
        item["resource_display_name"] = resource["display_name"]
        item["resource_identity_key"] = resource["identity_key"]
        item["resource_is_anchor"] = bool(resource["is_anchor"])
        item["resource_path_hint"] = resource.get("path_hint")
        item["resource_uri_host"] = resource.get("uri_host")
    item["activity_display_name"] = (
        item.get("resource_display_name") or item.get("app_name", "")
    )
    item["activity_identity_key"] = item.get("resource_identity_key") or ""
    return item


def _enforce_anonymous_if_excluded(
    activity_id: int,
    resource: DetectedResource,
    conn: sqlite3.Connection | None = None,
) -> DetectedResource:
    """Return an anonymous excluded resource for excluded activities."""

    def _get_status(connection) -> str | None:
        row = connection.execute(
            "SELECT status FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        return row["status"] if row else None

    if conn is not None:
        status = _get_status(conn)
    else:
        with get_connection() as own_conn:
            status = _get_status(own_conn)

    if status != STATUS_EXCLUDED:
        return resource
    return make_system_resource(STATUS_EXCLUDED)
