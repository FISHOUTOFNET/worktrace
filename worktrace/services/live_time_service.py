from __future__ import annotations

from datetime import datetime

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


def safe_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
