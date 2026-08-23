"""Pure report-time smoothing for transient automatic project switches.

Raw activity rows and durable project assignments remain unchanged. This
projection only adjusts report-visible project fields so short foreground
excursions do not fragment user-facing project sessions.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from ..constants import STATUS_NORMAL, TIME_FORMAT
from .context_service import BoundaryIndex

REPORT_PROJECT_CONFIRM_SECONDS = 8
REPORT_UNCATEGORIZED_GRACE_SECONDS = 30
REPORT_SAME_PROJECT_DETOUR_SECONDS = 20

AUTOMATIC_PROJECT_SOURCES = frozenset({"keyword_rule", "folder_rule"})
AUTHORITATIVE_TRANSITION_SOURCES = frozenset({"manual", "midnight_anchor"})


@dataclass(frozen=True)
class ReportProjectTransitionAdjustment:
    activity_id: int
    from_project_id: int
    to_project_id: int
    attribution_kind: str


@dataclass(frozen=True)
class _Run:
    indexes: tuple[int, ...]
    project_id: int | None
    duration_seconds: int


@dataclass(frozen=True)
class ReportProjectTransitionProjection:
    rows: tuple[dict[str, Any], ...]
    adjustments: tuple[ReportProjectTransitionAdjustment, ...]

    @classmethod
    def build(
        cls,
        rows: Sequence[Mapping[str, Any]],
        *,
        boundary_times: Iterable[str] = (),
    ) -> "ReportProjectTransitionProjection":
        projected = [deepcopy(dict(row)) for row in rows]
        boundary_index = BoundaryIndex(boundary_times)
        adjustments: list[ReportProjectTransitionAdjustment] = []

        for section in _smoothing_sections(projected, boundary_index):
            _smooth_same_project_detours(projected, section, adjustments)
            _smooth_pending_transitions(projected, section, adjustments)

        return cls(tuple(projected), tuple(adjustments))


def _smoothing_sections(
    rows: Sequence[dict[str, Any]],
    boundary_index: BoundaryIndex,
) -> list[tuple[int, ...]]:
    sections: list[tuple[int, ...]] = []
    current: list[int] = []
    previous_index: int | None = None

    for index, row in enumerate(rows):
        if _is_row_barrier(row, boundary_index):
            if current:
                sections.append(tuple(current))
                current = []
            previous_index = None
            continue

        if previous_index is not None and _crosses_boundary(
            rows[previous_index], row, boundary_index
        ):
            if current:
                sections.append(tuple(current))
            current = []

        current.append(index)
        previous_index = index

    if current:
        sections.append(tuple(current))
    return sections


def _smooth_same_project_detours(
    rows: list[dict[str, Any]],
    section: Sequence[int],
    adjustments: list[ReportProjectTransitionAdjustment],
) -> None:
    runs = _runs(rows, section)
    for index in range(1, len(runs) - 1):
        previous = runs[index - 1]
        detour = runs[index]
        following = runs[index + 1]
        if (
            previous.project_id is None
            or detour.project_id is None
            or following.project_id is None
            or previous.project_id != following.project_id
            or detour.project_id == previous.project_id
            or detour.duration_seconds > REPORT_SAME_PROJECT_DETOUR_SECONDS
        ):
            continue
        anchor = rows[previous.indexes[-1]]
        for row_index in detour.indexes:
            _copy_report_project(
                rows[row_index],
                anchor,
                "report_transition_same_project_detour",
                adjustments,
            )


def _smooth_pending_transitions(
    rows: list[dict[str, Any]],
    section: Sequence[int],
    adjustments: list[ReportProjectTransitionAdjustment],
) -> None:
    stable_project_id: int | None = None
    stable_anchor: dict[str, Any] | None = None

    for run in _runs(rows, section):
        if run.project_id is not None:
            if stable_project_id is None:
                stable_project_id = run.project_id
                stable_anchor = rows[run.indexes[-1]]
                continue
            if run.project_id == stable_project_id:
                stable_anchor = rows[run.indexes[-1]]
                continue
            if run.duration_seconds < REPORT_PROJECT_CONFIRM_SECONDS:
                if stable_anchor is not None:
                    for row_index in run.indexes:
                        _copy_report_project(
                            rows[row_index],
                            stable_anchor,
                            "report_transition_pending_project",
                            adjustments,
                        )
                continue
            stable_project_id = run.project_id
            stable_anchor = rows[run.indexes[-1]]
            continue

        if (
            stable_project_id is not None
            and stable_anchor is not None
            and run.duration_seconds < REPORT_UNCATEGORIZED_GRACE_SECONDS
        ):
            for row_index in run.indexes:
                _copy_report_project(
                    rows[row_index],
                    stable_anchor,
                    "report_transition_uncategorized_grace",
                    adjustments,
                )
            continue

        stable_project_id = None
        stable_anchor = None


def _runs(rows: Sequence[dict[str, Any]], section: Sequence[int]) -> list[_Run]:
    result: list[_Run] = []
    current_indexes: list[int] = []
    current_project_id: int | None = None
    current_duration = 0
    has_current = False

    for index in section:
        project_id = _automatic_report_project_id(rows[index])
        duration = _row_duration_seconds(rows[index])
        if has_current and project_id == current_project_id:
            current_indexes.append(index)
            current_duration += duration
            continue
        if has_current:
            result.append(
                _Run(
                    indexes=tuple(current_indexes),
                    project_id=current_project_id,
                    duration_seconds=current_duration,
                )
            )
        current_indexes = [index]
        current_project_id = project_id
        current_duration = duration
        has_current = True

    if has_current:
        result.append(
            _Run(
                indexes=tuple(current_indexes),
                project_id=current_project_id,
                duration_seconds=current_duration,
            )
        )
    return result


def _automatic_report_project_id(row: Mapping[str, Any]) -> int | None:
    source = str(row.get("assignment_source") or "")
    if source not in AUTOMATIC_PROJECT_SOURCES:
        return None
    if not bool(row.get("is_report_project")):
        return None
    if bool(
        row.get("report_project_is_deleted")
        or row.get("effective_project_is_deleted")
    ):
        return None
    try:
        project_id = int(row.get("report_project_id") or 0)
    except (TypeError, ValueError):
        return None
    return project_id if project_id > 0 else None


def _is_row_barrier(
    row: Mapping[str, Any],
    boundary_index: BoundaryIndex,
) -> bool:
    if str(row.get("status") or "") != STATUS_NORMAL:
        return True
    if str(row.get("assignment_source") or "") in AUTHORITATIVE_TRANSITION_SOURCES:
        return True
    start = str(row.get("start_time") or "")
    end = str(row.get("end_time") or start)
    return bool(start and end and boundary_index.crosses(start, end))


def _crosses_boundary(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    boundary_index: BoundaryIndex,
) -> bool:
    start = str(left.get("end_time") or left.get("start_time") or "")
    end = str(right.get("start_time") or "")
    return boundary_index.crosses(start, end)


def _row_duration_seconds(row: Mapping[str, Any]) -> int:
    stored = 0
    for field in ("report_duration_seconds", "duration_seconds"):
        if row.get(field) is None:
            continue
        try:
            stored = max(stored, max(0, int(row.get(field) or 0)))
        except (TypeError, ValueError):
            pass
    start = _parse(row.get("start_time"))
    end = _parse(row.get("end_time"))
    observed = (
        max(0, int((end - start).total_seconds()))
        if start is not None and end is not None and end >= start
        else 0
    )
    return max(stored, observed)


def _copy_report_project(
    row: dict[str, Any],
    anchor: Mapping[str, Any],
    kind: str,
    adjustments: list[ReportProjectTransitionAdjustment],
) -> None:
    from_project_id = int(row.get("report_project_id") or 0)
    to_project_id = int(anchor.get("report_project_id") or 0)
    if to_project_id <= 0 or not bool(anchor.get("is_report_project")):
        return
    if (
        from_project_id == to_project_id
        and bool(row.get("is_report_project"))
        and bool(row.get("report_transition_smoothed"))
    ):
        return

    row.update(
        {
            "report_project_id": to_project_id,
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
            "is_report_classified": True,
            "is_report_uncategorized": False,
            "is_official_project": False,
            "report_attribution_kind": kind,
            "report_transition_smoothed": True,
            "report_transition_original_project_id": from_project_id,
        }
    )
    adjustments.append(
        ReportProjectTransitionAdjustment(
            activity_id=int(row.get("id") or row.get("activity_id") or 0),
            from_project_id=from_project_id,
            to_project_id=to_project_id,
            attribution_kind=kind,
        )
    )


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), TIME_FORMAT)
    except (TypeError, ValueError):
        return None


__all__ = [
    "AUTHORITATIVE_TRANSITION_SOURCES",
    "AUTOMATIC_PROJECT_SOURCES",
    "REPORT_PROJECT_CONFIRM_SECONDS",
    "REPORT_SAME_PROJECT_DETOUR_SECONDS",
    "REPORT_UNCATEGORIZED_GRACE_SECONDS",
    "ReportProjectTransitionAdjustment",
    "ReportProjectTransitionProjection",
]
