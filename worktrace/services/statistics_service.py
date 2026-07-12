from __future__ import annotations

from datetime import date

from ..constants import STATUS_EXCLUDED, STATUS_IDLE, STATUS_NORMAL, STATUS_PAUSED, UNCATEGORIZED_PROJECT
from ..formatters import format_status_label

# Maximum inclusive calendar-day span accepted by the read-only
# statistics/export summary. A 31-day span (e.g. 2026-06-01..2026-07-01) is
# allowed; anything wider is rejected as ``range_too_large`` so the summary
# never reads an unbounded amount of data.
STATISTICS_SUMMARY_MAX_RANGE_DAYS = 31

# Statistics uses the central report status policy: normal rows always count;
# attributed idle/error/excluded rows count through their report attribution
# (excluded remains privacy-redacted); unattributed idle/error and paused rows
# are suppressed.

_UNKNOWN_APP_LABEL = "未知应用"


def get_summary(start_date: str, end_date: str) -> dict:
    """Return a DB-only statistics summary for the inclusive date range.

    This function is DB-ONLY. It does NOT project the current live
    snapshot. The Overview / KPI live overlay is owned by
    :mod:`worktrace.services.activity_display_model_service` and applied
    by :mod:`worktrace.services.view_model_service` on top of the DB-only
    base returned here. Keeping statistics DB-only is the contract that
    guarantees the KPI base, the recent items, and the live clock all
    share one sample.
    """
    projection = _build_projection(start_date, end_date)
    by_status = {str(row["key"]): int(row["duration_seconds"]) for row in projection.by_status}
    return {
        "total_duration": projection.total_duration_seconds,
        "effective_duration": by_status.get(STATUS_NORMAL, 0),
        "classified_duration": projection.classified_duration_seconds,
        "idle_duration": by_status.get(STATUS_IDLE, 0),
        "paused_duration": by_status.get(STATUS_PAUSED, 0),
        "excluded_duration": projection.excluded_duration_seconds,
        "uncategorized_duration": projection.uncategorized_duration_seconds,
    }


def get_project_stats(start_date: str, end_date: str) -> list[dict]:
    """Return DB-only per-project statistics for the inclusive date range.

    This function is DB-ONLY. It does NOT project the current live
    snapshot nor apply the persisted_open display-project overlay. Both
    of those live semantics are owned by
    :mod:`worktrace.services.activity_display_model_service`.
    """
    projection = _build_projection(start_date, end_date)
    return [
        {
            "project": row["display_name"],
            "total_duration": row["duration_seconds"],
            "record_count": row.get("record_count") or row["activity_count"],
        }
        for row in projection.by_project
    ]


def get_uncategorized_duration(start_date: str, end_date: str) -> int:
    return sum(
        int(row["total_duration"])
        for row in get_project_stats(start_date, end_date)
        if row["project"] == UNCATEGORIZED_PROJECT
    )


def _build_projection(start_date: str, end_date: str):
    from .report_projection_snapshot_service import build_visible_snapshot
    from .statistics_projection import build_statistics_projection

    return build_statistics_projection(build_visible_snapshot(start_date, end_date))


def get_statistics_export_summary(date_from: str, date_to: str) -> dict:
    """Return a read-only statistics + export-preview payload for a date range.

    Inputs are ``YYYY-MM-DD`` strings. ``date_from`` must be on or before
    ``date_to`` and the inclusive span must not exceed
    ``STATISTICS_SUMMARY_MAX_RANGE_DAYS`` calendar days. Violations raise
    ``ValueError`` (the API layer maps these to stable error codes).

    Non-string inputs (including ``None`` and ``bool``) are rejected as
    ``invalid_date``. ``bool`` is rejected explicitly because it is not a
    date string even though it is a subclass of ``int``.

    The returned dict is display-safe and contains no raw DB rows.
    """
    _validate_summary_date_range(date_from, date_to)
    from .report_projection_snapshot_service import build_visible_snapshot
    from .statistics_projection import build_statistics_projection

    projection = build_statistics_projection(build_visible_snapshot(date_from, date_to))
    return {
        "date_from": date_from,
        "date_to": date_to,
        "snapshot_revision": projection.snapshot_revision,
        "total_duration_seconds": projection.total_duration_seconds,
        "project_duration_seconds": projection.project_duration_seconds,
        "classified_duration_seconds": projection.classified_duration_seconds,
        "uncategorized_duration_seconds": projection.uncategorized_duration_seconds,
        "excluded_duration_seconds": projection.excluded_duration_seconds,
        "activity_count": projection.activity_count,
        "session_count": projection.session_count,
        "export_row_count": projection.export_row_count,
        "project_count": len(projection.by_project),
        "app_count": len(projection.by_app),
        "by_project": list(projection.by_project),
        "by_app": list(projection.by_app),
        "by_status": list(projection.by_status),
        "export_preview": {
            "date_from": date_from,
            "date_to": date_to,
            "snapshot_revision": projection.snapshot_revision,
            "included_activity_count": projection.activity_count,
            "session_count": projection.session_count,
            "export_row_count": projection.export_row_count,
            "included_duration_seconds": projection.total_duration_seconds,
            # CSV export is available. Excel / PDF / timesheet are
            # intentionally NOT listed here; the frontend must never offer
            # a format the backend cannot produce.
            "available_formats": ["csv"],
            "export_actions_enabled": True,
        },
    }


def validate_statistics_date_range(date_from: str, date_to: str) -> None:
    """Validate the date range shared by the Statistics summary and CSV export.

    This is the single canonical validation used by both the read-only
    summary (``get_statistics_export_summary``) and the CSV export
    (``export_service.build_statistics_csv_rows`` / ``write_statistics_csv``)
    so summary and export enforce identical rules.

    Raises ``ValueError`` with a stable code token (``invalid_date`` /
    ``invalid_range`` / ``range_too_large``) so the API layer can map to
    user-facing messages without echoing internal details. ``bool`` is
    rejected explicitly because it is not a date string even though it
    is a subclass of ``int``.
    """
    # ``bool`` is a subclass of ``int`` but not of ``str``; the ``str``
    # isinstance check below rejects it so ``True`` / ``False`` never reach
    # ``date.fromisoformat``.
    if not isinstance(date_from, str) or not isinstance(date_to, str):
        raise ValueError("invalid_date")
    try:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to)
    except ValueError:
        raise ValueError("invalid_date")
    if start > end:
        raise ValueError("invalid_range")
    if (end - start).days > STATISTICS_SUMMARY_MAX_RANGE_DAYS - 1:
        raise ValueError("range_too_large")


_validate_summary_date_range = validate_statistics_date_range


def _accumulate_summary_group(
    groups: dict[str, dict],
    key: str,
    display_name: str,
    duration: int,
    activity_id: int,
) -> None:
    group = groups.setdefault(
        key,
        {"display_name": display_name, "duration_seconds": 0, "activity_ids": set()},
    )
    group["duration_seconds"] += duration
    if activity_id:
        group["activity_ids"].add(activity_id)


def _build_summary_groups(groups: dict[str, dict], total_duration: int) -> list[dict]:
    items: list[dict] = []
    for key, group in groups.items():
        duration = int(group["duration_seconds"])
        percentage = round(duration / total_duration * 100, 1) if total_duration > 0 else 0.0
        items.append(
            {
                "key": key,
                "display_name": str(group["display_name"]),
                "duration_seconds": duration,
                "activity_count": len(group["activity_ids"]),
                "percentage": percentage,
            }
        )
    items.sort(key=lambda item: (-item["duration_seconds"], str(item["display_name"]).casefold()))
    return items
