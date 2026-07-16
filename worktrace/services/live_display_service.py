"""Display-safe helpers for the unified Activity Display Model."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from ..constants import (
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    UNCATEGORIZED_PROJECT,
)
from ..contracts.live_display_contracts import (
    ActivitySnapshotContract,
    CurrentActivityContract,
)
from . import activity_service, timeline_service
from .live_time_service import (
    safe_int,
    snapshot_elapsed_seconds,
    snapshot_persisted_id,
    snapshot_seconds_for_date_range,
    snapshot_start_time,
)
from .project_attribution_policy import is_official_project_source
from .settings_service import get_setting

_MAX_LIVE_DURATION_SECONDS = 36 * 60 * 60


def _snapshot_status(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return ""
    return str(snapshot.get("status") or "")


def classify_live_state(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return "none"
    status = _snapshot_status(snapshot)
    if status == STATUS_PAUSED:
        return "paused"
    if status == STATUS_IDLE:
        return "idle"
    if status == STATUS_EXCLUDED:
        return "excluded"
    if status == STATUS_ERROR:
        return "error"
    if status != STATUS_NORMAL:
        return "none"
    if bool(snapshot.get("is_persisted")) or snapshot_persisted_id(snapshot):
        return "persisted_open"
    return "none"


def is_live_eligible_for_normal(
    snapshot: ActivitySnapshotContract | None,
    report_date: str | None,
    today: str | None,
) -> bool:
    if not snapshot or _snapshot_status(snapshot) != STATUS_NORMAL:
        return False
    if classify_live_state(snapshot) != "persisted_open":
        return False
    return bool(report_date and today and report_date == today)


def _snapshot_total_seconds(snapshot: ActivitySnapshotContract | None) -> int:
    return snapshot_elapsed_seconds(snapshot)


def _display_resource_name(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return "未知"
    name = (
        snapshot.get("resource_display_name")
        or snapshot.get("activity_display_name")
        or snapshot.get("app_name")
        or snapshot.get("process_name")
    )
    return str(name or "未知").strip() or "未知"


def _display_app_name(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return ""
    return str(snapshot.get("app_name") or "").strip()


def _snapshot_display_project_dict(
    snapshot: ActivitySnapshotContract | None,
) -> dict[str, Any] | None:
    if not snapshot:
        return None
    value = snapshot.get("display_project")
    return value if isinstance(value, dict) and value else None


def _official_project_name_for_persisted_row(activity_id: int) -> str:
    try:
        from .project_inference_service import get_assignment_for_activity

        assignment = get_assignment_for_activity(activity_id)
    except Exception:
        return ""
    if not assignment:
        return ""
    source = str(assignment.get("source") or "").strip()
    if not is_official_project_source(source):
        return ""
    project_id = assignment.get("project_id")
    if project_id is None:
        return ""
    from ..db import get_connection

    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT name FROM project WHERE id = ?", (int(project_id),)
            ).fetchone()
    except Exception:
        return ""
    name = str(row["name"]).strip() if row else ""
    return name if name and name != UNCATEGORIZED_PROJECT else ""


def _display_project_name(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return UNCATEGORIZED_PROJECT
    display_project = _snapshot_display_project_dict(snapshot)
    if display_project and is_official_project_source(
        str(display_project.get("source") or "")
    ):
        name = str(display_project.get("name") or "").strip()
        if name:
            return name
    persisted_id = snapshot_persisted_id(snapshot)
    if persisted_id:
        official = _official_project_name_for_persisted_row(int(persisted_id))
        if official:
            return official
    return UNCATEGORIZED_PROJECT


def _display_project_description(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return ""
    display_project = _snapshot_display_project_dict(snapshot)
    if display_project and is_official_project_source(
        str(display_project.get("source") or "")
    ):
        return str(display_project.get("description") or "")
    project_name = _display_project_name(snapshot)
    if project_name and project_name != UNCATEGORIZED_PROJECT:
        from . import project_service

        existing = project_service.get_project_by_name(project_name)
        if existing:
            return str(existing.get("description") or "")
    return ""


def _stable_live_key(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return ""
    return "|".join(
        [
            str(snapshot.get("resource_display_name") or ""),
            str(snapshot.get("activity_display_name") or ""),
            str(snapshot.get("app_name") or ""),
            str(snapshot.get("process_name") or ""),
            str(snapshot.get("start_time") or ""),
            str(snapshot.get("status") or ""),
        ]
    )


def _stable_live_key_hash(snapshot: ActivitySnapshotContract | None) -> str:
    key = _stable_live_key(snapshot)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:12] if key else ""


def _start_time_epoch_ms(snapshot: ActivitySnapshotContract | None) -> int:
    if not snapshot:
        return 0
    start_time = str(snapshot.get("start_time") or "")
    if not start_time:
        return 0
    try:
        value = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0
    return int(value.timestamp() * 1000)


def _live_display_key(snapshot: ActivitySnapshotContract | None) -> str:
    if not snapshot:
        return ""
    return "|".join(
        [
            str(snapshot.get("resource_display_name") or ""),
            str(snapshot.get("activity_display_name") or ""),
            str(snapshot.get("app_name") or ""),
            str(snapshot.get("process_name") or ""),
            str(snapshot.get("start_time") or ""),
            str(snapshot.get("status") or ""),
            "1" if bool(snapshot.get("is_persisted")) else "0",
            str(int(snapshot.get("persisted_activity_id") or 0)),
        ]
    )


def build_current_activity_summary(
    snapshot: ActivitySnapshotContract | None,
    report_date: str | None = None,
    today: str | None = None,
) -> CurrentActivityContract:
    if not snapshot:
        return {
            "active": False,
            "display": "无",
            "elapsed_seconds": 0,
            "resource_elapsed_seconds": 0,
            "is_paused": False,
            "status": "",
            "is_persisted": False,
            "project_name": "",
            "project_id": 0,
            "persisted_activity_id": 0,
            "live_state": "none",
            "is_in_progress": False,
            "is_virtual_live": False,
            "live_display_key": "",
            "stable_live_key": "",
            "stable_live_key_hash": "",
            "live_started_at_epoch_ms": 0,
            "carry_seconds": 0,
            "resource_name": "",
            "app_name": "",
            "start_time": "",
            "end_time": None,
            "activity_id": None,
            "source": "none",
            "is_uncategorized": True,
            "is_classified": False,
            "project_description": "",
            "display_project": None,
        }
    if today is None:
        today = timeline_service.get_default_report_date()
    if report_date is None:
        report_date = today
    live_state = classify_live_state(snapshot)
    elapsed_seconds = _snapshot_total_seconds(snapshot)
    project_name = _display_project_name(snapshot)
    project_description = _display_project_description(snapshot)
    resource_name = _display_resource_name(snapshot)
    app_name = _display_app_name(snapshot)
    start_time = str(snapshot.get("start_time") or "")
    status = _snapshot_status(snapshot)
    is_paused = status == STATUS_PAUSED
    is_persisted = bool(snapshot.get("is_persisted"))
    persisted_id = snapshot_persisted_id(snapshot) or 0
    is_in_progress = live_state == "persisted_open"
    is_uncategorized = not project_name or project_name == UNCATEGORIZED_PROJECT
    carry_seconds = 0
    display_seconds = elapsed_seconds
    display_project = _snapshot_display_project_dict(snapshot) or {
        "id": None,
        "name": project_name,
        "description": project_description,
        "source": "uncategorized",
        "is_uncategorized": is_uncategorized,
        "is_suggested_project": False,
    }
    live_started_at_epoch_ms = _start_time_epoch_ms(snapshot)
    from ..formatters import format_duration

    state_label = "进行中" if is_persisted else "活动状态异常"
    if status == STATUS_IDLE:
        resource_name = "空闲中"
        state_label = "空闲"
    elif status == STATUS_PAUSED:
        state_label = "已暂停"
    elif status == STATUS_EXCLUDED:
        state_label = "已排除"
    elif status == STATUS_ERROR:
        state_label = "异常"
    display = f"{resource_name}｜{project_name}｜{format_duration(display_seconds)}｜{state_label}"
    project_id = display_project.get("id")
    return {
        "active": True,
        "display": display,
        "elapsed_seconds": int(display_seconds),
        "resource_elapsed_seconds": int(snapshot_elapsed_seconds(snapshot)),
        "is_paused": bool(is_paused),
        "status": status,
        "is_persisted": is_persisted,
        "project_name": project_name,
        "project_id": int(project_id) if project_id is not None else 0,
        "persisted_activity_id": int(persisted_id or 0),
        "live_state": live_state,
        "is_in_progress": bool(is_in_progress),
        "is_virtual_live": False,
        "live_display_key": _live_display_key(snapshot),
        "stable_live_key": _stable_live_key(snapshot),
        "stable_live_key_hash": _stable_live_key_hash(snapshot),
        "live_started_at_epoch_ms": int(live_started_at_epoch_ms or 0),
        "carry_seconds": int(carry_seconds),
        "resource_name": resource_name,
        "app_name": app_name,
        "start_time": start_time,
        "end_time": None,
        "activity_id": int(persisted_id or 0) or None,
        "source": "db" if is_in_progress else "none",
        "is_uncategorized": bool(is_uncategorized),
        "is_classified": not bool(is_uncategorized),
        "project_description": project_description,
        "display_project": display_project,
    }


def _snapshot_display_project_fields(
    snapshot: ActivitySnapshotContract | None,
) -> dict[str, Any]:
    project_name = _display_project_name(snapshot)
    project_description = _display_project_description(snapshot)
    is_uncategorized = not project_name or project_name == UNCATEGORIZED_PROJECT
    snapshot_project = _snapshot_display_project_dict(snapshot)
    display_project = snapshot_project or {
        "id": None,
        "name": project_name,
        "description": project_description,
        "source": "uncategorized",
        "is_uncategorized": is_uncategorized,
        "is_suggested_project": False,
    }
    project_id = display_project.get("id")
    if project_id is None and snapshot_project is None:
        persisted_id = snapshot_persisted_id(snapshot) if snapshot else None
        if persisted_id and _official_project_name_for_persisted_row(int(persisted_id)):
            try:
                from .project_inference_service import get_assignment_for_activity

                assignment = get_assignment_for_activity(int(persisted_id))
                if assignment and is_official_project_source(
                    str(assignment.get("source") or "")
                ):
                    project_id = assignment.get("project_id")
            except Exception:
                project_id = None
    return {
        "project_id": int(project_id) if project_id is not None else 0,
        "project_name": project_name,
        "project_description": project_description,
        "display_project": display_project,
        "is_uncategorized": bool(is_uncategorized),
        "is_classified": not bool(is_uncategorized),
        "status": _snapshot_status(snapshot),
        "start_time": str(snapshot.get("start_time") or "") if snapshot else "",
    }


def persisted_open_live_seconds(
    snapshot: ActivitySnapshotContract | None,
    row: dict[str, Any] | None,
) -> int:
    if not snapshot or not row:
        return 0
    try:
        row_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        return 0
    snapshot_id = snapshot_persisted_id(snapshot)
    if row_id <= 0 or not snapshot_id or int(snapshot_id) != row_id:
        return 0
    return _snapshot_total_seconds(snapshot)


__all__ = [
    "build_current_activity_summary",
    "classify_live_state",
    "is_live_eligible_for_normal",
    "persisted_open_live_seconds",
]
