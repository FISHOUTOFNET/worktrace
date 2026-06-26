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


def update_activity_time(activity_id: int, start_time: str, end_time: str) -> None:
    """Atomically update an activity's ``start_time``, ``end_time``, and
    ``duration_seconds``.

    This is the low-level write used by the Phase 3B.1 Timeline time-correction
    path. The caller (the API layer) is responsible for input validation
    (format, existence, not-deleted, not-in-progress, ``start < end``); this
    method defensively re-derives ``duration_seconds`` from the new range and
    restricts the UPDATE to non-deleted, already-closed rows so a stale or
    racing call cannot mutate a deleted or in-progress record.

    ``start_time`` and ``end_time`` must already be validated
    ``YYYY-MM-DD HH:MM:SS`` strings with ``start_time < end_time``.
    """
    start_dt = _parse_time(start_time)
    end_dt = _parse_time(end_time)
    duration = int((end_dt - start_dt).total_seconds())
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE activity_log
            SET start_time = ?,
                end_time = ?,
                duration_seconds = ?,
                updated_at = ?
            WHERE id = ?
              AND is_deleted = 0
              AND end_time IS NOT NULL
            """,
            (start_time, end_time, duration, now_str(), activity_id),
        )
        if cur.rowcount == 0:
            # Defensive guard: the row was deleted or reopened between the
            # API-layer validation and this write (a race condition), or the
            # caller bypassed validation. Raise so the API can map this to a
            # controlled ``TimelineTimeEditError`` instead of silently
            # succeeding with 0 rows written.
            raise ValueError("activity_time_update_affected_zero_rows")


def split_activity(activity_id: int, split_time: str) -> dict:
    """Atomically split a closed activity into two at ``split_time``.

    The original activity is updated to ``[original_start, split_time)`` and a
    new activity is inserted for ``[split_time, original_end)``. Both
    ``duration_seconds`` values are recomputed precisely from the new ranges.

    Field inheritance (conservative):
    - The new activity copies ``app_name``, ``process_name``, ``window_title``,
      ``file_path_hint``, ``status``, ``source``, ``auto_classified``,
      ``manual_override``, ``project_id``, ``is_hidden``, ``is_deleted`` from
      the original row. These are DB-internal fields required for record
      integrity and classification; they are never surfaced to the bridge.
    - ``created_at`` and ``updated_at`` are set to the current write time
      (``now_str()``) for the new activity — they are NOT copied from the
      original. The new row is a new record, so its creation timestamp
      reflects when the split was performed. The original activity's
      ``updated_at`` is also refreshed to the write time (its ``end_time``
      and ``duration_seconds`` changed); its ``created_at`` is untouched.
    - ``activity_project_assignment`` is copied to the new activity so manual
      and automatic assignments are preserved. The new activity does not
      become "未归类" unless the original was. If the original has no
      assignment row, no assignment is created for the new activity either.
    - ``activity_resource`` is copied to the new activity (a new row with the
      same ``identity_key``, ``display_name``, ``path_hint`` etc.) so the
      resource display name is preserved on both halves. Excluded activities
      keep their anonymous resource.
    - ``note`` (the activity_log.note column) is NOT copied to the new
      activity. The primary note mechanism is ``project_session_note`` keyed
      by ``(report_date, first_activity_id)``; the front-half keeps the
      original id and thus keeps any session note. The new back-half starts
      without a note. See docs/ui-webview-migration.md Phase 3B.2.

    The write is a single transaction; any failure rolls back so the original
    activity is untouched and no half-created new activity remains.

    Returns ``{"original_activity_id": int, "new_activity_id": int}``.

    Raises ``ValueError`` if the activity is missing, deleted, in-progress, or
    if the UPDATE affects 0 rows (race condition). The caller (API layer) is
    responsible for input validation (format, range).
    """
    split_dt = _parse_time(split_time)
    ts = now_str()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, start_time, end_time, app_name, process_name, window_title,
                   file_path_hint, status, source, is_deleted, is_hidden,
                   auto_classified, manual_override, project_id
            FROM activity_log
            WHERE id = ?
            """,
            (activity_id,),
        ).fetchone()
        if not row or int(row["is_deleted"] or 0):
            raise ValueError("activity_not_found_or_deleted")
        if row["end_time"] is None:
            raise ValueError("activity_in_progress")
        orig_start = row["start_time"]
        orig_end = row["end_time"]
        first_duration = int((split_dt - _parse_time(orig_start)).total_seconds())
        second_duration = int((_parse_time(orig_end) - split_dt).total_seconds())
        if first_duration <= 0 or second_duration <= 0:
            raise ValueError("split_time_out_of_range")

        # 1) Update the original activity to the front half.
        cur = conn.execute(
            """
            UPDATE activity_log
            SET end_time = ?,
                duration_seconds = ?,
                updated_at = ?
            WHERE id = ?
              AND is_deleted = 0
              AND end_time IS NOT NULL
            """,
            (split_time, first_duration, ts, activity_id),
        )
        if cur.rowcount == 0:
            # Race condition: deleted or reopened between the SELECT above and
            # this UPDATE. Abort without inserting the new activity.
            raise ValueError("activity_split_update_affected_zero_rows")

        # 2) Insert the new back-half activity. ``note`` is intentionally NOT
        # copied (see docstring).
        new_cur = conn.execute(
            """
            INSERT INTO activity_log(
                start_time, end_time, duration_seconds, app_name, process_name, window_title,
                file_path_hint, status, source, is_deleted, is_hidden,
                auto_classified, manual_override, project_id, note, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                split_time,
                orig_end,
                second_duration,
                row["app_name"],
                row["process_name"],
                row["window_title"],
                row["file_path_hint"],
                row["status"],
                row["source"],
                int(row["is_hidden"] or 0),
                int(row["auto_classified"] or 0),
                int(row["manual_override"] or 0),
                row["project_id"],
                ts,
                ts,
            ),
        )
        new_activity_id = int(new_cur.lastrowid)
        if new_activity_id <= 0:
            # Defensive guard: the INSERT did not return a valid row id.
            # This should never happen under normal sqlite3 operation, but
            # if it does we must not proceed with assignment/resource copies
            # that would reference a non-existent activity id. Raise so the
            # transaction rolls back and the original activity is restored.
            raise ValueError("activity_split_insert_returned_no_id")

        # 3) Copy the project assignment row so the new activity keeps the
        # same effective project (manual or automatic).
        assignment = conn.execute(
            """
            SELECT project_id, confidence, source, is_manual, suggested_project_name
            FROM activity_project_assignment
            WHERE activity_id = ?
            """,
            (activity_id,),
        ).fetchone()
        if assignment:
            conn.execute(
                """
                INSERT INTO activity_project_assignment(
                    activity_id, project_id, confidence, source, is_manual, suggested_project_name, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO NOTHING
                """,
                (
                    new_activity_id,
                    assignment["project_id"],
                    int(assignment["confidence"] or 0),
                    assignment["source"],
                    int(assignment["is_manual"] or 0),
                    assignment["suggested_project_name"],
                    ts,
                    ts,
                ),
            )

        # 4) Copy the activity_resource row so the new activity keeps the same
        # resource display name, identity key, and path_hint. Excluded
        # activities copy their anonymous resource, which is already safe.
        resource = conn.execute(
            """
            SELECT resource_kind, resource_subtype, display_name, identity_key,
                   is_anchor, confidence, source, app_name, process_name, window_title,
                   path_hint, path_key, uri_scheme, uri_host, uri_hint, metadata_json
            FROM activity_resource
            WHERE activity_id = ?
            """,
            (activity_id,),
        ).fetchone()
        if resource:
            conn.execute(
                """
                INSERT INTO activity_resource(
                    activity_id, resource_kind, resource_subtype, display_name, identity_key,
                    is_anchor, confidence, source, app_name, process_name, window_title,
                    path_hint, path_key, uri_scheme, uri_host, uri_hint, metadata_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO NOTHING
                """,
                (
                    new_activity_id,
                    resource["resource_kind"],
                    resource["resource_subtype"],
                    resource["display_name"],
                    resource["identity_key"],
                    int(resource["is_anchor"] or 0),
                    int(resource["confidence"] or 0),
                    resource["source"],
                    resource["app_name"],
                    resource["process_name"],
                    resource["window_title"],
                    resource["path_hint"],
                    resource["path_key"],
                    resource["uri_scheme"],
                    resource["uri_host"],
                    resource["uri_hint"],
                    resource["metadata_json"],
                    ts,
                    ts,
                ),
            )

        return {"original_activity_id": activity_id, "new_activity_id": new_activity_id}


# Maximum gap (in seconds) tolerated between two activities being merged.
# Real collector data may have a 1-2 second gap between adjacent activities
# due to close/create timing; allowing a small tolerance makes merge usable
# without opening the door to merging activities that are far apart in time.
# A gap larger than this is rejected as ``not_adjacent`` by the API layer.
MERGE_GAP_TOLERANCE_SECONDS = 2


def merge_activities(first_activity_id: int, second_activity_id: int) -> dict:
    """Atomically merge two closed activities into one.

    The earlier activity (by ``start_time``, then ``id``) is kept: its
    ``start_time`` is unchanged, its ``end_time`` becomes the later
    activity's ``end_time``, and its ``duration_seconds`` is recomputed
    precisely from the merged range. The later activity is soft-deleted
    (``is_deleted = 1``); it is NOT physically removed.

    Conservative preconditions (the API layer validates most of these before
    calling; the service re-checks the critical DB state guards so a race
    between validation and write cannot corrupt data):

    - The two ids must be different.
    - Both activities must exist and ``is_deleted = 0``.
    - Both must be closed (raw ``end_time IS NOT NULL``).
    - The two activities must not overlap: ``earlier.end_time <= later.start_time``.
    - The two activities must be adjacent within ``MERGE_GAP_TOLERANCE_SECONDS``:
      ``later.start_time - earlier.end_time <= tolerance``.
    - Both must have the same ``project_id``.
    - Both must have the same ``activity_resource.identity_key``.
    - Both must have the same ``status``.
    - Both must have the same ``source``.

    Field inheritance (conservative):
    - The kept (earlier) activity keeps its ``id``, ``start_time``,
      ``created_at``, ``app_name``, ``process_name``, ``window_title``,
      ``file_path_hint``, ``status``, ``source``, ``project_id``, ``note``,
      and all other fields. Only ``end_time``, ``duration_seconds``, and
      ``updated_at`` change.
    - The merged (later) activity is soft-deleted (``is_deleted = 1``) and
      its ``updated_at`` is refreshed. Its assignment / resource rows are
      left in place (not physically deleted); timeline reads exclude it via
      ``is_deleted = 0`` filtering.
    - ``activity_log.note`` is NOT copied or concatenated from the later
      activity; the kept activity's note is preserved as-is.
    - ``project_session_note`` is NOT migrated. If the later activity was a
      ``first_activity_id`` for a session note, that note row remains keyed
      to the now-deleted activity id. Timeline sessions are rebuilt by
      ``timeline_service`` from live (non-deleted) activities, so the
      orphaned note does not surface in the UI. See
      docs/ui-webview-migration.md Phase 3B.3.

    The write is a single transaction; any failure rolls back so both
    activities keep their original state.

    Returns ``{"kept_activity_id": int, "merged_activity_id": int}`` where
    ``kept_activity_id`` is the earlier activity's id and
    ``merged_activity_id`` is the later (now soft-deleted) activity's id.

    Raises ``ValueError`` with a stable code suffix for known failure modes:
    - ``activity_merge_same_id`` — the two ids are identical.
    - ``activity_merge_not_found_or_deleted`` — either activity is missing
      or already deleted.
    - ``activity_merge_in_progress`` — either activity is still open.
    - ``activity_merge_overlap`` — the two activities overlap in time.
    - ``activity_merge_not_adjacent`` — the gap exceeds tolerance.
    - ``activity_merge_different_project`` — project_id differs.
    - ``activity_merge_different_resource`` — resource identity_key differs.
    - ``activity_merge_incompatible_activity`` — status or source differs.
    - ``activity_merge_update_affected_zero_rows`` — race condition: a row
      was deleted/reopened between the SELECT and the UPDATE.
    """
    if first_activity_id == second_activity_id:
        raise ValueError("activity_merge_same_id")
    ts = now_str()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, start_time, end_time, app_name, process_name, window_title,
                   file_path_hint, status, source, is_deleted, is_hidden,
                   auto_classified, manual_override, project_id, note, created_at
            FROM activity_log
            WHERE id IN (?, ?)
            """,
            (first_activity_id, second_activity_id),
        ).fetchall()
        if len(rows) != 2:
            raise ValueError("activity_merge_not_found_or_deleted")
        # Sort by start_time, then id, to determine kept (earlier) and
        # merged (later). This does NOT trust the caller's argument order.
        sorted_rows = sorted(rows, key=lambda r: (r["start_time"], r["id"]))
        kept_row = sorted_rows[0]
        merged_row = sorted_rows[1]
        if int(kept_row["is_deleted"] or 0) or int(merged_row["is_deleted"] or 0):
            raise ValueError("activity_merge_not_found_or_deleted")
        if kept_row["end_time"] is None or merged_row["end_time"] is None:
            raise ValueError("activity_merge_in_progress")

        kept_start_dt = _parse_time(kept_row["start_time"])
        kept_end_dt = _parse_time(kept_row["end_time"])
        merged_start_dt = _parse_time(merged_row["start_time"])
        merged_end_dt = _parse_time(merged_row["end_time"])

        # Overlap check: earlier.end_time > later.start_time means overlap.
        if kept_end_dt > merged_start_dt:
            raise ValueError("activity_merge_overlap")
        # Adjacency check: gap must be within tolerance.
        gap_seconds = int((merged_start_dt - kept_end_dt).total_seconds())
        if gap_seconds > MERGE_GAP_TOLERANCE_SECONDS:
            raise ValueError("activity_merge_not_adjacent")

        # Project consistency check.
        if kept_row["project_id"] != merged_row["project_id"]:
            raise ValueError("activity_merge_different_project")

        # Resource consistency check via identity_key.
        kept_res = conn.execute(
            "SELECT identity_key FROM activity_resource WHERE activity_id = ?",
            (kept_row["id"],),
        ).fetchone()
        merged_res = conn.execute(
            "SELECT identity_key FROM activity_resource WHERE activity_id = ?",
            (merged_row["id"],),
        ).fetchone()
        kept_identity = kept_res["identity_key"] if kept_res else None
        merged_identity = merged_res["identity_key"] if merged_res else None
        if kept_identity != merged_identity:
            raise ValueError("activity_merge_different_resource")

        # Status / source consistency check.
        if kept_row["status"] != merged_row["status"]:
            raise ValueError("activity_merge_incompatible_activity")
        if kept_row["source"] != merged_row["source"]:
            raise ValueError("activity_merge_incompatible_activity")

        # All preconditions passed. Perform the atomic write.
        new_end = merged_row["end_time"]
        new_duration = int((merged_end_dt - kept_start_dt).total_seconds())

        # 1) Update the kept (earlier) activity: extend end_time to the
        #    later activity's end_time and recompute duration_seconds.
        kept_cur = conn.execute(
            """
            UPDATE activity_log
            SET end_time = ?,
                duration_seconds = ?,
                updated_at = ?
            WHERE id = ?
              AND is_deleted = 0
              AND end_time IS NOT NULL
            """,
            (new_end, new_duration, ts, kept_row["id"]),
        )
        if kept_cur.rowcount == 0:
            # Race condition: kept activity was deleted or reopened between
            # the SELECT and the UPDATE. Abort without touching the merged
            # activity.
            raise ValueError("activity_merge_update_affected_zero_rows")

        # 2) Soft-delete the merged (later) activity. The WHERE clause
        #    re-checks is_deleted and end_time so a race cannot corrupt a
        #    concurrently-modified row.
        merged_cur = conn.execute(
            """
            UPDATE activity_log
            SET is_deleted = 1,
                updated_at = ?
            WHERE id = ?
              AND is_deleted = 0
              AND end_time IS NOT NULL
            """,
            (ts, merged_row["id"]),
        )
        if merged_cur.rowcount == 0:
            # Race condition: merged activity was deleted or reopened.
            raise ValueError("activity_merge_update_affected_zero_rows")

        return {
            "kept_activity_id": int(kept_row["id"]),
            "merged_activity_id": int(merged_row["id"]),
        }


def hide_activity(activity_id: int) -> None:
    """Atomically hide a closed activity from the default Timeline.

    Sets ``activity_log.is_hidden = 1`` for the given activity. The row is
    not physically deleted; assignment / resource / note / session-note rows
    are untouched. Only non-deleted, already-closed (raw ``end_time IS NOT
    NULL``) rows are affected, so a stale or racing call cannot hide a
    deleted or in-progress record.

    This operation is idempotent: hiding an already-hidden activity still
    succeeds (the UPDATE matches the row and refreshes ``updated_at``).

    Raises ``ValueError("activity_hide_affected_zero_rows")`` if the UPDATE
    affects 0 rows (the activity was missing, deleted, or in-progress at
    write time). The caller (API layer) maps this to a controlled
    ``TimelineVisibilityError``.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE activity_log
            SET is_hidden = 1, updated_at = ?
            WHERE id = ?
              AND is_deleted = 0
              AND end_time IS NOT NULL
            """,
            (now_str(), activity_id),
        )
        if cur.rowcount == 0:
            raise ValueError("activity_hide_affected_zero_rows")


def soft_delete_activity(activity_id: int) -> None:
    """Atomically soft-delete a closed activity from the Timeline.

    Sets ``activity_log.is_deleted = 1`` for the given activity. The row is
    not physically deleted; assignment / resource / note / session-note rows
    are untouched. Only non-deleted, already-closed (raw ``end_time IS NOT
    NULL``) rows are affected, so a stale or racing call cannot delete a
    deleted or in-progress record.

    Raises ``ValueError("activity_soft_delete_affected_zero_rows")`` if the
    UPDATE affects 0 rows (the activity was missing, already deleted, or
    in-progress at write time). The caller (API layer) maps this to a
    controlled ``TimelineVisibilityError``.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE activity_log
            SET is_deleted = 1, updated_at = ?
            WHERE id = ?
              AND is_deleted = 0
              AND end_time IS NOT NULL
            """,
            (now_str(), activity_id),
        )
        if cur.rowcount == 0:
            raise ValueError("activity_soft_delete_affected_zero_rows")


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
