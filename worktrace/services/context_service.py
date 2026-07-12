"""Pure report-period context attribution.

Direct assignments are durable collection/business facts.  Context attribution
is deliberately reconstructed from those facts for every canonical snapshot;
this module has no database or process-cache dependency.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from ..constants import CLIPBOARD_TRANSITION_SECONDS, STATUS_NORMAL, STATUS_PAUSED, TIME_FORMAT

DIRECT_ASSIGNMENT_SOURCES = frozenset(
    {"manual", "keyword_rule", "folder_rule", "midnight_anchor"}
)
DERIVED_CONTEXT_SOURCES = frozenset(
    {"anchor_context", "same_project_context", "clipboard_transition_context"}
)


@dataclass(frozen=True)
class ReportContextAttribution:
    activity_id: int
    project_id: int
    attribution_kind: str


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
        attributions: list[ReportContextAttribution] = []

        # A persisted derived source is never trusted as a direct fact.  Fresh
        # v4 databases cannot create one, but this keeps projection semantics
        # deterministic for any in-memory caller.
        for row in projected:
            if str(row.get("assignment_source") or "") in DERIVED_CONTEXT_SOURCES:
                _clear_project(row)

        for index, row in enumerate(projected):
            if not _eligible(row):
                continue
            if _has_direct_project(row):
                continue
            attribution = _clipboard_attribution(projected, index, copies, boundaries)
            if attribution is None:
                attribution = _neighbour_attribution(
                    projected,
                    index,
                    max(0, int(carry_minutes)),
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


def _eligible(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("status") or "") == STATUS_NORMAL
        and not bool(row.get("is_deleted"))
        and not bool(row.get("is_hidden"))
    )


def _has_direct_project(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("assignment_source") or "") in DIRECT_ASSIGNMENT_SOURCES
        and bool(row.get("is_report_project"))
        and not bool(row.get("report_project_is_deleted") or row.get("effective_project_is_deleted"))
    )


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
    if not _has_direct_project(previous) or _crosses_boundary(previous, current, boundaries):
        return None
    current_start = _parse(current.get("start_time"))
    if current_start is None:
        return None
    previous_id = int(previous.get("id") or previous.get("activity_id") or 0)
    for copied_at in clipboard_times.get(previous_id, ()):
        copied = _parse(copied_at)
        if copied is not None and 0 <= (current_start - copied).total_seconds() <= CLIPBOARD_TRANSITION_SECONDS:
            return previous, "clipboard_transition_context"
    return None


def _neighbour_attribution(
    rows: Sequence[dict[str, Any]],
    index: int,
    carry_minutes: int,
    boundaries: Sequence[str],
) -> tuple[dict[str, Any], str] | None:
    previous = _find_anchor(rows, index, -1, carry_minutes, boundaries)
    following = _find_anchor(rows, index, 1, carry_minutes, boundaries)
    if previous and following:
        if int(previous.get("report_project_id") or 0) != int(following.get("report_project_id") or 0):
            return None
        return previous, _context_kind(previous)
    anchor = previous or following
    return (anchor, _context_kind(anchor)) if anchor else None


def _find_anchor(
    rows: Sequence[dict[str, Any]],
    origin: int,
    step: int,
    carry_minutes: int,
    boundaries: Sequence[str],
) -> dict[str, Any] | None:
    cursor = origin + step
    while 0 <= cursor < len(rows):
        left, right = (rows[cursor], rows[cursor - step]) if step < 0 else (rows[cursor - step], rows[cursor])
        if _crosses_boundary(left, right, boundaries) or str(rows[cursor].get("status") or "") == STATUS_PAUSED:
            return None
        if _has_direct_project(rows[cursor]):
            if _minutes_apart(rows[origin], rows[cursor]) <= carry_minutes:
                return rows[cursor]
            return None
        cursor += step
    return None


def _context_kind(anchor: Mapping[str, Any]) -> str:
    return "anchor_context" if bool(anchor.get("resource_is_anchor") or anchor.get("is_anchor")) else "same_project_context"


def _copy_project(row: dict[str, Any], anchor: Mapping[str, Any], kind: str) -> None:
    row.update(
        {
            "report_project_id": int(anchor.get("report_project_id") or 0),
            "report_project_name": str(anchor.get("report_project_name") or ""),
            "report_project_description": str(anchor.get("report_project_description") or ""),
            "report_project_key": str(anchor.get("report_project_key") or ""),
            "report_project_is_deleted": bool(anchor.get("report_project_is_deleted")),
            "report_project_is_archived": bool(anchor.get("report_project_is_archived")),
            "is_report_project": True,
            "is_report_classified": bool(anchor.get("is_report_classified", True)),
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
            "is_report_project": False,
            "is_report_classified": False,
            "is_report_uncategorized": True,
        }
    )


def _crosses_boundary(left: Mapping[str, Any], right: Mapping[str, Any], boundaries: Sequence[str]) -> bool:
    start = str(left.get("end_time") or left.get("start_time") or "")
    end = str(right.get("start_time") or "")
    return bool(start and end and any(start <= boundary <= end for boundary in boundaries))


def _minutes_apart(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    left_time = _parse(left.get("start_time"))
    right_time = _parse(right.get("end_time") or right.get("start_time"))
    if left_time is None or right_time is None:
        return float("inf")
    return abs((left_time - right_time).total_seconds()) / 60.0


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), TIME_FORMAT)
    except (TypeError, ValueError):
        return None


__all__ = [
    "DERIVED_CONTEXT_SOURCES",
    "DIRECT_ASSIGNMENT_SOURCES",
    "ReportContextAttribution",
    "ReportContextProjection",
]
