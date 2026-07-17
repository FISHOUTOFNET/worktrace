"""Semantic normalization and validation for a secure-backup staging DB."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import sqlite3
from typing import Any

from ..constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)
from ..db import CURRENT_SCHEMA_VERSION, expected_schema_fingerprint, schema_fingerprint
from ..domain_limits import NOTE_MAX_LENGTH

_ALLOWED_ACTIVITY_STATUSES = {
    STATUS_NORMAL,
    STATUS_IDLE,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_PAUSED,
}


class BackupValidationError(ValueError):
    pass


def validate_staging_database(conn: sqlite3.Connection) -> None:
    """Normalize restore-only runtime state, then validate all semantics."""

    # The durable structural generation is installation-local technical state,
    # not portable business data. Recreate it at the restore ingress inside the
    # caller's transaction; executescript() is intentionally avoided because it
    # would commit before semantic validation finishes.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS report_structure_revision_state (
            singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
            generation INTEGER NOT NULL CHECK(generation >= 0)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO report_structure_revision_state(singleton_id, generation)
        VALUES (1, 0)
        ON CONFLICT(singleton_id) DO NOTHING
        """
    )
    if int(conn.execute("PRAGMA user_version").fetchone()[0] or 0) != CURRENT_SCHEMA_VERSION:
        raise BackupValidationError("schema version")
    if schema_fingerprint(conn) != expected_schema_fingerprint():
        raise BackupValidationError("schema fingerprint")

    # An open row belongs to the exporting process generation and cannot remain
    # open after a replace import. Seal it at start + already-observed duration;
    # this preserves recorded work without using the importing machine's clock.
    _seal_imported_open_activity_rows(conn)

    if conn.execute("PRAGMA foreign_key_check").fetchone():
        raise BackupValidationError("foreign key")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()
    if integrity is None or str(integrity[0]).lower() != "ok":
        raise BackupValidationError("integrity")
    _validate_activity_rows(conn)
    _validate_operation_graph(conn)
    _validate_replay_records(conn)


