from __future__ import annotations

from datetime import datetime

from ..constants import (
    ANCHOR_FILE_EXTENSIONS,
    CLIPBOARD_TRANSITION_SECONDS,
    DEFAULT_CONTEXT_CARRY_MINUTES,
    REPORT_CONTEXT_SHORT_MERGE_SECONDS,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)
from ..db import dict_rows, get_connection, get_db_path, now_str
from . import clipboard_service, session_boundary_service
from .project_inference_service import assign_project_for_activity
from .resource_service import attach_resource
from .settings_service import get_int_setting

INTERRUPT_STATUSES = {STATUS_IDLE, STATUS_PAUSED}
DIRECT_ASSIGNMENT_SOURCES = {"manual", "folder_rule", "keyword_rule", "midnight_anchor"}
# ``anchor_context`` covers two context-assignment scenarios:
#   1. Ordinary anchor context carry — auxiliary activities between two
#      same-project anchors inherit the anchor's project.
#   2. Short same-project gap bridging — a short uncategorized context
#      anchor (e.g. a brief .doc / .docx Word activity) sandwiched
#      between two same-project anchors is bridged to that project.
# Both scenarios reuse the ``anchor_context`` source; no new schema
# source is introduced.
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
    if _recompute_clipboard_transition_rows(rows, uncategorized_id):
        rows = _load_rows(start, end)
    if _recompute_short_gap_anchor_rows(rows, uncategorized_id):
        rows = _load_rows(start, end)

    for index, row in enumerate(rows):
        if row["status"] != STATUS_NORMAL:
            continue
        if row.get("assignment_source") == "midnight_anchor":
            continue
        if row.get("assignment_source") in DIRECT_ASSIGNMENT_SOURCES | {"clipboard_transition_context"}:
            continue
        if _is_context_anchor(row):
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
        clipboard_sig = _table_update_signature(conn, "activity_clipboard_event")
    return (
        carry_minutes,
        activity_sig,
        assignment_sig,
        project_sig,
        folder_rule_sig,
        folder_index_sig,
        keyword_rule_sig,
        clipboard_sig,
    )


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
    return [attach_resource(row) for row in dict_rows(rows)]


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
        if _is_context_anchor(row):
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


def _recompute_clipboard_transition_rows(rows: list[dict], uncategorized_id: int) -> bool:
    if len(rows) < 2:
        return False
    with get_connection() as conn:
        copy_times = clipboard_service.clipboard_times_for_activity_ids(conn, [int(row["id"]) for row in rows])
    changed = False
    for index in range(len(rows) - 1):
        previous = rows[index]
        current = rows[index + 1]
        if not copy_times.get(int(previous["id"])):
            continue
        if not _is_normal_adjacent_transition(previous, current):
            continue
        if not _copied_before_transition(previous, current, copy_times):
            continue
        previous_project = _row_project_id(previous)
        current_project = _row_project_id(current)
        previous_concrete = previous_project != uncategorized_id
        current_concrete = current_project != uncategorized_id
        if previous_concrete and _can_apply_clipboard_context(current):
            _set_clipboard_context_assignment(current, previous_project)
            changed = True
            continue
        if current_concrete and _can_apply_clipboard_context(previous):
            _set_clipboard_context_assignment(previous, current_project)
            changed = True
    return changed


def _is_normal_adjacent_transition(previous: dict, current: dict) -> bool:
    if previous.get("status") != STATUS_NORMAL or current.get("status") != STATUS_NORMAL:
        return False
    return not _has_session_boundary_between(previous, current)


def _has_session_boundary_between(previous: dict, current: dict) -> bool:
    boundary_start = previous.get("end_time") or previous.get("start_time") or ""
    boundary_end = current.get("start_time") or ""
    if not boundary_start or not boundary_end:
        return False
    return session_boundary_service.has_boundary_between(str(boundary_start), str(boundary_end))


def _copied_before_transition(previous: dict, current: dict, copy_times: dict[int, list[str]]) -> bool:
    current_start = str(current.get("start_time") or "")
    if not current_start:
        return False
    for copied_at in copy_times.get(int(previous["id"]), []):
        seconds = _seconds_between(copied_at, current_start)
        if seconds is not None and 0 <= seconds <= CLIPBOARD_TRANSITION_SECONDS:
            return True
    return False


