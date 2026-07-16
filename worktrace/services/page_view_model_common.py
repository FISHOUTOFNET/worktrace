"""Shared page-level ViewModel presentation helpers."""

from __future__ import annotations

from typing import Any

from ..constants import STATUS_NORMAL
from . import page_revision_service
from .report_revision_service import get_report_structure_revision


def apply_structure_revision(
    payload: dict[str, Any],
    *,
    report_date: str,
    today: str,
    snapshot=None,
) -> None:
    """Attach the canonical structural revision used by heartbeat refreshes.

    ``snapshot`` remains accepted while page builders are migrated to an
    explicit read context.  It is intentionally not hashed here: page loads
    and heartbeat checks must use the same owner and the same algorithm.
    """

    del snapshot
    payload["structure_revision"] = get_report_structure_revision(report_date)
    page_revision_service.apply_page_revision(
        payload,
        report_date=report_date,
        today=today,
    )


def enable_safe_open_edit(entry: dict[str, Any]) -> None:
    if not bool(entry.get("is_in_progress")):
        entry.setdefault("can_edit_project", bool(entry.get("editable", True)))
        entry.setdefault("can_edit_note", bool(entry.get("editable", True)))
        entry.setdefault("can_edit_duration", bool(entry.get("editable", True)))
        return
    safe = (
        str(entry.get("status_code") or entry.get("status") or "")
        == STATUS_NORMAL
        and int(entry.get("open_activity_id") or 0) > 0
        and str(entry.get("row_kind") or "project_session")
        == "project_session"
    )
    entry.update(
        {
            "can_edit_project": safe,
            "can_edit_note": safe,
            "can_edit_duration": False,
            "editable": safe,
            "edit_disabled": not safe,
            "disable_reason": "" if safe else "进行中记录暂不支持编辑",
        }
    )
    for key in (
        "can_hide",
        "can_merge_previous",
        "can_merge_next",
        "can_split",
        "can_copy",
        "can_hide_activity",
    ):
        entry[key] = False


__all__ = ["apply_structure_revision", "enable_safe_open_edit"]
