from __future__ import annotations

import hashlib
from typing import Any

from ..db import get_connection, now_str

ACTIVE = "active"
CONFLICT = "conflict"
ORPHANED = "orphaned"
SUPERSEDED = "superseded"


def member_slices_for_rows(rows: list[dict]) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for row in rows:
        report_date = str(row.get("report_date") or "")[:10]
        activity_id = int(row.get("id") or row.get("activity_id") or 0)
        slice_start = str(row.get("start_time") or "")
        slice_end = str(row.get("end_time") or "")
        if not report_date or activity_id <= 0 or not slice_start or not slice_end:
            continue
        members.append(
            {
                "report_date": report_date,
                "activity_id": activity_id,
                "slice_start_time": slice_start,
                "slice_end_time": slice_end,
            }
        )
    return members


def activity_member_hash(report_date: str, members: list[dict[str, Any]]) -> str:
    parts = []
    for member in sorted(
        members,
        key=lambda item: (
            str(item.get("report_date") or ""),
            int(item.get("activity_id") or 0),
            str(item.get("slice_start_time") or ""),
            str(item.get("slice_end_time") or ""),
        ),
    ):
        parts.append(
            "|".join(
                (
                    str(report_date),
                    str(int(member.get("activity_id") or 0)),
                    str(member.get("slice_start_time") or ""),
                    str(member.get("slice_end_time") or ""),
                )
            )
        )
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def attach_overrides(sessions: list[dict]) -> list[dict]:
    if not sessions:
        return sessions
    _refresh_match_states(sessions)
    dates = sorted({str(session.get("report_date") or "") for session in sessions if session.get("report_date")})
    if not dates:
        return sessions
    placeholders = ",".join("?" for _ in dates)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT o.*, p.name AS project_name, p.description AS project_description
            FROM project_session_override o
            LEFT JOIN project p ON p.id = o.project_id
            WHERE o.match_state = ?
              AND o.report_date IN ({placeholders})
            """,
            [ACTIVE, *dates],
        ).fetchall()
    by_key = {
        (str(row["report_date"]), str(row["activity_member_hash"])): dict(row)
        for row in rows
    }
    for session in sessions:
        key = (str(session.get("report_date") or ""), str(session.get("activity_member_hash") or ""))
        override = by_key.get(key)
        if not override:
            session["override_id"] = None
            session["override_match_state"] = None
            session["has_project_override"] = False
            session["has_duration_override"] = False
            session.setdefault("session_note", "")
            continue
        _apply_override(session, override)
    return sessions


def upsert_session_override(
    session: dict,
    *,
    project_id: int | None,
    adjusted_duration_seconds: int | None,
    note: str,
) -> int | None:
    report_date = str(session.get("report_date") or "")
    member_hash = str(session.get("activity_member_hash") or "")
    members = list(session.get("member_slices") or [])
    anchor_activity_id = int(session.get("anchor_activity_id") or session.get("first_activity_id") or 0)
    raw_duration = int(session.get("raw_duration_seconds") or session.get("duration_seconds") or 0)
    note = str(note or "")
    has_project = project_id is not None
    has_duration = adjusted_duration_seconds is not None
    if not report_date or not member_hash or not members or anchor_activity_id <= 0:
        raise ValueError("invalid_session_identity")
    with get_connection() as conn:
        existing = conn.execute(
            """
            SELECT id
            FROM project_session_override
            WHERE report_date = ?
              AND activity_member_hash = ?
              AND match_state = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (report_date, member_hash, ACTIVE),
        ).fetchone()
        if not (has_project or has_duration or note):
            if existing:
                conn.execute(
                    "DELETE FROM project_session_override WHERE id = ?",
                    (int(existing["id"]),),
                )
            return None
        _supersede_overlapping_overrides(conn, members, existing_id=int(existing["id"]) if existing else None)
        ts = now_str()
        if existing:
            override_id = int(existing["id"])
            conn.execute(
                """
                UPDATE project_session_override
                SET anchor_activity_id = ?,
                    original_start_time = ?,
                    original_end_time = ?,
                    original_raw_duration_seconds = ?,
                    project_id = ?,
                    adjusted_duration_seconds = ?,
                    note = ?,
                    match_state = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    anchor_activity_id,
                    str(session.get("start_time") or ""),
                    str(session.get("end_time") or ""),
                    raw_duration,
                    project_id,
                    adjusted_duration_seconds,
                    note,
                    ACTIVE,
                    ts,
                    override_id,
                ),
            )
            conn.execute(
                "DELETE FROM project_session_override_member WHERE override_id = ?",
                (override_id,),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO project_session_override(
                    report_date, activity_member_hash, anchor_activity_id,
                    original_start_time, original_end_time, original_raw_duration_seconds,
                    project_id, adjusted_duration_seconds, note, match_state,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_date,
                    member_hash,
                    anchor_activity_id,
                    str(session.get("start_time") or ""),
                    str(session.get("end_time") or ""),
                    raw_duration,
                    project_id,
                    adjusted_duration_seconds,
                    note,
                    ACTIVE,
                    ts,
                    ts,
                ),
            )
            override_id = int(cur.lastrowid)
        for member in members:
            conn.execute(
                """
                INSERT INTO project_session_override_member(
                    override_id, activity_id, report_date, slice_start_time, slice_end_time
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    override_id,
                    int(member["activity_id"]),
                    str(member["report_date"]),
                    str(member["slice_start_time"]),
                    str(member["slice_end_time"]),
                ),
            )
        return override_id


