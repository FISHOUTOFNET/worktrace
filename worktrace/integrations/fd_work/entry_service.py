"""Authoritative construction and opening of FD Work entry drafts."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Mapping, Protocol

from ...constants import UNCATEGORIZED_PROJECT
from ...services.report_projection_provider import get_day_projection
from .contracts import FDWorkEntryDraft, FDWorkEntryError, FDWorkEntryRequest

_SECONDS_PER_HOUR = Decimal(3600)
_ONE_DECIMAL = Decimal("0.1")
_MAX_DURATION_HOURS = Decimal("23.9")
_MAX_DURATION_SECONDS = _MAX_DURATION_HOURS * _SECONDS_PER_HOUR


class _DraftWindow(Protocol):
    def open_entry(self, draft: FDWorkEntryDraft) -> Mapping[str, Any]: ...


def format_duration_hours(duration_seconds: int) -> str:
    """Match Timeline's positive ``toFixed(1)`` hour presentation exactly."""

    hours = (Decimal(int(duration_seconds)) / _SECONDS_PER_HOUR).quantize(
        _ONE_DECIMAL,
        rounding=ROUND_HALF_UP,
    )
    return format(hours, ".1f")


class FDWorkEntryService:
    """Re-read the canonical projection, validate it, then open a draft."""

    def __init__(
        self,
        *,
        projection_reader: Callable[[str], Any] = get_day_projection,
        window_controller: _DraftWindow | None = None,
    ) -> None:
        self._projection_reader = projection_reader
        self._window_controller = window_controller

    def build_draft(self, request: FDWorkEntryRequest) -> FDWorkEntryDraft:
        projection = self._projection_reader(request.report_date)
        if (
            str(projection.source_version_token)
            != request.expected_source_version
        ):
            raise FDWorkEntryError("stale_selection")

        entry = projection.entry_by_key.get(request.projection_instance_key)
        if entry is None:
            raise FDWorkEntryError("stale_selection")
        if (
            str(entry.get("projection_revision") or "")
            != request.expected_projection_revision
        ):
            raise FDWorkEntryError("stale_selection")

        self._validate_project_session(entry)
        case_number = str(entry.get("project_name") or "").strip()
        if not case_number:
            raise FDWorkEntryError("empty_project_name")

        narrative = str(entry.get("session_note") or "").strip()
        if not narrative:
            raise FDWorkEntryError("empty_narrative")

        adjusted = entry.get("adjusted_duration_seconds")
        duration_seconds = int(
            adjusted
            if adjusted is not None
            else entry.get("duration_seconds") or 0
        )
        if duration_seconds <= 0:
            raise FDWorkEntryError("invalid_duration")
        if Decimal(duration_seconds) > _MAX_DURATION_SECONDS:
            raise FDWorkEntryError("duration_exceeds_limit")
        duration_hours = format_duration_hours(duration_seconds)
        if Decimal(duration_hours) <= 0:
            raise FDWorkEntryError("invalid_duration")

        return FDWorkEntryDraft(
            work_date=request.report_date,
            case_number=case_number,
            duration_hours=duration_hours,
            narrative=narrative,
        )

    def open_entry(
        self,
        report_date: str,
        projection_instance_key: str,
        expected_projection_revision: str,
        expected_source_version: str,
    ) -> dict[str, Any]:
        if self._window_controller is None:
            raise RuntimeError("fd_work_window_unavailable")
        draft = self.build_draft(
            FDWorkEntryRequest(
                report_date=report_date,
                projection_instance_key=projection_instance_key,
                expected_projection_revision=expected_projection_revision,
                expected_source_version=expected_source_version,
            )
        )
        return dict(self._window_controller.open_entry(draft))

    @staticmethod
    def _validate_project_session(entry: Mapping[str, Any]) -> None:
        if bool(entry.get("is_in_progress")):
            raise FDWorkEntryError("in_progress_session")
        if str(entry.get("row_kind") or "") != "project_session":
            raise FDWorkEntryError("system_project")
        name = str(entry.get("project_name") or "").strip()
        if bool(entry.get("is_report_uncategorized")) or name == UNCATEGORIZED_PROJECT:
            raise FDWorkEntryError("uncategorized_project")
        if (
            name in {"已排除", "排除规则"}
            or bool(entry.get("project_is_system"))
            or bool(entry.get("project_is_special"))
            or not bool(entry.get("is_report_project"))
        ):
            raise FDWorkEntryError("system_project")
        if (
            bool(entry.get("project_is_deleted"))
            or bool(entry.get("project_is_archived"))
            or not bool(entry.get("project_is_enabled"))
        ):
            raise FDWorkEntryError("project_unavailable")


__all__ = ["FDWorkEntryService", "format_duration_hours"]
