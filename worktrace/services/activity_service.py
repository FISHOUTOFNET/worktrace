from __future__ import annotations

from datetime import datetime
from typing import Any

from ..constants import (
    SOURCE_AUTO,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_NORMAL,
    TIME_FORMAT,
)
from ..activity_identity import attach_activity_identity
from ..db import dict_rows, get_connection, now_str
from ..platforms.base import ActiveWindow
from ..resources.types import DetectedResource
from .project_service import get_or_create_uncategorized_project
from .resource_service import attach_resource, create_or_update_activity_resource


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def _duration_seconds(start_time: str, end_time: str) -> tuple[int, bool]:
    seconds = int((_parse_time(end_time) - _parse_time(start_time)).total_seconds())
    if seconds < 0:
        return 0, True
    return seconds, False


def create_activity(
    app_name: str,
    process_name: str,
    window_title: str,
    status: str = STATUS_NORMAL,
    source: str = SOURCE_AUTO,
    start_time: str | None = None,
    project_id: int | None = None,
    file_path_hint: str | None = None,
    note: str | None = None,
    auto_classified: bool = False,
    manual_override: bool = False,
    resource: DetectedResource | None = None,
) -> int:
    ts = now_str()
    start = start_time or ts
    project = project_id if project_id is not None else get_or_create_uncategorized_project()
    manual_assignment = bool(manual_override or project_id is not None)
    with get_connection() as conn:
        open_rows = conn.execute("SELECT id FROM activity_log WHERE end_time IS NULL").fetchall()
        for row in open_rows:
            _close_activity_in_conn(conn, int(row["id"]), start)
        cur = conn.execute(
            """
            INSERT INTO activity_log(
                start_time, end_time, duration_seconds, app_name, process_name, window_title,
                file_path_hint, status, source, is_deleted, is_hidden,
                auto_classified, manual_override, project_id, note, created_at, updated_at
            )
            VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?, ?)
            """,
            (
                start,
                app_name,
                process_name,
                window_title,
                file_path_hint,
                status,
                source,
                int(auto_classified),
                int(manual_assignment),
                project,
                note,
                ts,
                ts,
            ),
        )
        activity_id = int(cur.lastrowid)
        assignment_source = "manual" if manual_assignment else "uncategorized"
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual, suggested_project_name, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
            ON CONFLICT(activity_id) DO NOTHING
            """,
            (
                activity_id,
                project,
                100 if manual_assignment else 0,
                assignment_source,
                int(manual_assignment),
                ts,
                ts,
            ),
        )
        _write_resource_in_conn(conn, activity_id, app_name, process_name, window_title, file_path_hint, status, resource, ts)
        return activity_id


def _close_activity_in_conn(conn, activity_id: int, end_time: str, duration_seconds: int | None = None) -> None:
    row = conn.execute(
        "SELECT start_time, status, duration_seconds FROM activity_log WHERE id = ?",
        (activity_id,),
    ).fetchone()
    if not row:
        return
    duration, is_error = _duration_seconds(row["start_time"], end_time)
    existing = int(row["duration_seconds"] or 0)
    if duration_seconds is not None:
        duration = max(duration, int(duration_seconds or 0))
    duration = max(existing, duration)
    status = STATUS_ERROR if is_error else row["status"]
    conn.execute(
        """
        UPDATE activity_log
        SET end_time = ?, duration_seconds = ?, status = ?, updated_at = ?
        WHERE id = ?
        """,
        (end_time, duration, status, now_str(), activity_id),
    )


def _write_resource_in_conn(
    conn,
    activity_id: int,
    app_name: str,
    process_name: str,
    window_title: str,
    file_path_hint: str | None,
    status: str,
    resource: DetectedResource | None,
    ts: str,
) -> None:
    from ..path_utils import normalize_path_key
    from ..resources.resource_policy import safe_metadata_json

    if resource is None:
        if status == STATUS_EXCLUDED:
            from ..constants import EXCLUDED_APP_NAME, EXCLUDED_PROCESS_NAME, EXCLUDED_WINDOW_TITLE
            resource = DetectedResource(
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
            )
        else:
            resource = _resource_from_activity_identity(
                app_name, process_name, window_title, file_path_hint, status,
            )
    path_key = normalize_path_key(resource.path_hint) if resource.path_hint else None
    metadata = safe_metadata_json(
        _parse_metadata_json(resource.metadata_json) if resource.metadata_json else None
    )
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


def _resource_from_activity_identity(
    app_name: str,
    process_name: str,
    window_title: str,
    file_path_hint: str | None,
    status: str,
) -> DetectedResource:
    from ..constants import STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR
    from ..resources.detectors import detect_resource

    if status == STATUS_IDLE:
        return DetectedResource(
            resource_kind="system", resource_subtype="idle",
            display_name="空闲", identity_key="system:idle",
            is_anchor=False, confidence=100, source="auto_idle",
            app_name=app_name, process_name=process_name, window_title=window_title,
        )
    if status == STATUS_PAUSED:
        return DetectedResource(
            resource_kind="system", resource_subtype="paused",
            display_name="已暂停", identity_key="system:paused",
            is_anchor=False, confidence=100, source="auto_paused",
            app_name=app_name, process_name=process_name, window_title=window_title,
        )
    if status == STATUS_ERROR:
        return DetectedResource(
            resource_kind="system", resource_subtype="error",
            display_name="异常", identity_key="system:error",
            is_anchor=False, confidence=100, source="auto_error",
            app_name=app_name, process_name=process_name, window_title=window_title,
        )

    active_window = ActiveWindow(
        app_name=app_name,
        process_name=process_name,
        window_title=window_title,
        file_path_hint=file_path_hint,
    )
    resource = detect_resource(active_window)

    # If the detector returned a non-generic result, use it directly
    if resource.resource_kind != "app" or resource.resource_subtype != "generic_app":
        return resource

    # Fall back to activity_identity for anchor file detection from title
    from ..activity_identity import infer_activity_identity
    identity = infer_activity_identity(app_name, process_name, window_title, file_path_hint)

    if identity.is_anchor_file:
        return DetectedResource(
            resource_kind="local_file",
            resource_subtype="unknown",
            display_name=identity.display_name,
            identity_key=identity.identity_key,
            is_anchor=True,
            confidence=80,
            source="activity_identity",
            app_name=identity.app_name or app_name,
            process_name=identity.process_name or process_name,
            window_title=identity.title_hint or window_title,
            path_hint=identity.full_path,
        )

    return resource


def _parse_metadata_json(value: str) -> dict | None:
    import json
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def close_activity(activity_id: int, end_time: str, duration_seconds: int | None = None) -> None:
    with get_connection() as conn:
        _close_activity_in_conn(conn, activity_id, end_time, duration_seconds=duration_seconds)


def close_current_open_record(end_time: str | None = None) -> None:
    end = end_time or now_str()
    with get_connection() as conn:
        rows = conn.execute("SELECT id FROM activity_log WHERE end_time IS NULL ORDER BY id").fetchall()
        for row in rows:
            _close_activity_in_conn(conn, int(row["id"]), end)


def increment_activity_duration(activity_id: int, seconds: int) -> None:
    seconds = max(0, int(seconds or 0))
    if seconds <= 0:
        return
    with get_connection() as conn:
        row = conn.execute(
            "SELECT duration_seconds FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not row:
            return
        duration = int(row["duration_seconds"] or 0) + seconds
        conn.execute(
            """
            UPDATE activity_log
            SET duration_seconds = ?, updated_at = ?
            WHERE id = ?
            """,
            (duration, now_str(), activity_id),
        )


def set_activity_duration(activity_id: int, seconds: int) -> None:
    seconds = max(0, int(seconds or 0))
    with get_connection() as conn:
        row = conn.execute(
            "SELECT duration_seconds FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not row:
            return
        duration = max(int(row["duration_seconds"] or 0), seconds)
        conn.execute(
            """
            UPDATE activity_log
            SET duration_seconds = ?, updated_at = ?
            WHERE id = ?
            """,
            (duration, now_str(), activity_id),
        )


def reopen_activity(activity_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE activity_log
            SET end_time = NULL, updated_at = ?
            WHERE id = ? AND is_deleted = 0
            """,
            (now_str(), activity_id),
        )


