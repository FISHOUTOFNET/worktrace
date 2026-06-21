from __future__ import annotations

from datetime import datetime

from ..constants import (
    DEFAULT_CONTEXT_CARRY_MINUTES,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)
from ..activity_identity import attach_activity_identity
from ..db import dict_rows, get_connection, get_db_path, now_str
from .project_inference_service import assign_project_for_activity
from .settings_service import get_int_setting

INTERRUPT_STATUSES = {STATUS_IDLE, STATUS_PAUSED}
_CONTEXT_RECOMPUTE_CACHE: dict[str, tuple] = {}


def recompute_context_assignments_for_date(date: str) -> None:
    start = f"{date} 00:00:00"
    end = f"{date} 23:59:59"
    carry_minutes = max(0, get_int_setting("context_carry_minutes", DEFAULT_CONTEXT_CARRY_MINUTES))
    cache_key = _context_cache_key(date)
    fingerprint = _context_fingerprint(start, end, carry_minutes)
    if _CONTEXT_RECOMPUTE_CACHE.get(cache_key) == fingerprint:
        return
    uncategorized_id = _get_uncategorized_project_id()

    rows = _load_rows(start, end)
    if _ensure_assignments(rows):
        rows = _load_rows(start, end)
    if _recompute_anchor_rows(rows):
        rows = _load_rows(start, end)

    for index, row in enumerate(rows):
        if row["status"] != STATUS_NORMAL:
            continue
        if row.get("assignment_source") == "midnight_anchor":
            continue
        if row.get("is_anchor_file"):
            continue
        if int(row["manual_override"] or 0) or int(row["assignment_is_manual"] or 0):
            continue

        target_project_id = _infer_context_project(rows, index, carry_minutes, uncategorized_id)
        source = "anchor_context" if target_project_id != uncategorized_id else "uncategorized"
        confidence = 60 if source == "anchor_context" else 0
        _sync_assignment_and_activity(
            int(row["id"]),
            target_project_id,
            source,
            confidence,
            is_manual=False,
            auto_classified=False,
        )
    _CONTEXT_RECOMPUTE_CACHE[cache_key] = _context_fingerprint(start, end, carry_minutes)


def invalidate_context_recompute_cache(date: str | None = None) -> None:
    if date is None:
        _CONTEXT_RECOMPUTE_CACHE.clear()
        return
    _CONTEXT_RECOMPUTE_CACHE.pop(_context_cache_key(date), None)


def _context_cache_key(date: str) -> str:
    return f"{get_db_path().resolve()}:{date}"


def _context_fingerprint(start: str, end: str, carry_minutes: int) -> tuple:
    with get_connection() as conn:
        activity_sig = _ordered_concat(
            conn,
            """
            SELECT
                a.id || ':' ||
                COALESCE(a.start_time, '') || ':' ||
                COALESCE(a.end_time, '') || ':' ||
                COALESCE(a.app_name, '') || ':' ||
                COALESCE(a.process_name, '') || ':' ||
                COALESCE(a.window_title, '') || ':' ||
                COALESCE(a.file_path_hint, '') || ':' ||
                COALESCE(a.status, '') || ':' ||
                COALESCE(a.project_id, '') || ':' ||
                COALESCE(a.manual_override, 0) AS sig
            FROM activity_log a
            WHERE a.is_deleted = 0
              AND a.start_time BETWEEN ? AND ?
            ORDER BY a.start_time ASC, a.id ASC
            """,
            (start, end),
        )
        assignment_sig = _ordered_concat(
            conn,
            """
            SELECT
                apa.activity_id || ':' ||
                COALESCE(apa.project_id, '') || ':' ||
                COALESCE(apa.source, '') || ':' ||
                COALESCE(apa.is_manual, 0) || ':' ||
                COALESCE(apa.suggested_project_name, '') AS sig
            FROM activity_project_assignment apa
            JOIN activity_log a ON a.id = apa.activity_id
            WHERE a.is_deleted = 0
              AND a.start_time BETWEEN ? AND ?
            ORDER BY apa.activity_id ASC
            """,
            (start, end),
        )
        project_sig = _table_update_signature(conn, "project")
        folder_rule_sig = _table_update_signature(conn, "folder_project_rule")
        folder_index_sig = _table_update_signature(conn, "folder_rule_index_state")
        keyword_rule_sig = _table_update_signature(conn, "project_rule")
    return (carry_minutes, activity_sig, assignment_sig, project_sig, folder_rule_sig, folder_index_sig, keyword_rule_sig)


def _ordered_concat(conn, sql: str, params: tuple = ()) -> str:
    row = conn.execute(f"SELECT COALESCE(group_concat(sig, '|'), '') AS sig FROM ({sql})", params).fetchone()
    return str(row["sig"] or "") if row else ""


def _table_update_signature(conn, table_name: str) -> tuple[int, str]:
    row = conn.execute(f"SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS updated_at FROM {table_name}").fetchone()
    return (int(row["count"] or 0), str(row["updated_at"] or "")) if row else (0, "")


