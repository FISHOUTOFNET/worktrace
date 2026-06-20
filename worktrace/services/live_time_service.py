from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta

from ..constants import TIME_FORMAT

MAX_LIVE_DURATION_SECONDS = 36 * 60 * 60


def snapshot_elapsed_seconds(snapshot: dict | None, now: datetime | None = None) -> int:
    if not snapshot:
        return 0
    fallback = safe_int(snapshot.get("elapsed_seconds"))
    start_text = str(snapshot.get("start_time") or "").strip()
    if not start_text:
        return fallback
    try:
        start = datetime.strptime(start_text, TIME_FORMAT)
    except ValueError:
        return fallback
    current = now or datetime.now()
    seconds = int((current - start).total_seconds())
    if 0 <= seconds <= MAX_LIVE_DURATION_SECONDS:
        return seconds
    return fallback


def snapshot_extra_seconds(snapshot: dict | None) -> int:
    if not snapshot:
        return 0
    return safe_int(snapshot.get("extra_seconds"))


def snapshot_total_seconds(snapshot: dict | None, now: datetime | None = None) -> int:
    return snapshot_elapsed_seconds(snapshot, now=now) + snapshot_extra_seconds(snapshot)


def snapshot_seconds_for_date_range(
    snapshot: dict | None,
    start_date: str,
    end_date: str,
    now: datetime | None = None,
) -> int:
    if not snapshot:
        return 0
    start_dt = snapshot_start_time(snapshot)
    if start_dt is None:
        return 0
    total_seconds = snapshot_total_seconds(snapshot, now=now)
    if total_seconds <= 0:
        return 0
    try:
        range_start_date = date.fromisoformat(start_date)
        range_end_date = date.fromisoformat(end_date)
    except ValueError:
        return 0
    range_start = datetime.combine(range_start_date, datetime_time.min)
    range_end = datetime.combine(range_end_date + timedelta(days=1), datetime_time.min)
    activity_end = start_dt + timedelta(seconds=total_seconds)
    overlap_start = max(start_dt, range_start)
    overlap_end = min(activity_end, range_end)
    return max(0, int((overlap_end - overlap_start).total_seconds()))


def snapshot_start_time(snapshot: dict | None) -> datetime | None:
    if not snapshot:
        return None
    start_text = str(snapshot.get("start_time") or "").strip()
    if not start_text:
        return None
    try:
        return datetime.strptime(start_text, TIME_FORMAT)
    except ValueError:
        return None


def snapshot_persisted_id(snapshot: dict | None) -> int | None:
    value = safe_int((snapshot or {}).get("persisted_activity_id"))
    return value or None


def snapshot_signature(snapshot: dict | None) -> tuple | None:
    if not snapshot:
        return None
    return (
        snapshot.get("status"),
        snapshot.get("app_name"),
        snapshot.get("process_name"),
        snapshot.get("window_title"),
        snapshot.get("file_path_hint"),
        snapshot.get("start_time"),
        bool(snapshot.get("is_persisted")),
        snapshot_persisted_id(snapshot),
    )


def safe_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
