"""Versioned, restartable repair of missing durable activity-resource facts."""

from __future__ import annotations

import json
import logging
from typing import Any

from ..constants import STATUS_ERROR, STATUS_EXCLUDED, STATUS_IDLE, STATUS_PAUSED
from ..db import get_connection, now_str
from ..platforms.base import ActiveWindow
from ..resources.detectors import detect_resource
from ..resources.resource_builders import make_system_resource
from ..resources.types import DetectedResource
from .resource_service import create_or_update_activity_resource

DEFAULT_BATCH_SIZE = 200
REPAIR_POLICY_VERSION = 1
REPAIR_STATE_KEY = "maintenance.activity_resource_repair.v1"
_VALID_STATUSES = {"pending", "running", "completed", "failed"}


def _default_state() -> dict[str, Any]:
    return {
        "policy_version": REPAIR_POLICY_VERSION,
        "status": "pending",
        "cursor_activity_id": 0,
        "scanned_count": 0,
        "repaired_count": 0,
        "unknown_count": 0,
        "error_count": 0,
        "last_error": "",
        "started_at": "",
        "completed_at": "",
        "updated_at": "",
    }


def get_activity_fact_repair_state(*, conn=None) -> dict[str, Any]:
    """Return validated durable repair progress for diagnostics and startup gates."""

    if conn is None:
        with get_connection() as read_conn:
            return get_activity_fact_repair_state(conn=read_conn)
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (REPAIR_STATE_KEY,),
    ).fetchone()
    if row is None:
        return _default_state()
    try:
        raw = json.loads(str(row["value"] or ""))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("data_repair_state_invalid") from exc
    if not isinstance(raw, dict):
        raise ValueError("data_repair_state_invalid")
    if int(raw.get("policy_version") or 0) != REPAIR_POLICY_VERSION:
        return _default_state()
    status = str(raw.get("status") or "")
    if status not in _VALID_STATUSES:
        raise ValueError("data_repair_state_invalid")
    state = _default_state()
    state.update(
        {
            "status": status,
            "cursor_activity_id": max(0, int(raw.get("cursor_activity_id") or 0)),
            "scanned_count": max(0, int(raw.get("scanned_count") or 0)),
            "repaired_count": max(0, int(raw.get("repaired_count") or 0)),
            "unknown_count": max(0, int(raw.get("unknown_count") or 0)),
            "error_count": max(0, int(raw.get("error_count") or 0)),
            "last_error": str(raw.get("last_error") or ""),
            "started_at": str(raw.get("started_at") or ""),
            "completed_at": str(raw.get("completed_at") or ""),
            "updated_at": str(raw.get("updated_at") or ""),
        }
    )
    return state


def repair_missing_activity_resources(batch_size: int = DEFAULT_BATCH_SIZE) -> int:
    """Persist all missing resource facts under a versioned, resumable policy."""

    size = max(1, int(batch_size))
    first_missing_id = _first_unrepaired_activity_id()
    try:
        state = get_activity_fact_repair_state()
    except ValueError:
        logging.exception("activity resource repair state was invalid; restarting policy")
        state = _default_state()

    if first_missing_id is None:
        if state["status"] != "completed":
            state["status"] = "completed"
            state["completed_at"] = now_str()
            state["last_error"] = ""
            _persist_state(state)
        return 0

    if state["status"] == "completed":
        state = _default_state()

    initial_repaired_count = int(state["repaired_count"])
    state["status"] = "running"
    state["started_at"] = str(state["started_at"] or now_str())
    state["completed_at"] = ""
    state["last_error"] = ""
    _persist_state(state)

    reset_cursor_once = False
    try:
        while True:
            rows = _load_missing_rows_after(
                int(state["cursor_activity_id"]),
                size,
            )
            if not rows:
                remaining_id = _first_unrepaired_activity_id()
                if (
                    remaining_id is not None
                    and remaining_id <= int(state["cursor_activity_id"])
                    and not reset_cursor_once
                ):
                    state["cursor_activity_id"] = 0
                    reset_cursor_once = True
                    _persist_state(state)
                    continue
                if remaining_id is not None:
                    raise RuntimeError("activity_resource_repair_cursor_inconsistent")
                state["status"] = "completed"
                state["completed_at"] = now_str()
                state["last_error"] = ""
                _persist_state(state)
                return int(state["repaired_count"]) - initial_repaired_count

            prepared: list[tuple[int, DetectedResource, bool, bool]] = []
            for row in rows:
                resource, detection_failed = _resource_for_row(row)
                prepared.append(
                    (
                        int(row["id"]),
                        resource,
                        resource.resource_kind == "unknown",
                        detection_failed,
                    )
                )

            with get_connection() as conn:
                for activity_id, resource, _is_unknown, _failed in prepared:
                    create_or_update_activity_resource(activity_id, resource, conn=conn)
                state["cursor_activity_id"] = int(prepared[-1][0])
                state["scanned_count"] = int(state["scanned_count"]) + len(prepared)
                state["repaired_count"] = int(state["repaired_count"]) + len(prepared)
                state["unknown_count"] = int(state["unknown_count"]) + sum(
                    1 for _activity_id, _resource, is_unknown, _failed in prepared if is_unknown
                )
                state["error_count"] = int(state["error_count"]) + sum(
                    1 for _activity_id, _resource, _is_unknown, failed in prepared if failed
                )
                _write_state(conn, state)

            logging.info(
                "activity resource repair committed policy=%s batch=%s total=%s cursor=%s",
                REPAIR_POLICY_VERSION,
                len(prepared),
                state["repaired_count"],
                state["cursor_activity_id"],
            )
    except Exception as exc:
        state["status"] = "failed"
        state["last_error"] = f"{type(exc).__name__}: {exc}"
        try:
            _persist_state(state)
        except Exception:
            logging.exception("activity resource repair failure state could not be persisted")
        raise


