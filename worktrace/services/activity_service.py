from __future__ import annotations

from datetime import datetime
from typing import Any

from ..constants import (
    SOURCE_AUTO,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)
from ..db import dict_rows, get_connection, now_str
from ..platforms.base import ActiveWindow
from ..resources.resource_builders import make_system_resource
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
        _write_resource_in_conn(conn, activity_id, app_name, process_name, window_title, file_path_hint, status, resource, start)
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
    start_time: str | None = None,
) -> None:
    # Excluded activities: let resource_service's anonymisation safety net
    # handle them — never persist real resource metadata.
    if resource is None and status != STATUS_EXCLUDED:
        resource = _detect_resource_for_activity(
            app_name, process_name, window_title, file_path_hint, status, start_time,
        )
    create_or_update_activity_resource(activity_id, resource, conn=conn)


def _detect_resource_for_activity(
    app_name: str,
    process_name: str,
    window_title: str,
    file_path_hint: str | None,
    status: str,
    start_time: str | None = None,
) -> DetectedResource:
    """Build a DetectedResource for a new activity using resource-first detection."""
    from ..resources.detectors import detect_resource

    if status in (STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR):
        return make_system_resource(status, app_name, process_name, window_title)

    active_window = ActiveWindow(
        app_name=app_name,
        process_name=process_name,
        window_title=window_title,
        file_path_hint=file_path_hint,
        activity_start_time=start_time,
    )
    return detect_resource(active_window)


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
        _sync_activity_resource_after_path_update(conn, activity_id, file_path_hint)
    from .project_inference_service import assign_project_for_activity

    assign_project_for_activity(activity_id)


def _sync_activity_resource_after_path_update(conn, activity_id: int, file_path_hint: str) -> None:
    """Re-infer the resource after a path hint update and sync activity_resource.

    When a real full path becomes available for an activity that previously only
    had a name-only resource (e.g. ``合同.docx`` from the window title), we
    re-run detection and upgrade the stored resource so that path-based
    identity keys, ``path_hint`` and ``path_key`` are populated. Excluded
    activities keep their anonymous resource.
    """
    from ..path_utils import normalize_path_key

    row = conn.execute(
        "SELECT app_name, process_name, window_title, status FROM activity_log WHERE id = ?",
        (activity_id,),
    ).fetchone()
    if not row:
        return
    status = row["status"]
    if status == STATUS_EXCLUDED:
        # Excluded activities always keep their anonymous resource; never
        # persist a real path even when one becomes available.
        return

    existing = conn.execute(
        "SELECT resource_kind, resource_subtype, identity_key FROM activity_resource WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if not existing:
        # No existing resource row; create_activity will handle it.
        return

    # Re-infer the resource using the updated file_path_hint.
    resource = _detect_resource_for_activity(
        row["app_name"], row["process_name"], row["window_title"], file_path_hint, status,
        row["start_time"],
    )

    new_path_hint = resource.path_hint
    new_identity_key = resource.identity_key
    new_display_name = resource.display_name
    new_kind = resource.resource_kind
    new_subtype = resource.resource_subtype

    # If detection still produced a name-only identity (no path_hint), but we
    # now have a real local file path, upgrade to a path-based identity so
    # that the stored resource reflects the newly-available path. We keep the
    # existing resource kind/subtype when the detector didn't surface a file
    # (e.g. generic app) so that we don't accidentally downgrade a previously
    # classified resource.
    from ..path_utils import looks_like_local_file_path

    if looks_like_local_file_path(file_path_hint) and not new_path_hint:
        existing_kind = existing["resource_kind"]
        existing_subtype = existing["resource_subtype"]
        existing_identity = existing["identity_key"] or ""
        normalized = normalize_path_key(file_path_hint)
        # Determine the appropriate identity key prefix. Prefer the existing
        # resource kind when it is file-like; otherwise fall back to local_file.
        if existing_kind == "office_document":
            new_identity_key = f"office_file:{normalized}"
            new_kind = existing_kind
            new_subtype = existing_subtype
        elif existing_kind == "ide_file":
            new_identity_key = f"ide_file:{normalized}"
            new_kind = existing_kind
            new_subtype = existing_subtype
        elif existing_kind == "email":
            new_identity_key = f"email_file:{normalized}"
            new_kind = existing_kind
            new_subtype = existing_subtype
        elif existing_kind == "local_file":
            new_identity_key = f"file_path:{normalized}"
            new_kind = existing_kind
            new_subtype = existing_subtype
        elif existing_identity.startswith(("office_file_name:", "ide_file_name:", "email_file_name:", "file_name:")):
            # Name-only file-like resource that detection didn't re-classify;
            # upgrade to a path-based local_file identity.
            new_identity_key = f"file_path:{normalized}"
            new_kind = "local_file"
            new_subtype = "unknown"
        else:
            # Generic app or other kind: don't force a file identity if
            # detection didn't find one.
            new_path_hint = None
        if new_path_hint is not None:
            new_path_hint = file_path_hint
            import ntpath as _ntpath
            new_display_name = _ntpath.basename(file_path_hint) or new_display_name

    path_key = normalize_path_key(new_path_hint) if new_path_hint else None
    conn.execute(
        """
        UPDATE activity_resource
        SET path_hint = ?,
            path_key = ?,
            identity_key = ?,
            display_name = ?,
            resource_kind = ?,
            resource_subtype = ?,
            updated_at = ?
        WHERE activity_id = ?
        """,
        (
            new_path_hint,
            path_key,
            new_identity_key,
            new_display_name,
            new_kind,
            new_subtype,
            now_str(),
            activity_id,
        ),
    )


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
