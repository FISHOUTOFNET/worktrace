"""Pure report-period context attribution.

Direct assignments are durable collection/business facts. Context attribution
is reconstructed from those facts for every canonical snapshot; this module
has no database or process-cache dependency.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from ..constants import (
    CLIPBOARD_TRANSITION_SECONDS,
    REPORT_CONTEXT_SHORT_MERGE_SECONDS,
    STATUS_ERROR,
    STATUS_EXCLUDED,
    STATUS_IDLE,
    STATUS_NORMAL,
    STATUS_PAUSED,
    TIME_FORMAT,
)
from .activity_status_policy import does_status_require_boundary

DIRECT_ASSIGNMENT_SOURCES = frozenset(
    {"manual", "keyword_rule", "folder_rule", "midnight_anchor"}
)
DERIVED_CONTEXT_SOURCES = frozenset(
    {"anchor_context", "same_project_context", "clipboard_transition_context"}
)
CONTEXT_ATTRIBUTABLE_STATUSES = frozenset(
    {STATUS_NORMAL, STATUS_IDLE, STATUS_ERROR, STATUS_EXCLUDED}
)


@dataclass(frozen=True)
class ReportContextAttribution:
    activity_id: int
    project_id: int
    attribution_kind: str


@dataclass(frozen=True)
class ContextRowRole:
    """Independent context capabilities for one report row.

    A durable direct assignment is not the same thing as a context anchor.
    Direct status rows keep their own project and block propagation, while only
    normal direct rows are permitted to lend a project to neighbouring rows.
    """

    has_durable_direct_assignment: bool
    has_visible_direct_project: bool
    can_anchor_context: bool
    can_receive_context: bool
    blocks_context_search: bool


@dataclass(frozen=True)
class ReportContextProjection:
    rows: tuple[dict[str, Any], ...]
    attributions: tuple[ReportContextAttribution, ...]

    @classmethod
    def build(
        cls,
        rows: Sequence[Mapping[str, Any]],
        *,
        carry_minutes: int,
        boundary_times: Iterable[str] = (),
        clipboard_times: Mapping[int, Sequence[str]] | None = None,
    ) -> "ReportContextProjection":
        projected = [deepcopy(dict(row)) for row in rows]
        boundaries = tuple(sorted(str(value) for value in boundary_times if value))
        copies = clipboard_times or {}
        carry_seconds = min(
            max(0, int(carry_minutes)) * 60,
            REPORT_CONTEXT_SHORT_MERGE_SECONDS,
        )
        attributions: list[ReportContextAttribution] = []

        # Persisted derived sources are never trusted as direct facts. Fresh v4
        # databases cannot create them, but clearing them keeps in-memory and
        # imported callers deterministic.
        for row in projected:
            if str(row.get("assignment_source") or "") in DERIVED_CONTEXT_SOURCES:
                _clear_project(row)

        for index, row in enumerate(projected):
            role = _context_role(row, carry_seconds)
            if not role.can_receive_context:
                continue
            attribution = _clipboard_attribution(projected, index, copies, boundaries)
            if attribution is None and carry_seconds > 0:
                attribution = _neighbour_attribution(
                    projected,
                    index,
                    carry_seconds,
                    boundaries,
                )
            if attribution is None:
                continue
            anchor, kind = attribution
            _copy_project(row, anchor, kind)
            attributions.append(
                ReportContextAttribution(
                    activity_id=int(row.get("id") or row.get("activity_id") or 0),
                    project_id=int(row.get("report_project_id") or 0),
                    attribution_kind=kind,
                )
            )
        return cls(tuple(projected), tuple(attributions))


def _context_role(row: Mapping[str, Any], carry_seconds: int) -> ContextRowRole:
    status = str(row.get("status") or "")
    direct = _has_durable_direct_assignment(row)
    visible_direct = direct and _has_visible_direct_project(row)
    can_anchor = status == STATUS_NORMAL and visible_direct
    eligible = _eligible(row, carry_seconds)
    boundary = status == STATUS_PAUSED or does_status_require_boundary(
        status,
        _row_duration_seconds(row),
    )
    return ContextRowRole(
        has_durable_direct_assignment=direct,
        has_visible_direct_project=visible_direct,
        can_anchor_context=can_anchor,
        can_receive_context=eligible and not direct,
        blocks_context_search=direct or boundary,
    )


def _eligible(row: Mapping[str, Any], carry_seconds: int) -> bool:
    if bool(row.get("is_deleted")) or bool(row.get("is_hidden")):
        return False
    status = str(row.get("status") or "")
    if status not in CONTEXT_ATTRIBUTABLE_STATUSES:
        return False
    if status == STATUS_NORMAL:
        return True
    return carry_seconds > 0 and _row_duration_seconds(row) <= carry_seconds


def _has_durable_direct_assignment(row: Mapping[str, Any]) -> bool:
    if str(row.get("assignment_source") or "") not in DIRECT_ASSIGNMENT_SOURCES:
        return False
    return _direct_project_id(row) > 0


def _has_visible_direct_project(row: Mapping[str, Any]) -> bool:
    return (
        bool(row.get("is_report_project"))
        and not bool(
            row.get("report_project_is_deleted")
            or row.get("effective_project_is_deleted")
        )
    )


def _direct_project_id(row: Mapping[str, Any]) -> int:
    for field in (
        "assignment_project_id",
        "effective_project_id",
        "report_project_id",
        "project_id",
    ):
        try:
            value = int(row.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0


def _clipboard_attribution(
    rows: Sequence[dict[str, Any]],
    index: int,
    clipboard_times: Mapping[int, Sequence[str]],
    boundaries: Sequence[str],
) -> tuple[dict[str, Any], str] | None:
    if index <= 0:
        return None
    previous = rows[index - 1]
    current = rows[index]
    # Clipboard transition is a normal-activity transition mechanism. System
    # statuses use the bounded neighbour policy instead.
    if str(current.get("status") or "") != STATUS_NORMAL:
        return None
    if (
        not _context_role(previous, REPORT_CONTEXT_SHORT_MERGE_SECONDS).can_anchor_context
        or _crosses_boundary(previous, current, boundaries)
    ):
        return None
    current_start = _parse(current.get("start_time"))
    if current_start is None:
        return None
    previous_id = int(previous.get("id") or previous.get("activity_id") or 0)
    for copied_at in clipboard_times.get(previous_id, ()):
        copied = _parse(copied_at)
        if (
            copied is not None
            and 0 <= (current_start - copied).total_seconds() <= CLIPBOARD_TRANSITION_SECONDS
        ):
            return previous, "clipboard_transition_context"
    return None


def _neighbour_attribution(
    rows: Sequence[dict[str, Any]],
    index: int,
    carry_seconds: int,
    boundaries: Sequence[str],
) -> tuple[dict[str, Any], str] | None:
    previous = _find_anchor(rows, index, -1, carry_seconds, boundaries)
    following = _find_anchor(rows, index, 1, carry_seconds, boundaries)
    if previous and following:
        if int(previous.get("report_project_id") or 0) != int(
            following.get("report_project_id") or 0
        ):
            return None
        return previous, _context_kind(previous)
    anchor = previous or following
    return (anchor, _context_kind(anchor)) if anchor else None


def _find_anchor(
    rows: Sequence[dict[str, Any]],
    origin: int,
    step: int,
    carry_seconds: int,
    boundaries: Sequence[str],
) -> dict[str, Any] | None:
    cursor = origin + step
    while 0 <= cursor < len(rows):
        left, right = (
            (rows[cursor], rows[cursor - step])
            if step < 0
            else (rows[cursor - step], rows[cursor])
        )
        if _crosses_boundary(left, right, boundaries):
            return None
        role = _context_role(rows[cursor], carry_seconds)
        if role.can_anchor_context:
            if _context_distance_seconds(rows[origin], rows[cursor], step) <= carry_seconds:
                return rows[cursor]
            return None
        if role.blocks_context_search:
            return None
        cursor += step
    return None


def _context_distance_seconds(
    target: Mapping[str, Any],
    anchor: Mapping[str, Any],
    step: int,
) -> float:
    if step < 0:
        start = _row_end(anchor)
        end = _row_end(target)
    else:
        start = _parse(target.get("start_time"))
        end = _parse(anchor.get("start_time"))
    if start is None or end is None or end < start:
        return float("inf")
    return (end - start).total_seconds()


def _row_duration_seconds(row: Mapping[str, Any]) -> int:
    stored = 0
    for field in ("report_duration_seconds", "duration_seconds"):
        if row.get(field) is not None:
            try:
                stored = max(stored, max(0, int(row.get(field) or 0)))
            except (TypeError, ValueError):
                pass
    start = _parse(row.get("start_time"))
    end = _parse(row.get("end_time"))
    observed = (
        max(0, int((end - start).total_seconds()))
        if start and end and end >= start
        else 0
    )
    return max(stored, observed)


def _row_end(row: Mapping[str, Any]) -> datetime | None:
    end = _parse(row.get("end_time"))
    if end is not None:
        return end
    start = _parse(row.get("start_time"))
    if start is None:
        return None
    return start + timedelta(seconds=_row_duration_seconds(row))


def _context_kind(anchor: Mapping[str, Any]) -> str:
    return (
        "anchor_context"
        if bool(anchor.get("resource_is_anchor") or anchor.get("is_anchor"))
        else "same_project_context"
    )


def _copy_project(row: dict[str, Any], anchor: Mapping[str, Any], kind: str) -> None:
    row.update(
        {
            "report_project_id": int(anchor.get("report_project_id") or 0),
            "report_project_name": str(anchor.get("report_project_name") or ""),
            "report_project_description": str(
                anchor.get("report_project_description") or ""
            ),
            "report_project_key": str(anchor.get("report_project_key") or ""),
            "report_project_is_deleted": bool(
                anchor.get("report_project_is_deleted")
            ),
            "report_project_is_archived": bool(
                anchor.get("report_project_is_archived")
            ),
            "is_report_project": True,
            "is_report_classified": bool(
                anchor.get("is_report_classified", True)
            ),
            "is_report_uncategorized": False,
            "is_official_project": False,
            "report_context_merged": True,
            "report_attribution_kind": kind,
        }
    )


def _clear_project(row: dict[str, Any]) -> None:
    row.update(
        {
            "effective_project_id": None,
            "effective_project_name": None,
            "effective_project_description": None,
            "report_project_id": 0,
            "report_project_name": "",
            "report_project_description": "",
            "report_project_key": "",
            "report_project_is_deleted": False,
            "report_project_is_archived": False,
            "is_report_project": False,
            "is_report_classified": False,
            "is_report_uncategorized": True,
            "is_official_project": False,
            "report_context_merged": False,
            "report_attribution_kind": "none",
        }
    )


def _crosses_boundary(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    boundaries: Sequence[str],
) -> bool:
    start = str(left.get("end_time") or left.get("start_time") or "")
    end = str(right.get("start_time") or "")
    return bool(
        start and end and any(start <= boundary <= end for boundary in boundaries)
    )


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), TIME_FORMAT)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CONTEXT_ATTRIBUTABLE_STATUSES",
    "ContextRowRole",
    "DERIVED_CONTEXT_SOURCES",
    "DIRECT_ASSIGNMENT_SOURCES",
    "ReportContextAttribution",
    "ReportContextProjection",
]
