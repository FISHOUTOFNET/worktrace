from __future__ import annotations

import logging
import hashlib
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
    UNCATEGORIZED_PROJECT,
)
from ..db import dict_rows, get_connection, now_str
from ..formatters import format_activity_project_cell, format_status_label
from ..platforms.base import ActiveWindow
from ..resources.resource_builders import make_system_resource
from ..resources.types import DetectedResource
from .activity_edit_policy import is_project_editable_activity, require_project_editable_activity
from .project_attribution_policy import official_project_fields
from .project_service import get_or_create_uncategorized_project
from .resource_service import attach_resource, create_or_update_activity_resource


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, TIME_FORMAT)


def _duration_seconds(start_time: str, end_time: str) -> tuple[int, bool]:
    seconds = int((_parse_time(end_time) - _parse_time(start_time)).total_seconds())
    if seconds < 0:
        return 0, True
    return seconds, False


def insert_activity_row(
    app_name: str,
    process_name: str,
    window_title: str,
    status: str = STATUS_NORMAL,
    source: str = SOURCE_AUTO,
    start_time: str | None = None,
    project_id: int | None = None,
    file_path_hint: str | None = None,
    resource: DetectedResource | None = None,
    **_ignored,
) -> int:
    """Low-level insert of a new open activity row.

    This is a pure CRUD helper: it does NOT close pre-existing open rows
    and does NOT run project inference / automatic rules. Production
    open-row lifecycle must use ``activity_lifecycle_service`` (the
    ActivityLifecycle Command Facade). Tests / fixtures may use this
    helper to construct data directly.
    """
    ts = now_str()
    start = start_time or ts
    project = project_id if project_id is not None else get_or_create_uncategorized_project()
    manual_assignment = bool(project_id is not None)
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO activity_log(
                start_time, end_time, duration_seconds, app_name, process_name, window_title,
                file_path_hint, status, source, is_deleted, is_hidden, created_at, updated_at
            )
            VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
            """,
            (
                start,
                app_name,
                process_name,
                window_title,
                file_path_hint,
                status,
                source,
                ts,
                ts,
            ),
        )
        activity_id = int(cur.lastrowid)
        assignment_source = "manual" if manual_assignment else "uncategorized"
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual, suggested_project_name,
                source_rule_type, source_rule_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?)
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


def close_activity_row(
    activity_id: int,
    end_time: str,
    *,
    duration_seconds: int | None = None,
    status: str | None = None,
) -> None:
    """Low-level close of a single open activity row.

    Pure CRUD: does NOT run project inference / automatic rules. Production
    open-row lifecycle must use ``activity_lifecycle_service.close_activity``
    which calls this helper and then finalizes. Tests / fixtures may use
    this helper directly.
    """
    with get_connection() as conn:
        _close_activity_in_conn(conn, activity_id, end_time, duration_seconds=duration_seconds, status=status)


def close_all_open_rows(end_time: str | None = None) -> list[int]:
    """Low-level close of every open activity row (``end_time IS NULL``).

    Pure CRUD: does NOT run project inference / automatic rules. Returns
    the list of closed activity ids so the caller (typically
    ``activity_lifecycle_service``) can finalize them outside the
    transaction. Production open-row lifecycle must use
    ``activity_lifecycle_service.close_all_open_activities``.
    """
    end = end_time or now_str()
    closed_ids: list[int] = []
    with get_connection() as conn:
        rows = conn.execute("SELECT id FROM activity_log WHERE end_time IS NULL ORDER BY id").fetchall()
        for row in rows:
            aid = int(row["id"])
            _close_activity_in_conn(conn, aid, end)
            closed_ids.append(aid)
    return closed_ids


def create_activity(
    app_name: str,
    process_name: str,
    window_title: str,
    status: str = STATUS_NORMAL,
    source: str = SOURCE_AUTO,
    start_time: str | None = None,
    project_id: int | None = None,
    file_path_hint: str | None = None,
    resource: DetectedResource | None = None,
    **_ignored,
) -> int:
    """Low-level insert of a new open activity row.

    .. warning::

        This is a **low-level CRUD helper**. It does NOT close pre-existing
        open rows and does NOT run project inference / automatic rules.
        Production open-row lifecycle must use
        ``activity_lifecycle_service`` (the ActivityLifecycle Command
        Facade). Tests / fixtures may use this helper to construct data
        directly.

    Equivalent to :func:`insert_activity_row`.
    """
    return insert_activity_row(
        app_name=app_name,
        process_name=process_name,
        window_title=window_title,
        status=status,
        source=source,
        start_time=start_time,
        project_id=project_id,
        file_path_hint=file_path_hint,
        resource=resource,
    )


def _close_activity_in_conn(
    conn,
    activity_id: int,
    end_time: str,
    duration_seconds: int | None = None,
    status: str | None = None,
) -> None:
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
    if status is None:
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
    """Low-level close of a single open activity row.

    Pure CRUD: does NOT run project inference / automatic rules.
    Production open-row lifecycle must use
    ``activity_lifecycle_service.close_activity`` which calls this helper
    and then finalizes. Tests / fixtures may use this helper directly.
    """
    close_activity_row(activity_id, end_time, duration_seconds=duration_seconds)


def increment_activity_duration(activity_id: int, seconds: int) -> None:
    """Increment an open activity row's ``duration_seconds``.

    This write is a *natural growth* update on an open row — the
    duration is derived from ``now - start_time`` and is NOT a
    structural change. The ``updated_at`` column is therefore NOT
    bumped, so the page revision (which excludes
    ``updated_at`` from the per-row structural signature) does not
    trigger a heavy refresh on every collector tick.
    on every collector tick.

    A subsequent structural write (close, project edit, time edit, etc.)
    will refresh ``updated_at`` as usual.
    """
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
            SET duration_seconds = ?
            WHERE id = ?
            """,
            (duration, activity_id),
        )


