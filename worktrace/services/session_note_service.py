from __future__ import annotations

from ..db import get_connection, now_str


def session_note_key(session: dict) -> tuple[str, int] | None:
    report_date = str(session.get("report_date") or session.get("start_time") or "")[:10]
    activity_ids = [int(value) for value in session.get("activity_ids") or []]
    if not report_date or not activity_ids:
        return None
    return report_date, int(activity_ids[0])


def get_session_note(report_date: str, first_activity_id: int) -> str:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT note
            FROM project_session_note
            WHERE report_date = ? AND first_activity_id = ?
            """,
            (report_date, int(first_activity_id)),
        ).fetchone()
    return str(row["note"] or "") if row else ""


def set_session_note(report_date: str, first_activity_id: int, note: str) -> None:
    cleaned = str(note or "").strip()
    with get_connection() as conn:
        if not cleaned:
            conn.execute(
                "DELETE FROM project_session_note WHERE report_date = ? AND first_activity_id = ?",
                (report_date, int(first_activity_id)),
            )
            return
        ts = now_str()
        conn.execute(
            """
            INSERT INTO project_session_note(report_date, first_activity_id, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(report_date, first_activity_id) DO UPDATE SET
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (report_date, int(first_activity_id), cleaned, ts, ts),
        )


def attach_session_notes(sessions: list[dict]) -> list[dict]:
    keys = [session_note_key(session) for session in sessions]
    clean_keys = [key for key in keys if key is not None]
    notes = _notes_for_keys(clean_keys)
    for session, key in zip(sessions, keys):
        note = notes.get(key, "") if key is not None else ""
        session["session_note"] = note
        session["first_activity_id"] = key[1] if key is not None else None
    return sessions


def _notes_for_keys(keys: list[tuple[str, int]]) -> dict[tuple[str, int], str]:
    if not keys:
        return {}
    clauses = " OR ".join("(report_date = ? AND first_activity_id = ?)" for _ in keys)
    params = [value for key in keys for value in key]
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT report_date, first_activity_id, note
            FROM project_session_note
            WHERE {clauses}
            """,
            params,
        ).fetchall()
    return {
        (str(row["report_date"]), int(row["first_activity_id"])): str(row["note"] or "")
        for row in rows
    }