def get_latest_closed_auto_normal_activity(after_time: str | None = None) -> dict | None:
    time_clause = ""
    params: list[Any] = [STATUS_NORMAL, SOURCE_AUTO]
    if after_time:
        time_clause = "AND end_time > ?"
        params.append(after_time)
    with get_connection() as conn:
        row = conn.execute(
            f"""
            SELECT *
            FROM activity_log
            WHERE is_deleted = 0
              AND is_hidden = 0
              AND status = ?
              AND source = ?
              AND end_time IS NOT NULL
              {time_clause}
            ORDER BY end_time DESC, id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    return dict(row) if row else None


def get_open_activity() -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM activity_log WHERE end_time IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def _activity_select_sql(where: str) -> str:
    return f"""
        SELECT
            a.*,
            p.name AS project_name
        FROM activity_log a
        LEFT JOIN project p ON p.id = a.project_id
        WHERE {where}
        ORDER BY a.start_time DESC, a.id DESC
    """


def get_activities_by_date(date: str) -> list[dict]:
    return get_activities_by_range(date, date)


def get_activities_by_range(start_date: str, end_date: str) -> list[dict]:
    start = f"{start_date} 00:00:00"
    end = f"{end_date} 23:59:59"
    with get_connection() as conn:
        rows = conn.execute(
            _activity_select_sql("a.is_deleted = 0 AND a.start_time BETWEEN ? AND ?"),
            (start, end),
        ).fetchall()
    return [attach_resource(row) for row in dict_rows(rows)]


def get_activity(activity_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(_activity_select_sql("a.id = ?"), (activity_id,)).fetchone()
    return attach_resource(dict(row)) if row else None


def activity_display_name(activity: dict) -> str:
    name = activity.get("resource_display_name") or activity.get("activity_display_name")
    if name:
        return str(name).strip()
    return attach_resource(activity)["activity_display_name"]


def update_activity_project(activity_id: int, project_id: int, manual: bool = True) -> None:
    update_activities_project([activity_id], project_id, manual=manual)


def update_activity_file_path_hint(activity_id: int, file_path_hint: str) -> None:
    if not (file_path_hint or "").strip():
        return
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET file_path_hint = ?, updated_at = ? WHERE id = ?",
            (file_path_hint, now_str(), activity_id),
        )
    from .project_inference_service import assign_project_for_activity

    assign_project_for_activity(activity_id)


def update_activities_project(activity_ids: list[int], project_id: int, manual: bool = True) -> None:
    if not activity_ids:
        return
    ts = now_str()
    placeholders = ",".join("?" for _ in activity_ids)
    source = "manual" if manual else "anchor_context"
    confidence = 100 if manual else 60
    with get_connection() as conn:
        conn.execute(
            f"""
            UPDATE activity_log
            SET project_id = ?,
                manual_override = CASE WHEN ? = 1 THEN 1 ELSE manual_override END,
                updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [project_id, int(manual), ts, *activity_ids],
        )
        for activity_id in activity_ids:
            conn.execute(
                """
                INSERT INTO activity_project_assignment(
                    activity_id, project_id, confidence, source, is_manual, suggested_project_name, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    is_manual = excluded.is_manual,
                    suggested_project_name = excluded.suggested_project_name,
                    updated_at = excluded.updated_at
                """,
                (activity_id, project_id, confidence, source, int(manual), None, ts, ts),
            )