def _apply_override(session: dict, override: dict) -> None:
    session["override_id"] = int(override["id"])
    session["override_match_state"] = str(override["match_state"] or ACTIVE)
    if override.get("project_id") is not None:
        session["project_id"] = int(override["project_id"])
        session["project_name"] = str(override.get("project_name") or "")
        session["project_description"] = str(override.get("project_description") or "")
        session["has_project_override"] = True
        session["is_report_project"] = True
        session["is_report_classified"] = True
        session["is_report_uncategorized"] = False
        session["is_classified"] = True
        session["is_uncategorized"] = False
    else:
        session["has_project_override"] = False
    if override.get("adjusted_duration_seconds") is not None:
        adjusted = int(override["adjusted_duration_seconds"])
        session["adjusted_duration_seconds"] = adjusted
        session["display_duration_seconds"] = adjusted
        session["duration_seconds"] = adjusted
        session["has_duration_override"] = True
    else:
        session["adjusted_duration_seconds"] = None
        session["has_duration_override"] = False
    session["session_note"] = str(override.get("note") or "")


def _refresh_match_states(sessions: list[dict]) -> None:
    dates = sorted({str(session.get("report_date") or "") for session in sessions if session.get("report_date")})
    if not dates:
        return
    current_hashes = {
        (str(session.get("report_date") or ""), str(session.get("activity_member_hash") or ""))
        for session in sessions
    }
    member_to_hash: dict[tuple[str, int, str, str], str] = {}
    for session in sessions:
        session_hash = str(session.get("activity_member_hash") or "")
        for member in session.get("member_slices") or []:
            member_to_hash[_member_key(member)] = session_hash
    placeholders = ",".join("?" for _ in dates)
    with get_connection() as conn:
        overrides = conn.execute(
            f"""
            SELECT *
            FROM project_session_override
            WHERE match_state = ?
              AND report_date IN ({placeholders})
            """,
            [ACTIVE, *dates],
        ).fetchall()
        for override in overrides:
            key = (str(override["report_date"]), str(override["activity_member_hash"]))
            if key in current_hashes:
                continue
            members = conn.execute(
                """
                SELECT activity_id, report_date, slice_start_time, slice_end_time
                FROM project_session_override_member
                WHERE override_id = ?
                """,
                (int(override["id"]),),
            ).fetchall()
            found_hashes = {
                member_to_hash[_member_key(dict(member))]
                for member in members
                if _member_key(dict(member)) in member_to_hash
            }
            new_state = ORPHANED if not found_hashes else CONFLICT
            conn.execute(
                """
                UPDATE project_session_override
                SET match_state = ?, updated_at = ?
                WHERE id = ? AND match_state = ?
                """,
                (new_state, now_str(), int(override["id"]), ACTIVE),
            )


def _supersede_overlapping_overrides(conn, members: list[dict[str, Any]], existing_id: int | None) -> None:
    if not members:
        return
    seen_ids: set[int] = set()
    for member in members:
        rows = conn.execute(
            """
            SELECT override_id
            FROM project_session_override_member
            WHERE activity_id = ?
              AND report_date = ?
              AND slice_start_time = ?
              AND slice_end_time = ?
            """,
            (
                int(member["activity_id"]),
                str(member["report_date"]),
                str(member["slice_start_time"]),
                str(member["slice_end_time"]),
            ),
        ).fetchall()
        for row in rows:
            oid = int(row["override_id"])
            if existing_id is not None and oid == existing_id:
                continue
            seen_ids.add(oid)
    if not seen_ids:
        return
    placeholders = ",".join("?" for _ in seen_ids)
    conn.execute(
        f"""
        UPDATE project_session_override
        SET match_state = ?, updated_at = ?
        WHERE id IN ({placeholders})
          AND match_state IN (?, ?)
        """,
        [SUPERSEDED, now_str(), *sorted(seen_ids), ACTIVE, CONFLICT],
    )


def _member_key(member: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(member.get("report_date") or ""),
        int(member.get("activity_id") or 0),
        str(member.get("slice_start_time") or ""),
        str(member.get("slice_end_time") or ""),
    )