def require_activity_fact_repair_complete() -> dict[str, Any]:
    """Fail closed while durable resource facts or their repair state are incomplete."""

    state = get_activity_fact_repair_state()
    if state["status"] != "completed" or _first_unrepaired_activity_id() is not None:
        raise ValueError("data_repair_required")
    return state


def _persist_state(state: dict[str, Any]) -> None:
    with get_connection() as conn:
        _write_state(conn, state)


def _write_state(conn, state: dict[str, Any]) -> None:
    state["updated_at"] = now_str()
    conn.execute(
        """
        INSERT INTO settings(key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (
            REPAIR_STATE_KEY,
            json.dumps(state, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            state["updated_at"],
        ),
    )


def _first_unrepaired_activity_id() -> int | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT MIN(a.id) AS activity_id
            FROM activity_log a
            LEFT JOIN activity_resource ar ON ar.activity_id = a.id
            WHERE ar.activity_id IS NULL
               OR TRIM(COALESCE(ar.identity_key, '')) = ''
            """
        ).fetchone()
    if row is None or row["activity_id"] is None:
        return None
    return int(row["activity_id"])


def _load_missing_rows_after(cursor_activity_id: int, limit: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.app_name, a.process_name, a.window_title,
                   a.file_path_hint, a.start_time, a.status
            FROM activity_log a
            LEFT JOIN activity_resource ar ON ar.activity_id = a.id
            WHERE (ar.activity_id IS NULL OR TRIM(COALESCE(ar.identity_key, '')) = '')
              AND a.id > ?
            ORDER BY a.id
            LIMIT ?
            """,
            (max(0, int(cursor_activity_id)), int(limit)),
        ).fetchall()
    return [dict(row) for row in rows]


def _resource_for_row(row: dict[str, Any]) -> tuple[DetectedResource, bool]:
    status = str(row.get("status") or "")
    app_name = str(row.get("app_name") or "")
    process_name = str(row.get("process_name") or "")
    window_title = str(row.get("window_title") or "")
    if status == STATUS_EXCLUDED:
        return make_system_resource(STATUS_EXCLUDED), False
    if status in {STATUS_IDLE, STATUS_PAUSED, STATUS_ERROR}:
        return make_system_resource(status, app_name, process_name, window_title), False
    try:
        resource = detect_resource(
            ActiveWindow(
                app_name=app_name,
                process_name=process_name,
                window_title=window_title,
                file_path_hint=row.get("file_path_hint"),
                activity_start_time=str(row.get("start_time") or "") or None,
            )
        )
        if not str(resource.identity_key or "").strip():
            logging.warning(
                "activity resource repair produced empty identity activity_id=%s policy=%s",
                int(row.get("id") or 0),
                REPAIR_POLICY_VERSION,
            )
            return _unknown_resource(row), True
        return resource, False
    except Exception:
        logging.exception(
            "activity resource repair detection failed activity_id=%s policy=%s",
            int(row.get("id") or 0),
            REPAIR_POLICY_VERSION,
        )
        return _unknown_resource(row), True


def _unknown_resource(row: dict[str, Any]) -> DetectedResource:
    activity_id = int(row.get("id") or 0)
    app_name = str(row.get("app_name") or "")
    process_name = str(row.get("process_name") or "")
    display_name = app_name or process_name or "未知"
    return DetectedResource(
        resource_kind="unknown",
        resource_subtype="unknown",
        display_name=display_name,
        identity_key=f"activity:{activity_id}",
        is_anchor=False,
        confidence=0,
        source=f"repair_v{REPAIR_POLICY_VERSION}_unknown",
        app_name=app_name,
        process_name=process_name,
        window_title="",
    )


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "REPAIR_POLICY_VERSION",
    "REPAIR_STATE_KEY",
    "get_activity_fact_repair_state",
    "repair_missing_activity_resources",
    "require_activity_fact_repair_complete",
]