def apply_midnight_anchor_assignment(activity_id: int, project_id: int) -> None:
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE activity_log
            SET project_id = ?,
                auto_classified = 1,
                manual_override = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (project_id, ts, activity_id),
        )
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual, suggested_project_name, created_at, updated_at
            )
            VALUES (?, ?, 90, 'midnight_anchor', 0, NULL, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                project_id = excluded.project_id,
                confidence = excluded.confidence,
                source = excluded.source,
                is_manual = 0,
                suggested_project_name = NULL,
                updated_at = excluded.updated_at
            """,
            (activity_id, project_id, ts, ts),
        )


def finalize_created_activity(activity_id: int) -> None:
    from .project_inference_service import process_new_activity

    process_new_activity(activity_id)


def update_activity_note(activity_id: int, note: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET note = ?, source = 'manual', updated_at = ? WHERE id = ?",
            (note, now_str(), activity_id),
        )


def soft_delete_activity(activity_id: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET is_deleted = 1, updated_at = ? WHERE id = ?",
            (now_str(), activity_id),
        )


def update_activity_fields(activity_id: int, **fields: Any) -> None:
    if not fields:
        return
    allowed = {
        "status",
        "source",
        "is_hidden",
        "auto_classified",
        "manual_override",
        "project_id",
        "note",
    }
    items = [(key, value) for key, value in fields.items() if key in allowed]
    if not items:
        return
    sql = ", ".join(f"{key} = ?" for key, _ in items)
    values = [value for _, value in items]
    values.extend([now_str(), activity_id])
    with get_connection() as conn:
        conn.execute(f"UPDATE activity_log SET {sql}, updated_at = ? WHERE id = ?", values)