def _seconds_between(start: str, end: str) -> int | None:
    try:
        start_dt = datetime.strptime(start, TIME_FORMAT)
        end_dt = datetime.strptime(end, TIME_FORMAT)
    except (TypeError, ValueError):
        return None
    return int((end_dt - start_dt).total_seconds())


def _can_apply_clipboard_context(row: dict) -> bool:
    if row.get("status") != STATUS_NORMAL:
        return False
    if int(row.get("manual_override") or 0) or int(row.get("assignment_is_manual") or 0):
        return False
    return row.get("assignment_source") not in DIRECT_ASSIGNMENT_SOURCES


def _set_clipboard_context_assignment(row: dict, project_id: int) -> None:
    _sync_assignment_and_activity(
        int(row["id"]),
        int(project_id),
        "clipboard_transition_context",
        70,
        is_manual=False,
        auto_classified=False,
    )
    row["assignment_project_id"] = int(project_id)
    row["project_id"] = int(project_id)
    row["assignment_source"] = "clipboard_transition_context"
    row["assignment_is_manual"] = 0


def _recompute_short_gap_anchor_rows(rows: list[dict], uncategorized_id: int) -> bool:
    """Bridge short uncategorized context anchors between same-project anchors.

    For each context anchor row that is currently uncategorized (and not
    manual / not a direct-rule assignment), check whether it is sandwiched
    between two concrete (non-uncategorized) same-project anchors with a
    total middle-activity duration under ``REPORT_CONTEXT_SHORT_MERGE_SECONDS``.
    If so, persist the assignment with source ``anchor_context`` and update
    the in-memory row so subsequent non-anchor rows in the main loop see
    the bridged project.

    This covers the real-world scenario where a brief .doc / .docx Word
    activity (which is itself a context anchor) is sandwiched between two
    same-project anchors but does not hit any folder / keyword rule.
    Without this pass the anchor would stay uncategorized and would also
    block context carry for subsequent auxiliary activities.

    Conditions (all must hold):
      - The row is a context anchor (``_is_context_anchor``).
      - The row's current assignment is uncategorized (not manual, not
        folder_rule / keyword_rule / midnight_anchor / clipboard_transition_context).
      - No manual_override or assignment_is_manual.
      - Previous and next concrete anchors exist and belong to the same
        non-uncategorized project.
      - No interrupt status (idle / paused) between the anchors.
      - No session boundary between prev anchor and next anchor.
      - All middle activities (between the two anchors) are normal,
        visible, and non-deleted.
      - Total duration of middle activities <= threshold.
    """
    changed = False
    for index, row in enumerate(rows):
        if row.get("status") != STATUS_NORMAL:
            continue
        if not _is_context_anchor(row):
            continue
        source = row.get("assignment_source")
        if source in DIRECT_ASSIGNMENT_SOURCES or source == "clipboard_transition_context":
            continue
        if int(row.get("manual_override") or 0) or int(row.get("assignment_is_manual") or 0):
            continue
        # Only bridge rows that are currently uncategorized.
        if _row_project_id(row) != uncategorized_id:
            continue
        target = _short_gap_bridge_target(rows, index, uncategorized_id)
        if target is None:
            continue
        _set_short_gap_context_assignment(row, target)
        changed = True
    return changed


def _short_gap_bridge_target(
    rows: list[dict], index: int, uncategorized_id: int
) -> int | None:
    """Return the target project_id for short-gap bridging, or None."""
    row = rows[index]
    # Use the "concrete" anchor lookups so that other uncategorized context
    # anchors sitting between the same two same-project anchors are skipped
    # (rather than terminating the search). This lets every middle anchor in
    # a run of multiple short uncategorized anchors bridge to the surrounding
    # project, instead of only the first one.
    prev_anchor = _find_previous_concrete_anchor(rows, index, uncategorized_id)
    next_anchor = _find_next_concrete_anchor(rows, index, uncategorized_id)
    if not prev_anchor or not next_anchor:
        return None
    prev_project = _row_project_id(prev_anchor)
    next_project = _row_project_id(next_anchor)
    if prev_project != next_project or prev_project == uncategorized_id:
        return None
    # Find the index range of middle activities (between prev and next
    # anchor, exclusive of both anchors).
    prev_idx = rows.index(prev_anchor)
    next_idx = rows.index(next_anchor)
    if next_idx - prev_idx < 2:
        return None
    # All middle activities must be normal, visible, non-deleted.
    for mid_idx in range(prev_idx + 1, next_idx):
        mid_row = rows[mid_idx]
        if mid_row.get("status") != STATUS_NORMAL:
            return None
        if int(mid_row.get("is_hidden") or 0) or int(mid_row.get("is_deleted") or 0):
            return None
    # No session boundary between prev anchor and next anchor.
    if _has_session_boundary_in_range(rows, prev_idx, next_idx):
        return None
    # Total duration of middle activities must be under the threshold.
    middle_duration = _total_middle_duration_seconds(rows, prev_idx, next_idx)
    if middle_duration > REPORT_CONTEXT_SHORT_MERGE_SECONDS:
        return None
    return prev_project