def _seal_imported_open_activity_rows(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, start_time, duration_seconds
        FROM activity_log
        WHERE end_time IS NULL
        ORDER BY id
        """
    ).fetchall()
    for row in rows:
        try:
            start = datetime.strptime(str(row["start_time"] or ""), TIME_FORMAT)
            duration = max(0, int(row["duration_seconds"] or 0))
        except (TypeError, ValueError) as exc:
            raise BackupValidationError("activity encoding") from exc
        end = start + timedelta(seconds=duration)
        conn.execute(
            """
            UPDATE activity_log
            SET end_time = ?, duration_seconds = ?
            WHERE id = ? AND end_time IS NULL
            """,
            (end.strftime(TIME_FORMAT), duration, int(row["id"])),
        )


def _validate_activity_rows(conn: sqlite3.Connection) -> None:
    """Validate activity intervals and duration semantics."""
    for row in conn.execute(
        "SELECT id, start_time, end_time, duration_seconds, status "
        "FROM activity_log ORDER BY id"
    ).fetchall():
        try:
            start = datetime.strptime(str(row["start_time"] or ""), TIME_FORMAT)
            end_raw = row["end_time"]
            end = (
                datetime.strptime(str(end_raw), TIME_FORMAT)
                if end_raw is not None
                else None
            )
            duration_raw = row["duration_seconds"]
            duration = int(duration_raw) if duration_raw is not None else None
        except (TypeError, ValueError) as exc:
            raise BackupValidationError("activity encoding") from exc
        if str(row["status"] or "") not in _ALLOWED_ACTIVITY_STATUSES:
            raise BackupValidationError("activity status")
        if duration is not None and duration < 0:
            raise BackupValidationError("negative duration")
        if end is None:
            raise BackupValidationError("open activity after normalization")
        if duration is None:
            raise BackupValidationError("closed activity missing duration")
        wall_seconds = int((end - start).total_seconds())
        if wall_seconds < 0 or duration < wall_seconds:
            raise BackupValidationError("closed activity interval")


def _validate_replay_records(conn: sqlite3.Connection) -> None:
    from .report_projection_snapshot_service import build_visible_snapshot
    from .report_session_operation_engine import APPLIED, SUPERSEDED_BY_UNDO

    dates = conn.execute(
        """
        SELECT report_date FROM report_session_operation
        UNION
        SELECT substr(start_time, 1, 10) FROM activity_log WHERE length(start_time) >= 10
        UNION
        SELECT substr(end_time, 1, 10) FROM activity_log
        WHERE end_time IS NOT NULL AND length(end_time) >= 10
        ORDER BY 1
        """
    ).fetchall()
    try:
        for date_row in dates:
            report_date = str(date_row[0] or "")
            datetime.strptime(report_date, "%Y-%m-%d")
            for row in conn.execute(
                "SELECT * FROM report_session_operation "
                "WHERE report_date = ? ORDER BY sequence, id",
                (report_date,),
            ).fetchall():
                operation = dict(row)
                operation["payload"] = json.loads(
                    str(operation.pop("payload_json"))
                )
                _validate_operation_payload(operation, conn)
            snapshot = build_visible_snapshot(report_date, report_date, conn=conn)
            invalid = [
                item
                for item in snapshot.operation_diagnostics
                if item.state not in {APPLIED, SUPERSEDED_BY_UNDO}
            ]
            if invalid:
                raise BackupValidationError("operation replay")
    except BackupValidationError:
        raise
    except Exception as exc:
        raise BackupValidationError("operation replay") from exc


def _validate_operation_payload(
    operation: dict[str, Any],
    conn: sqlite3.Connection,
) -> None:
    payload = operation.get("payload")
    if not isinstance(payload, dict) or payload.get("payload_version") != 4:
        raise BackupValidationError("operation payload version")
    operation_type = str(operation.get("operation_type") or "")
    allowed = {"payload_version"}
    if operation_type == "edit_session":
        allowed |= {"project", "duration", "note"}
        if not any(key in payload for key in ("project", "duration", "note")):
            raise BackupValidationError("empty edit")
        project = payload.get("project")
        if project is not None:
            if not isinstance(project, dict) or set(project) - {"mode", "project_id"}:
                raise BackupValidationError("project patch")
            if project.get("mode") == "set":
                project_id = project.get("project_id")
                if not isinstance(project_id, int) or not conn.execute(
                    "SELECT 1 FROM project WHERE id = ?",
                    (project_id,),
                ).fetchone():
                    raise BackupValidationError("project reference")
            elif project.get("mode") != "inherit":
                raise BackupValidationError("project mode")
        duration = payload.get("duration")
        if duration is not None:
            if not isinstance(duration, dict) or set(duration) - {"mode", "value"}:
                raise BackupValidationError("duration patch")
            if duration.get("mode") == "set":
                if (
                    not isinstance(duration.get("value"), int)
                    or duration["value"] < 0
                ):
                    raise BackupValidationError("duration value")
            elif duration.get("mode") != "inherit":
                raise BackupValidationError("duration mode")
        note = payload.get("note")
        if note is not None:
            if not isinstance(note, dict) or set(note) - {"mode", "value"}:
                raise BackupValidationError("note patch")
            if note.get("mode") == "set":
                note_value = note.get("value")
                if not isinstance(note_value, str):
                    raise BackupValidationError("note value")
                if len(note_value) > NOTE_MAX_LENGTH:
                    raise BackupValidationError("note value length")
            elif note.get("mode") != "inherit":
                raise BackupValidationError("note mode")
    elif operation_type == "hide_activity":
        allowed |= {"summary_id"}
        if not isinstance(payload.get("summary_id"), str) or not payload["summary_id"]:
            raise BackupValidationError("summary id")
    elif operation_type not in {
        "hide_session",
        "copy_session",
        "merge_sessions",
        "split_session",
    }:
        raise BackupValidationError("operation type")
    if set(payload) - allowed:
        raise BackupValidationError("unknown payload field")


def _validate_operation_graph(conn: sqlite3.Connection) -> None:
    checks = (
        """
        SELECT 1 FROM report_mutation_request r
        LEFT JOIN report_session_operation o ON o.id = r.operation_id
        WHERE r.operation_id IS NOT NULL AND o.id IS NULL LIMIT 1
        """,
        """
        SELECT 1 FROM report_mutation_request
        WHERE json_valid(result_json) = 0
           OR (outcome_type = 'operation_committed') <> (operation_id IS NOT NULL)
        LIMIT 1
        """,
        """
        SELECT 1 FROM report_session_operation o
        WHERE json_valid(o.payload_json) = 0
           OR NOT EXISTS (
                SELECT 1 FROM report_session_operation_member m
                WHERE m.operation_id = o.id AND m.role = 'source'
           )
           OR (o.operation_type = 'merge_sessions' AND NOT EXISTS (
                SELECT 1 FROM report_session_operation_member m
                WHERE m.operation_id = o.id AND m.role = 'target'
           ))
           OR (o.operation_type = 'split_session' AND NOT EXISTS (
                SELECT 1 FROM report_session_operation m
                WHERE m.id = o.undo_of_operation_id
                  AND m.operation_type = 'merge_sessions'
                  AND m.report_date = o.report_date
                  AND m.sequence < o.sequence
           ))
        LIMIT 1
        """,
        """
        SELECT 1 FROM report_session_operation
        GROUP BY report_date, sequence HAVING COUNT(*) > 1 LIMIT 1
        """,
    )
    for sql in checks:
        if conn.execute(sql).fetchone():
            raise BackupValidationError("operation graph")


__all__ = ["BackupValidationError", "validate_staging_database"]