def _load_rows(start: str, end: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.*,
                apa.project_id AS assignment_project_id,
                apa.source AS assignment_source,
                apa.is_manual AS assignment_is_manual
            FROM activity_log a
            LEFT JOIN activity_project_assignment apa ON apa.activity_id = a.id
            WHERE a.is_deleted = 0
              AND a.start_time BETWEEN ? AND ?
            ORDER BY a.start_time ASC, a.id ASC
            """,
            (start, end),
        ).fetchall()
    return [attach_activity_identity(row) for row in dict_rows(rows)]


def _ensure_assignments(rows: list[dict]) -> bool:
    changed = False
    for row in rows:
        if row["assignment_project_id"] is None:
            assign_project_for_activity(int(row["id"]))
            changed = True
    return changed


def _recompute_anchor_rows(rows: list[dict]) -> bool:
    changed = False
    for row in rows:
        if row["status"] == STATUS_NORMAL and row.get("assignment_source") == "midnight_anchor":
            continue
        if row["status"] == STATUS_NORMAL and row.get("is_anchor_file"):
            if int(row.get("manual_override") or 0) or int(row.get("assignment_is_manual") or 0):
                continue
            assignment = assign_project_for_activity(int(row["id"]))
            if _assignment_changed(row, assignment):
                changed = True
    return changed


def _assignment_changed(row: dict, assignment: dict) -> bool:
    if not assignment:
        return True
    return not (
        int(row.get("assignment_project_id") or 0) == int(assignment.get("project_id") or 0)
        and str(row.get("assignment_source") or "") == str(assignment.get("source") or "")
        and int(row.get("assignment_is_manual") or 0) == int(assignment.get("is_manual") or 0)
    )


def _infer_context_project(rows: list[dict], index: int, carry_minutes: int, uncategorized_id: int) -> int:
    row = rows[index]
    if _nearest_anchor_is_uncategorized(rows, index, -1, uncategorized_id) or _nearest_anchor_is_uncategorized(rows, index, 1, uncategorized_id):
        return uncategorized_id
    previous_anchor = _find_previous_anchor(rows, index, uncategorized_id)
    next_anchor = _find_next_anchor(rows, index, uncategorized_id)

    if previous_anchor and next_anchor:
        previous_project = _row_project_id(previous_anchor)
        next_project = _row_project_id(next_anchor)
        if previous_project == next_project:
            return previous_project
        return uncategorized_id

    if previous_anchor and not next_anchor:
        if _minutes_between(_anchor_context_time(previous_anchor), row["start_time"]) <= carry_minutes:
            return _row_project_id(previous_anchor)
    if next_anchor and not previous_anchor:
        if _minutes_between(row["start_time"], next_anchor["start_time"]) <= carry_minutes:
            return _row_project_id(next_anchor)

    return uncategorized_id


def _nearest_anchor_is_uncategorized(rows: list[dict], index: int, step: int, uncategorized_id: int) -> bool:
    pos = index + step
    while 0 <= pos < len(rows):
        row = rows[pos]
        if row["status"] in INTERRUPT_STATUSES:
            return False
        if _is_context_anchor(row):
            return _row_project_id(row) == uncategorized_id
        pos += step
    return False


def _find_previous_anchor(rows: list[dict], index: int, uncategorized_id: int) -> dict | None:
    for pos in range(index - 1, -1, -1):
        row = rows[pos]
        if row["status"] in INTERRUPT_STATUSES:
            return None
        if _is_context_anchor(row):
            project_id = _row_project_id(row)
            return row if project_id != uncategorized_id else None
    return None


def _find_next_anchor(rows: list[dict], index: int, uncategorized_id: int) -> dict | None:
    for pos in range(index + 1, len(rows)):
        row = rows[pos]
        if row["status"] in INTERRUPT_STATUSES:
            return None
        if _is_context_anchor(row):
            project_id = _row_project_id(row)
            return row if project_id != uncategorized_id else None
    return None


def _row_project_id(row: dict) -> int:
    return int(row.get("assignment_project_id") or row.get("project_id") or 0)


def _is_context_anchor(row: dict) -> bool:
    return row["status"] == STATUS_NORMAL and (
        row.get("is_anchor_file") or row.get("assignment_source") == "midnight_anchor"
    )


def _anchor_context_time(row: dict) -> str:
    return row.get("end_time") or row.get("start_time")


def _minutes_between(start: str, end: str) -> float:
    start_dt = datetime.strptime(start, TIME_FORMAT)
    end_dt = datetime.strptime(end, TIME_FORMAT)
    return max(0.0, (end_dt - start_dt).total_seconds() / 60)


def _sync_assignment_and_activity(
    activity_id: int,
    project_id: int,
    source: str,
    confidence: int,
    is_manual: bool,
    auto_classified: bool,
) -> None:
    ts = now_str()
    with get_connection() as conn:
        assignment = conn.execute(
            """
            SELECT project_id, source, confidence, is_manual, suggested_project_name
            FROM activity_project_assignment
            WHERE activity_id = ?
            """,
            (activity_id,),
        ).fetchone()
        activity = conn.execute(
            "SELECT project_id, auto_classified FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        assignment_changed = not assignment or not (
            assignment["project_id"] == project_id
            and assignment["source"] == source
            and int(assignment["confidence"]) == confidence
            and int(assignment["is_manual"]) == int(is_manual)
            and not (assignment["suggested_project_name"] or "")
        )
        activity_changed = bool(activity) and not (
            activity["project_id"] == project_id
            and int(activity["auto_classified"] or 0) == int(auto_classified)
        )
        if not assignment_changed and not activity_changed:
            return
        if assignment_changed:
            conn.execute(
                """
                INSERT INTO activity_project_assignment(
                    activity_id, project_id, confidence, source, is_manual, suggested_project_name, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    project_id = excluded.project_id,
                    confidence = excluded.confidence,
                    source = excluded.source,
                    is_manual = excluded.is_manual,
                    suggested_project_name = NULL,
                    updated_at = excluded.updated_at
                """,
                (activity_id, project_id, confidence, source, int(is_manual), ts, ts),
            )
        if activity_changed:
            conn.execute(
                """
                UPDATE activity_log
                SET project_id = ?, auto_classified = ?, updated_at = ?
                WHERE id = ?
                """,
                (project_id, int(auto_classified), ts, activity_id),
            )


def _get_uncategorized_project_id() -> int:
    from .project_service import get_or_create_uncategorized_project

    return get_or_create_uncategorized_project()
