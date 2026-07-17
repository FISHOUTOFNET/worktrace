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
from ..formatters import format_duration
from . import timeline_service
from .live_time_service import snapshot_elapsed_seconds, snapshot_persisted_id
from .project_attribution_policy import is_official_project_source


def _snapshot_status(snapshot: ActivitySnapshotContract | None) -> str:
    return str(snapshot.get("status") or "") if snapshot else ""


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
    return str(snapshot.get("app_name") or "").strip() if snapshot else ""


def _snapshot_display_project_dict(
    snapshot: ActivitySnapshotContract | None,
) -> dict[str, Any] | None:
    if not snapshot:
        return None
    value = snapshot.get("display_project")
    return dict(value) if isinstance(value, dict) and value else None


def _official_snapshot_project(
    snapshot: ActivitySnapshotContract | None,
) -> dict[str, Any] | None:
    display_project = _snapshot_display_project_dict(snapshot)
    if not display_project:
        return None
    source = str(display_project.get("source") or "")
    name = str(display_project.get("name") or "").strip()
    if not name or not is_official_project_source(source):
        return None
    return display_project


def _display_project_name(snapshot: ActivitySnapshotContract | None) -> str:
    official = _official_snapshot_project(snapshot)
    return str(official.get("name")) if official else UNCATEGORIZED_PROJECT


def _display_project_description(snapshot: ActivitySnapshotContract | None) -> str:
    official = _official_snapshot_project(snapshot)
    return str(official.get("description") or "") if official else ""


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


def _uncategorized_display_project() -> dict[str, Any]:
    return {
        "id": None,
        "name": UNCATEGORIZED_PROJECT,
        "description": "",
        "source": "uncategorized",
        "is_uncategorized": True,
        "is_suggested_project": False,
    }


def _formal_display_project(
    snapshot: ActivitySnapshotContract | None,
) -> dict[str, Any]:
    official = _official_snapshot_project(snapshot)
    if official is None:
        return _uncategorized_display_project()
    return {
        "id": official.get("id"),
        "name": str(official.get("name") or ""),
        "description": str(official.get("description") or ""),
        "source": str(official.get("source") or ""),
        "is_uncategorized": False,
        "is_suggested_project": False,
    }


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
    display_project = _formal_display_project(snapshot)
    project_name = str(display_project["name"])
    project_description = str(display_project["description"])
    resource_name = _display_resource_name(snapshot)
    app_name = _display_app_name(snapshot)
    start_time = str(snapshot.get("start_time") or "")
    status = _snapshot_status(snapshot)
    is_paused = status == STATUS_PAUSED
    is_persisted = bool(snapshot.get("is_persisted"))
    persisted_id = snapshot_persisted_id(snapshot) or 0
    is_in_progress = live_state == "persisted_open"
    is_uncategorized = bool(display_project["is_uncategorized"])
    live_started_at_epoch_ms = _start_time_epoch_ms(snapshot)

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
    display = (
        f"{resource_name}｜{project_name}｜{format_duration(elapsed_seconds)}｜{state_label}"
    )
    project_id = display_project.get("id")
    return {
        "active": True,
        "display": display,
        "elapsed_seconds": int(elapsed_seconds),
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
        "carry_seconds": 0,
        "resource_name": resource_name,
        "app_name": app_name,
        "start_time": start_time,
        "end_time": None,
        "activity_id": int(persisted_id or 0) or None,
        "source": "db" if is_in_progress else "none",
        "is_uncategorized": is_uncategorized,
        "is_classified": not is_uncategorized,
        "project_description": project_description,
        "display_project": display_project,
    }


def _snapshot_display_project_fields(
    snapshot: ActivitySnapshotContract | None,
) -> dict[str, Any]:
    display_project = _formal_display_project(snapshot)
    project_id = display_project.get("id")
    is_uncategorized = bool(display_project["is_uncategorized"])
    return {
        "project_id": int(project_id) if project_id is not None else 0,
        "project_name": str(display_project["name"]),
        "project_description": str(display_project["description"]),
        "display_project": display_project,
        "is_uncategorized": is_uncategorized,
        "is_classified": not is_uncategorized,
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
