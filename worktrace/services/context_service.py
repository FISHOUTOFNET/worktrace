"""Pure report-period context attribution.

Direct assignments are durable collection/business facts. Context attribution
is reconstructed from those facts for every canonical snapshot; this module
has no database or process-cache dependency.

The attribution algorithm runs in O(N). The forward anchor (next anchor) is
precomputed in a single backward pass over the original (unmutated) rows. The
backward anchor (previous anchor) is tracked at runtime during the forward
build pass, because the former O(N²) algorithm's backward walk saw rows
already mutated by ``_copy_project`` — a row with a direct-assignment source
that received context became a new effective anchor (propagation effect).
Re-evaluating ``_context_role`` on the mutated previous row reproduces this
exactly while keeping the per-row cost O(1). A shared :class:`BoundaryIndex`
provides O(log B) boundary-crossing checks.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
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


class BoundaryIndex:
    """Sorted-array boundary lookup shared by context and session builder.

    Provides O(log B) ``crosses`` queries via :mod:`bisect`, replacing the
    O(B) ``any(start <= b <= end for b in boundaries)`` scan previously
    duplicated in :mod:`context_service` and :mod:`report_session_builder`.
    """

    __slots__ = ("_sorted",)

    def __init__(self, boundary_times: Iterable[str] = ()) -> None:
        self._sorted: tuple[str, ...] = tuple(
            sorted(str(value) for value in boundary_times if value)
        )

    def crosses(self, start: str, end: str) -> bool:
        """Return True if any boundary falls in the inclusive range [start, end]."""

        if not start or not end or not self._sorted or start > end:
            return False
        lo = bisect_left(self._sorted, start)
        hi = bisect_right(self._sorted, end)
        return lo < hi

    def __bool__(self) -> bool:
        return bool(self._sorted)


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
        boundary_index = BoundaryIndex(boundary_times)
        copies = clipboard_times or {}
        carry_seconds = min(
            max(0, int(carry_minutes)) * 60,
            REPORT_CONTEXT_SHORT_MERGE_SECONDS,
        )

        for row in projected:
            if str(row.get("assignment_source") or "") in DERIVED_CONTEXT_SOURCES:
                _clear_project(row)

        roles = [_context_role(row, carry_seconds) for row in projected]
        next_anchor = _precompute_next_anchors(
            projected, roles, boundary_index
        )

        attributions: list[ReportContextAttribution] = []
        prev_effective_anchor: int | None = None
        for index, row in enumerate(projected):
            # Track prev_effective_anchor against the previous row's *mutated*
            # state: the former backward walk saw rows already modified by
            # _copy_project, so a direct row that received context became a
            # new anchor (propagation effect).
            if index > 0:
                prev_row = projected[index - 1]
                prev_role = _context_role(prev_row, carry_seconds)
                left_end = str(
                    prev_row.get("end_time") or prev_row.get("start_time") or ""
                )
                right_start = str(row.get("start_time") or "")
                if boundary_index.crosses(left_end, right_start):
                    prev_effective_anchor = None
                elif prev_role.can_anchor_context:
                    prev_effective_anchor = index - 1
                elif prev_role.blocks_context_search:
                    prev_effective_anchor = None
                # else: carry forward unchanged

            role = roles[index]
            if not role.can_receive_context:
                continue
            attribution = _clipboard_attribution(
                projected, index, copies, boundary_index
            )
            if attribution is None and carry_seconds > 0:
                attribution = _neighbour_attribution_linear(
                    projected,
                    index,
                    carry_seconds,
                    prev_effective_anchor,
                    next_anchor[index],
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


def _precompute_next_anchors(
    rows: Sequence[dict[str, Any]],
    roles: Sequence[ContextRowRole],
    boundary_index: BoundaryIndex,
) -> list[int | None]:
    """Backward pass: for each row, the index of the nearest reachable next anchor."""

    n = len(rows)
    result: list[int | None] = [None] * n
    for i in range(n - 1, -1, -1):
        if roles[i].can_anchor_context:
            result[i] = i
        elif roles[i].blocks_context_search:
            result[i] = None
        elif i == n - 1:
            result[i] = None
        else:
            left_end = str(rows[i].get("end_time") or rows[i].get("start_time") or "")
            right_start = str(rows[i + 1].get("start_time") or "")
            if boundary_index.crosses(left_end, right_start):
                result[i] = None
            else:
                result[i] = result[i + 1]
    return result


def _context_role(row: Mapping[str, Any], carry_seconds: int) -> ContextRowRole:
    status = str(row.get("status") or "")
    direct = _has_durable_direct_assignment(row)
    visible_direct = direct and _has_visible_direct_project(row)
    can_anchor = status == STATUS_NORMAL and visible_direct
    eligible = _eligible(row, carry_seconds)
    context_limit_barrier = (
        status in {STATUS_IDLE, STATUS_ERROR, STATUS_EXCLUDED} and not eligible
    )
    boundary = (
        status == STATUS_PAUSED
        or context_limit_barrier
        or does_status_require_boundary(status, _row_duration_seconds(row))
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
    boundary_index: BoundaryIndex,
) -> tuple[dict[str, Any], str] | None:
    if index <= 0:
        return None
    previous = rows[index - 1]
    current = rows[index]
    if str(current.get("status") or "") != STATUS_NORMAL:
        return None
    if (
        not _context_role(
            previous,
            REPORT_CONTEXT_SHORT_MERGE_SECONDS,
        ).can_anchor_context
        or _crosses_boundary_indexed(previous, current, boundary_index)
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
            and 0
            <= (current_start - copied).total_seconds()
            <= CLIPBOARD_TRANSITION_SECONDS
        ):
            return previous, "clipboard_transition_context"
    return None


def _neighbour_attribution_linear(
    rows: Sequence[dict[str, Any]],
    index: int,
    carry_seconds: int,
    prev_anchor_idx: int | None,
    next_anchor_idx: int | None,
) -> tuple[dict[str, Any], str] | None:
    """O(1) neighbour attribution using runtime-tracked and precomputed anchors.

    ``prev_anchor_idx`` is tracked at runtime during the forward pass because
    the old algorithm's backward walk saw mutated rows (propagation effect).
    ``next_anchor_idx`` is precomputed from original rows because the forward
    walk only encounters unmutated rows. The carry-distance check is applied
    here because it depends on the origin row's timestamps.
    """

    prev_idx = _resolve_anchor_within_carry(
        rows, index, prev_anchor_idx, carry_seconds, step=-1
    )
    next_idx = _resolve_anchor_within_carry(
        rows, index, next_anchor_idx, carry_seconds, step=1
    )
    if prev_idx is not None and next_idx is not None:
        if int(rows[prev_idx].get("report_project_id") or 0) != int(
            rows[next_idx].get("report_project_id") or 0
        ):
            return None
        return rows[prev_idx], _context_kind(rows[prev_idx])
    anchor_idx = prev_idx if prev_idx is not None else next_idx
    if anchor_idx is None:
        return None
    return rows[anchor_idx], _context_kind(rows[anchor_idx])


def _resolve_anchor_within_carry(
    rows: Sequence[dict[str, Any]],
    origin: int,
    anchor_idx: int | None,
    carry_seconds: int,
    step: int,
) -> int | None:
    """Check carry distance for a precomputed anchor index.

    The precomputed index is the nearest reachable anchor ignoring distance.
    If it is beyond the carry window, no anchor is usable (matching the
    original ``_find_anchor`` which stops at the first anchor).
    """

    if anchor_idx is None or anchor_idx == origin:
        return None
    if _context_distance_seconds(rows[origin], rows[anchor_idx], step) <= carry_seconds:
        return anchor_idx
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


def _crosses_boundary_indexed(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    boundary_index: BoundaryIndex,
) -> bool:
    start = str(left.get("end_time") or left.get("start_time") or "")
    end = str(right.get("start_time") or "")
    return boundary_index.crosses(start, end)


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), TIME_FORMAT)
    except (TypeError, ValueError):
        return None


__all__ = [
    "CONTEXT_ATTRIBUTABLE_STATUSES",
    "BoundaryIndex",
    "ContextRowRole",
    "DERIVED_CONTEXT_SOURCES",
    "DIRECT_ASSIGNMENT_SOURCES",
    "ReportContextAttribution",
    "ReportContextProjection",
]