def _has_session_boundary_in_range(rows: list[dict], start_idx: int, end_idx: int) -> bool:
    """Check if any consecutive pair between start_idx and end_idx has a session boundary."""
    for i in range(start_idx, end_idx):
        if _has_session_boundary_between(rows[i], rows[i + 1]):
            return True
    return False


def _total_middle_duration_seconds(rows: list[dict], start_idx: int, end_idx: int) -> int:
    """Sum durations of rows strictly between start_idx and end_idx."""
    total = 0
    for i in range(start_idx + 1, end_idx):
        mid_row = rows[i]
        start_time = str(mid_row.get("start_time") or "")
        end_time = str(mid_row.get("end_time") or "")
        if not start_time or not end_time:
            continue
        seconds = _seconds_between(start_time, end_time)
        if seconds is not None and seconds > 0:
            total += seconds
    return total


def _set_short_gap_context_assignment(row: dict, project_id: int) -> None:
    _sync_assignment_and_activity(
        int(row["id"]),
        int(project_id),
        "anchor_context",
        60,
        is_manual=False,
        auto_classified=False,
    )
    row["assignment_project_id"] = int(project_id)
    row["project_id"] = int(project_id)
    row["assignment_source"] = "anchor_context"
    row["assignment_is_manual"] = 0


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


def _find_previous_concrete_anchor(rows: list[dict], index: int, uncategorized_id: int) -> dict | None:
    """Like _find_previous_anchor, but skips uncategorized context anchors
    instead of stopping at them. Used by short-gap bridging, which needs to
    locate the surrounding non-uncategorized ("concrete") anchors even when
    other uncategorized anchors sit in between (so every middle anchor in a
    run gets bridged, not just the first)."""
    for pos in range(index - 1, -1, -1):
        row = rows[pos]
        if row["status"] in INTERRUPT_STATUSES:
            return None
        if _is_context_anchor(row):
            project_id = _row_project_id(row)
            if project_id != uncategorized_id:
                return row
    return None


def _find_next_concrete_anchor(rows: list[dict], index: int, uncategorized_id: int) -> dict | None:
    """Like _find_next_anchor, but skips uncategorized context anchors
    instead of stopping at them. See _find_previous_concrete_anchor."""
    for pos in range(index + 1, len(rows)):
        row = rows[pos]
        if row["status"] in INTERRUPT_STATUSES:
            return None
        if _is_context_anchor(row):
            project_id = _row_project_id(row)
            if project_id != uncategorized_id:
                return row
    return None


def _row_project_id(row: dict) -> int:
    return int(row.get("assignment_project_id") or row.get("project_id") or 0)


_ANCHOR_EXT_SET = frozenset(ext.casefold() for ext in ANCHOR_FILE_EXTENSIONS)


def _is_context_anchor(row: dict) -> bool:
    if row["status"] != STATUS_NORMAL:
        return False
    if row.get("assignment_source") == "midnight_anchor":
        return True
    if not row.get("resource_is_anchor"):
        return False
    # Only file-based anchors with ANCHOR_FILE_EXTENSIONS are context anchors.
    # Browser tabs, email messages, and code files (.py, .js, etc.) are
    # resource anchors for identity but should be auxiliary for context carry.
    if row.get("resource_kind") in ("browser_tab", "email"):
        return False
    display_name = str(row.get("resource_display_name") or "").strip()
    if display_name:
        _, ext = _split_ext(display_name)
        if ext and ext.casefold() in _ANCHOR_EXT_SET:
            return True
    return False


def _split_ext(name: str) -> tuple[str, str]:
    import ntpath
    _, ext = ntpath.splitext(name)
    return name, ext


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