def set_activity_duration(activity_id: int, seconds: int) -> None:
    """Set an open activity row's ``duration_seconds`` (monotonic max).

    This write is a *natural growth* update on an open row — the
    duration is derived from ``now - start_time`` and is NOT a
    structural change. The ``updated_at`` column is therefore NOT
    bumped, so the page revision (which excludes
    ``updated_at`` from the per-row structural signature) does not
    trigger a heavy refresh on every collector tick.
    on every collector tick.

    A subsequent structural write (close, project edit, time edit, etc.)
    will refresh ``updated_at`` as usual.
    """
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
            SET duration_seconds = ?
            WHERE id = ?
            """,
            (duration, activity_id),
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
            _activity_select_sql("a.end_time IS NULL").replace(
                "ORDER BY a.start_time DESC, a.id DESC",
                "ORDER BY a.id DESC LIMIT 1",
            )
        ).fetchone()
    if not row:
        return None
    return _attach_attribution_fields(dict(row), get_or_create_uncategorized_project())


def _activity_select_sql(where: str) -> str:
    return f"""
        SELECT
            a.*,
            pe.name AS project_name,
            apa.source AS assignment_source,
            apa.is_manual AS assignment_is_manual,
            apa.suggested_project_name,
            apa.project_id AS effective_project_id,
            pe.name AS effective_project_name,
            pe.description AS effective_project_description
        FROM activity_log a
        LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
        LEFT JOIN project pe ON pe.id = apa.project_id
        WHERE {where}
        ORDER BY a.start_time DESC, a.id DESC
    """


def get_activities_by_date(date: str) -> list[dict]:
    """Return CRUD / official-display-only activity rows for one date.

    Do not use this helper for Timeline / Statistics / Export /
    report-visible project projection. Reporting surfaces must use
    ``timeline_service.get_report_activity_rows`` or
    ``timeline_service.get_project_sessions_by_range``.
    """
    return get_activities_by_range(date, date)


def get_activity_structure_marker_by_date(date: str) -> dict:
    """Return a lightweight structural marker for a report date.

    This helper is intentionally SQL-only and does not attach activity
    resources. It is suitable for heartbeat revision checks where duration
    growth should not force the heavy page ViewModel to reload.
    """
    start = f"{date} 00:00:00"
    end = f"{date} 23:59:59"
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS row_count,
                SUM(CASE WHEN is_deleted = 0 THEN 1 ELSE 0 END) AS visible_row_count,
                COALESCE(MAX(id), 0) AS max_id,
                COALESCE(MAX(CASE WHEN end_time IS NOT NULL THEN updated_at ELSE '' END), '') AS closed_max_updated_at,
                COALESCE(MAX(updated_at), '') AS max_updated_at,
                SUM(CASE WHEN end_time IS NULL AND is_deleted = 0 THEN 1 ELSE 0 END) AS open_row_count,
                COALESCE(MAX(CASE WHEN end_time IS NULL AND is_deleted = 0 THEN id ELSE 0 END), 0) AS open_max_id,
                COALESCE(MAX(CASE WHEN end_time IS NULL AND is_deleted = 0 THEN updated_at ELSE '' END), '') AS open_max_updated_at,
                COALESCE(MAX(CASE WHEN end_time IS NULL AND is_deleted = 0 THEN COALESCE(end_time, '') ELSE '' END), '') AS open_end_time_presence,
                SUM(CASE WHEN is_hidden != 0 THEN 1 ELSE 0 END) AS hidden_count,
                SUM(CASE WHEN is_deleted != 0 THEN 1 ELSE 0 END) AS deleted_count
            FROM activity_log
            WHERE start_time BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchone()
        signature_row = conn.execute(
            """
            SELECT COALESCE(GROUP_CONCAT(sig, '#'), '') AS structural_signature
            FROM (
                SELECT
                    id || '|' ||
                    COALESCE(start_time, '') || '|' ||
                    CASE WHEN end_time IS NULL THEN '1' ELSE '0' END || '|' ||
                    COALESCE(end_time, '') || '|' ||
                    COALESCE(status, '') || '|' ||
                    COALESCE(assignment_project_id, 0) || '|' ||
                    COALESCE(assignment_source, '') || '|' ||
                    COALESCE(assignment_is_manual, 0) || '|' ||
                    COALESCE(assignment_updated_at, '') || '|' ||
                    COALESCE(source, '') || '|' ||
                    COALESCE(is_deleted, 0) || '|' ||
                    COALESCE(is_hidden, 0) AS sig
                FROM (
                    SELECT
                        a.id,
                        a.start_time,
                        a.end_time,
                        a.status,
                        a.source,
                        a.is_deleted,
                        a.is_hidden,
                        apa.project_id AS assignment_project_id,
                        apa.source AS assignment_source,
                        apa.is_manual AS assignment_is_manual,
                        apa.updated_at AS assignment_updated_at
                    FROM activity_log a
                    LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
                    WHERE a.start_time BETWEEN ? AND ?
                    ORDER BY a.id
                )
            )
            """,
            (start, end),
        ).fetchone()
    if not row:
        return {
            "row_count": 0,
            "visible_row_count": 0,
            "max_id": 0,
            "closed_max_updated_at": "",
            "max_updated_at": "",
            "open_row_count": 0,
            "open_max_id": 0,
            "open_max_updated_at": "",
            "open_end_time_presence": "",
            "hidden_count": 0,
            "deleted_count": 0,
            "structural_signature": "",
        }
    return {
        "row_count": int(row["row_count"] or 0),
        "visible_row_count": int(row["visible_row_count"] or 0),
        "max_id": int(row["max_id"] or 0),
        "closed_max_updated_at": str(row["closed_max_updated_at"] or ""),
        "max_updated_at": str(row["max_updated_at"] or ""),
        "open_row_count": int(row["open_row_count"] or 0),
        "open_max_id": int(row["open_max_id"] or 0),
        "open_max_updated_at": str(row["open_max_updated_at"] or ""),
        "open_end_time_presence": str(row["open_end_time_presence"] or ""),
        "hidden_count": int(row["hidden_count"] or 0),
        "deleted_count": int(row["deleted_count"] or 0),
        "structural_signature": hashlib.sha1(
            str(signature_row["structural_signature"] if signature_row else "").encode("utf-8")
        ).hexdigest(),
    }


def _attach_attribution_fields(row: dict, uncategorized_id: int) -> dict:
    """Attach official project attribution fields to a row via the policy.

    Merges ``is_official_project`` / ``display_project_name`` /
    ``display_project_id`` etc. so that ``format_activity_project_cell``
    and other attribution-aware consumers work on plain activity rows.
    This CRUD helper is official-display-only; report/statistics/export
    projections must stay on ``timeline_service`` report rows instead of
    adding ``report_project_fields`` here.
    """
    row["raw_project_id_deprecated"] = row.get("project_id")
    if row.get("effective_project_id") is not None:
        row["project_id"] = int(row.get("effective_project_id") or 0)
        row["project_name"] = row.get("effective_project_name") or UNCATEGORIZED_PROJECT
        row["project_description"] = row.get("effective_project_description") or ""
    else:
        row["project_id"] = uncategorized_id
        row["project_name"] = UNCATEGORIZED_PROJECT
        row["project_description"] = ""
    row.update(official_project_fields(row, uncategorized_id))
    return row


def get_activities_by_range(start_date: str, end_date: str) -> list[dict]:
    """Return CRUD / official-display-only activity rows for a date range.

    This intentionally attaches ``official_project_fields`` only. It must
    not be used for Timeline / Statistics / Export / report-visible project
    projection; those surfaces must use
    ``timeline_service.get_report_activity_rows`` or
    ``timeline_service.get_project_sessions_by_range``.
    """
    start = f"{start_date} 00:00:00"
    end = f"{end_date} 23:59:59"
    uncategorized_id = get_or_create_uncategorized_project()
    with get_connection() as conn:
        rows = conn.execute(
            _activity_select_sql("a.is_deleted = 0 AND a.start_time BETWEEN ? AND ?"),
            (start, end),
        ).fetchall()
    return [
        _attach_attribution_fields(attach_resource(row), uncategorized_id)
        for row in dict_rows(rows)
    ]


def get_activity(activity_id: int) -> dict | None:
    """Return one CRUD / official-display-only activity row.

    Do not use this for Timeline / Statistics / Export report-visible
    projection. Reporting surfaces must use ``timeline_service`` report
    row/session helpers.
    """
    with get_connection() as conn:
        row = conn.execute(_activity_select_sql("a.id = ?"), (activity_id,)).fetchone()
    if not row:
        return None
    uncategorized_id = get_or_create_uncategorized_project()
    return _attach_attribution_fields(attach_resource(dict(row)), uncategorized_id)


def activity_display_name(activity: dict) -> str:
    name = activity.get("resource_display_name") or activity.get("activity_display_name")
    if name:
        return str(name).strip()
    return attach_resource(activity)["activity_display_name"]


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

    When a real full path becomes available for an activity that only
    had a name-only resource (e.g. ``合同.docx`` from the window title), we
    re-run detection and upgrade the stored resource so that path-based
    identity keys, ``path_hint`` and ``path_key`` are populated. Excluded
    activities keep their anonymous resource.
    """
    from ..path_utils import normalize_path_key

    row = conn.execute(
        "SELECT app_name, process_name, window_title, status, start_time FROM activity_log WHERE id = ?",
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

    # If detection yields only a name-only identity but a real local file
    # path is now available, upgrade to a path-based identity. Keep the
    # existing kind/subtype when the detector surfaced no file so we don't
    # downgrade an already-classified resource.
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


def update_project_editable_activities_project(activity_ids: list[int], project_id: int) -> None:
    raise ValueError("activity_level_project_edit_removed")


def apply_midnight_anchor_assignment(activity_id: int, project_id: int) -> None:
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO activity_project_assignment(
                activity_id, project_id, confidence, source, is_manual, suggested_project_name,
                source_rule_type, source_rule_id, created_at, updated_at
            )
            VALUES (?, ?, 90, 'midnight_anchor', 0, NULL, NULL, NULL, ?, ?)
            ON CONFLICT(activity_id) DO UPDATE SET
                project_id = excluded.project_id,
                confidence = excluded.confidence,
                source = excluded.source,
                is_manual = 0,
                suggested_project_name = NULL,
                source_rule_type = NULL,
                source_rule_id = NULL,
                updated_at = excluded.updated_at
            """,
            (activity_id, project_id, ts, ts),
        )


def finalize_created_activity(activity_id: int) -> None:
    from .project_inference_service import process_new_activity

    process_new_activity(activity_id)


def update_project_editable_activity_note(activity_id: int, note: str) -> None:
    raise ValueError("activity_level_note_edit_removed")
