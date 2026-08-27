"""Request-local realtime overlay for compact Statistics summaries.

The durable Statistics summary is cached independently of runtime ticks. A live
sample is applied only to the current session fragment: the fragment is summarized
before and after the existing canonical as-of overlay, then its delta is merged
into the durable summary. Historical ranges are never thawed or re-frozen for a
one-second runtime update. The same tiny-fragment overlay is also reusable by
point-in-time export so export does not reintroduce a full-range as-of snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping

from .live_time_service import snapshot_seconds_for_date_range, snapshot_start_time
from .page_read_context import current_page_read_context
from .report_projection_model import ReportProjectionSnapshot
from .report_projection_provider import get_day_projection
from .statistics_projection import (
    StatisticsSummaryProjection,
    build_statistics_summary_projection,
)
from .statistics_range_projection import StatisticsRangeProjection
from .timeline_service import get_default_report_date


@dataclass(frozen=True)
class RealtimeStatisticsSummary:
    projection: StatisticsSummaryProjection
    live_target: Mapping[str, Any] | None


@dataclass(frozen=True)
class StatisticsRealtimeOverlay:
    """Request-local replacement of only the verified live Statistics fragment."""

    before_fragment: ReportProjectionSnapshot
    after_fragment: ReportProjectionSnapshot
    runtime_snapshot: Mapping[str, Any]
    live_target: Mapping[str, Any] | None


def _empty_fragment_snapshot(
    start_date: str,
    end_date: str,
    snapshot_revision: str,
) -> ReportProjectionSnapshot:
    return ReportProjectionSnapshot(
        start_date=start_date,
        end_date=end_date,
        base_sessions=(),
        final_entries=(),
        final_sessions=(),
        standalone_status_entries=(),
        final_contributions=(),
        operation_diagnostics=(),
        snapshot_revision=snapshot_revision,
    )


def _activity_id(value: Mapping[str, Any]) -> int:
    try:
        return int(value.get("activity_id") or 0)
    except (TypeError, ValueError):
        return 0


def _select_live_fragment(
    entries,
    contributions,
    *,
    runtime_id: int,
    start_date: str,
    end_date: str,
    snapshot_revision: str,
) -> ReportProjectionSnapshot:
    live_keys = {
        str(row.get("projection_instance_key") or "")
        for row in contributions
        if _activity_id(row) == runtime_id
        and start_date <= str(row.get("report_date") or "") <= end_date
    }
    live_keys.discard("")
    if not live_keys:
        return _empty_fragment_snapshot(
            start_date,
            end_date,
            snapshot_revision,
        )

    selected_entries = tuple(
        entry
        for entry in entries
        if str(entry.get("projection_instance_key") or "") in live_keys
    )
    selected_contributions = tuple(
        row
        for row in contributions
        if str(row.get("projection_instance_key") or "") in live_keys
    )
    final_sessions = tuple(
        entry
        for entry in selected_entries
        if str(entry.get("row_kind") or "project_session") == "project_session"
    )
    standalone = tuple(
        entry
        for entry in selected_entries
        if str(entry.get("row_kind") or "") == "standalone_status"
    )
    return ReportProjectionSnapshot(
        start_date=start_date,
        end_date=end_date,
        base_sessions=selected_entries,
        final_entries=selected_entries,
        final_sessions=final_sessions,
        standalone_status_entries=standalone,
        final_contributions=selected_contributions,
        operation_diagnostics=(),
        snapshot_revision=snapshot_revision,
    )


def _fragment_from_compact_range(
    projection: StatisticsRangeProjection,
    *,
    runtime_id: int,
    start_date: str,
    end_date: str,
    snapshot_revision: str,
) -> ReportProjectionSnapshot:
    return _select_live_fragment(
        projection.entries,
        projection.contributions,
        runtime_id=runtime_id,
        start_date=start_date,
        end_date=end_date,
        snapshot_revision=snapshot_revision,
    )


def _runtime_dates(
    runtime_snapshot: Mapping[str, Any],
    start_date: str,
    end_date: str,
) -> tuple[str, ...]:
    started_at = snapshot_start_time(runtime_snapshot)
    if started_at is None:
        return ()
    try:
        selected_start = date.fromisoformat(start_date)
        selected_end = date.fromisoformat(end_date)
    except ValueError:
        return ()
    current = max(selected_start, started_at.date())
    try:
        report_today = date.fromisoformat(get_default_report_date())
    except ValueError:
        report_today = date.today()
    last = min(selected_end, report_today)
    if current > last:
        return ()
    result: list[str] = []
    while current <= last:
        result.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(result)


def _fragment_from_day_projections(
    runtime_snapshot: Mapping[str, Any],
    *,
    runtime_id: int,
    start_date: str,
    end_date: str,
    snapshot_revision: str,
) -> ReportProjectionSnapshot:
    entries: list[Mapping[str, Any]] = []
    contributions: list[Mapping[str, Any]] = []
    seen_entry_keys: set[tuple[str, str]] = set()
    seen_contributions: set[tuple[str, str, int, str]] = set()

    for report_date in _runtime_dates(runtime_snapshot, start_date, end_date):
        projection = get_day_projection(report_date)
        live_keys = {
            str(row.get("projection_instance_key") or "")
            for row in projection.contributions
            if _activity_id(row) == runtime_id
        }
        live_keys.discard("")
        if not live_keys:
            continue
        for entry in projection.entries:
            key = str(entry.get("projection_instance_key") or "")
            identity = (str(entry.get("report_date") or report_date), key)
            if key in live_keys and identity not in seen_entry_keys:
                entries.append(entry)
                seen_entry_keys.add(identity)
        for key in live_keys:
            for row in projection.contributions_by_key.get(key, ()):
                identity = (
                    str(row.get("report_date") or report_date),
                    str(row.get("projection_instance_key") or ""),
                    _activity_id(row),
                    str(row.get("slice_start_time") or ""),
                )
                if identity in seen_contributions:
                    continue
                contributions.append(row)
                seen_contributions.add(identity)

    return _select_live_fragment(
        entries,
        contributions,
        runtime_id=runtime_id,
        start_date=start_date,
        end_date=end_date,
        snapshot_revision=snapshot_revision,
    )


def _merge_group_rows(
    base_rows,
    before_rows,
    after_rows,
    *,
    total_duration: int,
    file_order: bool = False,
) -> tuple[dict[str, Any], ...]:
    state: dict[str, dict[str, Any]] = {}

    def ensure(row) -> dict[str, Any]:
        key = str(row.get("key") or "")
        item = state.get(key)
        if item is None:
            item = {
                "key": key,
                "display_name": str(row.get("display_name") or ""),
                "duration_seconds": 0,
                "activity_count": 0,
                "report_slice_count": 0,
                "record_count": 0,
                "is_concrete_project": bool(row.get("is_concrete_project")),
            }
            state[key] = item
        return item

    for row in base_rows:
        item = ensure(row)
        for field in (
            "duration_seconds",
            "activity_count",
            "report_slice_count",
            "record_count",
        ):
            item[field] = int(row.get(field) or 0)
        item["display_name"] = str(row.get("display_name") or "")
        item["is_concrete_project"] = bool(row.get("is_concrete_project"))

    for sign, rows in ((-1, before_rows), (1, after_rows)):
        for row in rows:
            item = ensure(row)
            for field in (
                "duration_seconds",
                "activity_count",
                "report_slice_count",
                "record_count",
            ):
                item[field] += sign * int(row.get(field) or 0)
            if sign > 0:
                item["display_name"] = str(
                    row.get("display_name") or item["display_name"]
                )
                item["is_concrete_project"] = bool(
                    item["is_concrete_project"]
                    or row.get("is_concrete_project")
                )

    result: list[dict[str, Any]] = []
    for item in state.values():
        duration = max(0, int(item["duration_seconds"]))
        if duration <= 0:
            continue
        row = {
            "key": str(item["key"]),
            "display_name": str(item["display_name"]),
            "duration_seconds": duration,
            "activity_count": max(0, int(item["activity_count"])),
            "report_slice_count": max(0, int(item["report_slice_count"])),
            "record_count": max(0, int(item["record_count"])),
            "percentage": round(duration / total_duration * 100, 1)
            if total_duration > 0
            else 0.0,
        }
        if any(
            "is_concrete_project" in source
            for source in (*base_rows, *before_rows, *after_rows)
        ):
            row["is_concrete_project"] = bool(item["is_concrete_project"])
        result.append(row)

    if file_order:
        result.sort(
            key=lambda row: (
                -int(row["duration_seconds"]),
                str(row["display_name"]).casefold(),
                str(row["key"]),
            )
        )
    else:
        result.sort(
            key=lambda row: (
                -int(row["duration_seconds"]),
                str(row["display_name"]),
            )
        )
    return tuple(result)


def _merged_scalar(base: int, before: int, after: int) -> int:
    return max(0, int(base) - int(before) + int(after))


def _merge_summary_delta(
    durable: StatisticsSummaryProjection,
    before: StatisticsSummaryProjection,
    after: StatisticsSummaryProjection,
    *,
    snapshot_revision: str,
) -> StatisticsSummaryProjection:
    total = _merged_scalar(
        durable.total_duration_seconds,
        before.total_duration_seconds,
        after.total_duration_seconds,
    )
    by_project = _merge_group_rows(
        durable.by_project,
        before.by_project,
        after.by_project,
        total_duration=total,
    )
    by_file = _merge_group_rows(
        durable.by_file,
        before.by_file,
        after.by_file,
        total_duration=total,
        file_order=True,
    )
    by_app = _merge_group_rows(
        durable.by_app,
        before.by_app,
        after.by_app,
        total_duration=total,
    )
    by_status = _merge_group_rows(
        durable.by_status,
        before.by_status,
        after.by_status,
        total_duration=total,
    )

    return StatisticsSummaryProjection(
        snapshot_revision=snapshot_revision,
        total_duration_seconds=total,
        project_duration_seconds=_merged_scalar(
            durable.project_duration_seconds,
            before.project_duration_seconds,
            after.project_duration_seconds,
        ),
        classified_duration_seconds=_merged_scalar(
            durable.classified_duration_seconds,
            before.classified_duration_seconds,
            after.classified_duration_seconds,
        ),
        uncategorized_duration_seconds=_merged_scalar(
            durable.uncategorized_duration_seconds,
            before.uncategorized_duration_seconds,
            after.uncategorized_duration_seconds,
        ),
        excluded_duration_seconds=_merged_scalar(
            durable.excluded_duration_seconds,
            before.excluded_duration_seconds,
            after.excluded_duration_seconds,
        ),
        activity_count=_merged_scalar(
            durable.activity_count,
            before.activity_count,
            after.activity_count,
        ),
        report_slice_count=_merged_scalar(
            durable.report_slice_count,
            before.report_slice_count,
            after.report_slice_count,
        ),
        session_count=_merged_scalar(
            durable.session_count,
            before.session_count,
            after.session_count,
        ),
        entry_count=_merged_scalar(
            durable.entry_count,
            before.entry_count,
            after.entry_count,
        ),
        export_row_count=_merged_scalar(
            durable.export_row_count,
            before.export_row_count,
            after.export_row_count,
        ),
        concrete_project_count=sum(
            1
            for row in by_project
            if bool(row.get("is_concrete_project"))
        ),
        concrete_app_count=sum(
            1
            for row in by_app
            if str(row.get("key") or "") != "已排除"
        ),
        by_project=by_project,
        by_file=by_file,
        by_app=by_app,
        by_status=by_status,
        live_file_key=str(after.live_file_key or ""),
    )


def build_statistics_realtime_overlay(
    snapshot_revision: str,
    start_date: str,
    end_date: str,
    *,
    range_projection: StatisticsRangeProjection | None = None,
) -> StatisticsRealtimeOverlay | None:
    """Build only the verified live fragment replacement for one request sample."""

    context = current_page_read_context()
    if context is None or not context.runtime_consistent:
        return None

    runtime_snapshot = context.runtime_sample.snapshot
    if not isinstance(runtime_snapshot, Mapping):
        return None
    if (
        snapshot_seconds_for_date_range(
            runtime_snapshot,
            start_date,
            end_date,
        )
        <= 0
    ):
        return None

    open_activity_id = context.verified_open_activity_id
    if open_activity_id is None:
        fragment = _empty_fragment_snapshot(
            start_date,
            end_date,
            snapshot_revision,
        )
    else:
        try:
            runtime_id = int(runtime_snapshot.get("persisted_activity_id") or 0)
        except (TypeError, ValueError):
            return None
        if runtime_id != int(open_activity_id):
            return None
        if range_projection is not None:
            fragment = _fragment_from_compact_range(
                range_projection,
                runtime_id=runtime_id,
                start_date=start_date,
                end_date=end_date,
                snapshot_revision=snapshot_revision,
            )
        else:
            fragment = _fragment_from_day_projections(
                runtime_snapshot,
                runtime_id=runtime_id,
                start_date=start_date,
                end_date=end_date,
                snapshot_revision=snapshot_revision,
            )

    # Reuse the canonical runtime-overlay policy only on the tiny live fragment.
    from . import report_as_of_snapshot_service

    as_of = report_as_of_snapshot_service.build_statistics_as_of_snapshot(
        start_date,
        end_date,
        base_snapshot=fragment,
    )
    if (
        as_of.live_target is None
        and as_of.snapshot.snapshot_revision == snapshot_revision
    ):
        return None

    return StatisticsRealtimeOverlay(
        before_fragment=fragment,
        after_fragment=as_of.snapshot,
        runtime_snapshot=runtime_snapshot,
        live_target=as_of.live_target,
    )


def merge_statistics_realtime_overlay(
    durable: StatisticsSummaryProjection,
    overlay: StatisticsRealtimeOverlay | None,
    project_id: str | int | None = None,
) -> RealtimeStatisticsSummary:
    """Merge a precomputed tiny-fragment overlay into one durable summary."""

    if overlay is None:
        return RealtimeStatisticsSummary(durable, None)

    before = build_statistics_summary_projection(
        overlay.before_fragment,
        project_id=project_id,
        live_runtime_snapshot=overlay.runtime_snapshot,
    )
    after = build_statistics_summary_projection(
        overlay.after_fragment,
        project_id=project_id,
        live_runtime_snapshot=overlay.runtime_snapshot,
    )
    projection = _merge_summary_delta(
        durable,
        before,
        after,
        snapshot_revision=overlay.after_fragment.snapshot_revision,
    )
    return RealtimeStatisticsSummary(
        projection=projection,
        live_target=overlay.live_target,
    )


def build_statistics_realtime_summary(
    durable: StatisticsSummaryProjection,
    start_date: str,
    end_date: str,
    project_id: str | int | None = None,
    *,
    range_projection: StatisticsRangeProjection | None = None,
) -> RealtimeStatisticsSummary:
    """Overlay only the verified live fragment onto a cached durable summary."""

    overlay = build_statistics_realtime_overlay(
        durable.snapshot_revision,
        start_date,
        end_date,
        range_projection=range_projection,
    )
    return merge_statistics_realtime_overlay(
        durable,
        overlay,
        project_id=project_id,
    )


__all__ = [
    "RealtimeStatisticsSummary",
    "StatisticsRealtimeOverlay",
    "build_statistics_realtime_overlay",
    "build_statistics_realtime_summary",
    "merge_statistics_realtime_overlay",
]
