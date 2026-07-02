from __future__ import annotations

from ..db import get_connection, now_str


def session_note_key(session: dict) -> tuple[str, int] | None:
    report_date = str(session.get("report_date") or session.get("start_time") or "")[:10]
    activity_ids = [int(value) for value in session.get("activity_ids") or []]
    if not report_date or not activity_ids:
        return None
    return report_date, int(activity_ids[0])


# Note-only accessors (read/write only the note field).


def get_session_note(report_date: str, first_activity_id: int) -> str:
    fields = get_session_user_fields(report_date, first_activity_id)
    return fields["note"]


def set_session_note(report_date: str, first_activity_id: int, note: str) -> None:
    """Note-only write that preserves any existing duration override.

    The row is deleted only when ``note`` is empty AND
    ``adjusted_duration_seconds`` is ``None``; an empty note alone does
    not destroy an existing duration override.
    """
    existing = get_session_user_fields(report_date, first_activity_id)
    set_session_user_fields(
        report_date,
        first_activity_id,
        note,
        existing["adjusted_duration_seconds"],
    )


def attach_session_notes(sessions: list[dict]) -> list[dict]:
    """Attach only ``session_note`` to each session dict."""
    fields_map = _user_fields_for_sessions(sessions)
    for session in sessions:
        key = session_note_key(session)
        fields = fields_map.get(key, {}) if key is not None else {}
        session["session_note"] = fields.get("note", "")
        session["first_activity_id"] = key[1] if key is not None else None
    return sessions


# Unified "user fields" API: note + adjusted duration.


def get_session_user_fields(report_date: str, first_activity_id: int) -> dict:
    """Return ``{"note": str, "adjusted_duration_seconds": int | None}``.

    Returns ``{"note": "", "adjusted_duration_seconds": None}`` when no row
    exists for the given ``(report_date, first_activity_id)``.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT note, adjusted_duration_seconds
            FROM project_session_note
            WHERE report_date = ? AND first_activity_id = ?
            """,
            (report_date, int(first_activity_id)),
        ).fetchone()
    if not row:
        return {"note": "", "adjusted_duration_seconds": None}
    return {
        "note": str(row["note"] or ""),
        "adjusted_duration_seconds": int(row["adjusted_duration_seconds"]) if row["adjusted_duration_seconds"] is not None else None,
    }


def set_session_user_fields(
    report_date: str,
    first_activity_id: int,
    note: str,
    adjusted_duration_seconds: int | None,
) -> None:
    """Write note and adjusted duration for a session.

    Semantics:
    - ``note`` is stripped; whitespace-only is treated as empty.
    - ``adjusted_duration_seconds`` may be ``None`` (no override / clear
      override) or a non-negative integer (``0`` is a valid explicit
      override to zero display/declared duration).
    - The row is deleted only when BOTH ``note`` is empty AND
      ``adjusted_duration_seconds`` is ``None``. This prevents an empty
      note from destroying an existing duration override.
    """
    cleaned_note = str(note or "").strip()
    duration_value: int | None = None
    if adjusted_duration_seconds is not None:
        duration_value = int(adjusted_duration_seconds)

    with get_connection() as conn:
        if not cleaned_note and duration_value is None:
            conn.execute(
                "DELETE FROM project_session_note WHERE report_date = ? AND first_activity_id = ?",
                (report_date, int(first_activity_id)),
            )
            return
        ts = now_str()
        conn.execute(
            """
            INSERT INTO project_session_note(
                report_date, first_activity_id, note, adjusted_duration_seconds,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_date, first_activity_id) DO UPDATE SET
                note = excluded.note,
                adjusted_duration_seconds = excluded.adjusted_duration_seconds,
                updated_at = excluded.updated_at
            """,
            (report_date, int(first_activity_id), cleaned_note, duration_value, ts, ts),
        )


def attach_session_user_fields(sessions: list[dict]) -> list[dict]:
    """Attach note + duration fields to each session dict.

    For each session the following keys are set:
    - ``session_note``: str
    - ``first_activity_id``: int | None
    - ``adjusted_duration_seconds``: int | None
    - ``has_duration_override``: bool
    - ``raw_duration_seconds``: int (the original ``duration_seconds``)
    - ``display_duration_seconds``: int (override if set, else raw)
    """
    fields_map = _user_fields_for_sessions(sessions)
    for session in sessions:
        key = session_note_key(session)
        fields = fields_map.get(key, {}) if key is not None else {}
        raw = int(session.get("duration_seconds") or 0)
        adjusted = fields.get("adjusted_duration_seconds")
        if adjusted is not None:
            adjusted = int(adjusted)
        has_override = adjusted is not None
        display = adjusted if has_override else raw
        session["session_note"] = fields.get("note", "")
        session["first_activity_id"] = key[1] if key is not None else None
        session["adjusted_duration_seconds"] = adjusted
        session["has_duration_override"] = has_override
        session["raw_duration_seconds"] = raw
        session["display_duration_seconds"] = display
    return sessions


# Internal helpers


def _user_fields_for_sessions(sessions: list[dict]) -> dict[tuple[str, int], dict]:
    keys = [session_note_key(session) for session in sessions]
    clean_keys = [key for key in keys if key is not None]
    return _fields_for_keys(clean_keys)


def _fields_for_keys(keys: list[tuple[str, int]]) -> dict[tuple[str, int], dict]:
    if not keys:
        return {}
    clauses = " OR ".join("(report_date = ? AND first_activity_id = ?)" for _ in keys)
    params = [value for key in keys for value in key]
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT report_date, first_activity_id, note, adjusted_duration_seconds
            FROM project_session_note
            WHERE {clauses}
            """,
            params,
        ).fetchall()
    return {
        (str(row["report_date"]), int(row["first_activity_id"])): {
            "note": str(row["note"] or ""),
            "adjusted_duration_seconds": int(row["adjusted_duration_seconds"])
            if row["adjusted_duration_seconds"] is not None
            else None,
        }
        for row in rows
    }
