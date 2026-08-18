"""Bounded maintenance policy for durable folder-rule indexes.

This module owns refresh *selection* only. The folder-index service remains the
single scanner/index writer; callers enqueue rule rebuilds through its public
command boundary. Pathless filename misses only signal this policy and never
scan the filesystem synchronously.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from ..constants import (
    EXCLUDED_PROJECT,
    STATUS_NORMAL,
    TIME_FORMAT,
    UNCATEGORIZED_PROJECT,
)
from ..data_generation_repository import (
    DataGenerationNamespace,
    DataGenerationRepository,
)
from ..db import get_connection, get_db_path, now_str

HOT_PROJECT_ACTIVITY_DAYS = 7
HOT_PROJECT_LIMIT = 10
HOT_INDEX_FRESHNESS_MINUTES = 15
HOT_REFRESH_QUERY_COOLDOWN_SECONDS = 300.0
UNRESOLVED_FILE_REFRESH_COOLDOWN_SECONDS = 60.0
_MAX_REFRESH_CACHE_ENTRIES = 256

_REFRESH_CACHE_LOCK = threading.Lock()
_HOT_REFRESH_TIMES: dict[tuple[str, int], float] = {}
_UNRESOLVED_REFRESH_TIMES: dict[tuple[str, int], float] = {}
_UNRESOLVED_FILE_MISS_EVENT = threading.Event()
_UNRESOLVED_FILE_MISS_IDENTITY: tuple[str, int] | None = None
_UNRESOLVED_FILE_MISS_SINCE: str | None = None


def _replacement_cache_identity(conn=None) -> tuple[str, int]:
    database_key = str(get_db_path().resolve())
    if conn is not None:
        replacement_epoch = DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.DATABASE_REPLACEMENT,
        )
        return database_key, replacement_epoch
    with get_connection() as read_conn:
        replacement_epoch = DataGenerationRepository.get(
            read_conn,
            DataGenerationNamespace.DATABASE_REPLACEMENT,
        )
    return database_key, replacement_epoch


def _reserve_refresh(
    cache: dict,
    key: tuple,
    *,
    cooldown_seconds: float,
) -> bool:
    """Return whether a refresh is due without recording success yet.

    The historical name is retained for test/source compatibility. Cooldown is
    committed only after the candidate query and every rebuild enqueue succeed,
    so transient failures remain immediately retryable.
    """

    current = time.monotonic()
    with _REFRESH_CACHE_LOCK:
        return current - cache.get(key, 0.0) >= cooldown_seconds


def _mark_refresh_success(cache: dict, key: tuple) -> None:
    current = time.monotonic()
    with _REFRESH_CACHE_LOCK:
        if len(cache) >= _MAX_REFRESH_CACHE_ENTRIES and key not in cache:
            cache.clear()
        cache[key] = current


def _queue_rule_ids(rule_ids: list[int]) -> int:
    if not rule_ids:
        return 0
    # Function-local import avoids a module-import cycle: folder-index runtime
    # orchestration calls this maintenance policy from its worker loop.
    from . import folder_index_service

    queued = 0
    for rule_id in rule_ids:
        folder_index_service.request_rebuild_for_rule(int(rule_id))
        queued += 1
    return queued


def note_unresolved_file_miss(
    unresolved_at: str | None = None,
    *,
    conn=None,
) -> None:
    """Record a pathless local-file miss and wake the existing index worker."""

    at = str(unresolved_at or now_str())
    identity = _replacement_cache_identity(conn)
    global _UNRESOLVED_FILE_MISS_IDENTITY
    global _UNRESOLVED_FILE_MISS_SINCE
    with _REFRESH_CACHE_LOCK:
        if _UNRESOLVED_FILE_MISS_IDENTITY != identity:
            _UNRESOLVED_FILE_MISS_IDENTITY = identity
            _UNRESOLVED_FILE_MISS_SINCE = at
        elif (
            _UNRESOLVED_FILE_MISS_SINCE is None
            or at > _UNRESOLVED_FILE_MISS_SINCE
        ):
            _UNRESOLVED_FILE_MISS_SINCE = at
        _UNRESOLVED_FILE_MISS_EVENT.set()
    try:
        from . import folder_index_service

        folder_index_service.wake_folder_index_worker()
    except Exception:
        # The worker also wakes on its normal cadence. The pending signal remains
        # set, so a transient wake failure cannot lose the requested maintenance.
        logging.exception("unresolved file miss could not wake folder index worker")


def _pending_unresolved_file_miss() -> tuple[tuple[str, int], str] | None:
    if not _UNRESOLVED_FILE_MISS_EVENT.is_set():
        return None
    with _REFRESH_CACHE_LOCK:
        if (
            _UNRESOLVED_FILE_MISS_IDENTITY is None
            or _UNRESOLVED_FILE_MISS_SINCE is None
        ):
            return None
        return _UNRESOLVED_FILE_MISS_IDENTITY, _UNRESOLVED_FILE_MISS_SINCE


def _clear_unresolved_file_miss_through(
    identity: tuple[str, int],
    resolved_through: str,
) -> None:
    global _UNRESOLVED_FILE_MISS_IDENTITY
    global _UNRESOLVED_FILE_MISS_SINCE
    with _REFRESH_CACHE_LOCK:
        current = _UNRESOLVED_FILE_MISS_SINCE
        if (
            _UNRESOLVED_FILE_MISS_IDENTITY == identity
            and current is not None
            and current <= resolved_through
        ):
            _UNRESOLVED_FILE_MISS_IDENTITY = None
            _UNRESOLVED_FILE_MISS_SINCE = None
            _UNRESOLVED_FILE_MISS_EVENT.clear()


def unresolved_file_indexes_refreshed_since(
    unresolved_at: str | None,
    *,
    conn=None,
) -> bool:
    """Return whether every eligible index began strictly after the miss fact.

    Timestamps are stored at second precision. Equality is intentionally treated
    as inconclusive: an index build and a miss in the same second have no reliable
    causal ordering, so one later rebuild is safer than accepting a stale snapshot.
    """

    boundary = str(unresolved_at or "").strip()
    if not boundary:
        return False

    def _check(read_conn) -> bool:
        row = read_conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(
                       CASE
                           WHEN state.valid_from IS NOT NULL
                            AND state.valid_from > ?
                            AND COALESCE(state.refresh_requested, 0) = 0
                            AND COALESCE(state.build_status, '') = 'ready'
                           THEN 1 ELSE 0
                       END
                   ) AS refreshed
            FROM folder_project_rule fpr
            JOIN project p ON p.id = fpr.project_id
            LEFT JOIN folder_rule_index_state state
              ON state.folder_rule_id = fpr.id
            WHERE fpr.enabled = 1
              AND p.enabled = 1
              AND COALESCE(p.is_archived, 0) = 0
              AND COALESCE(p.is_deleted, 0) = 0
              AND p.name NOT IN (?, ?)
            """,
            (boundary, UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT),
        ).fetchone()
        total = int(row["total"] or 0)
        return int(row["refreshed"] or 0) == total

    if conn is not None:
        return _check(conn)
    with get_connection() as read_conn:
        return _check(read_conn)


def request_refresh_for_unresolved_file_misses() -> int:
    """Queue one coalesced all-project refresh for unresolved pathless files."""

    pending = _pending_unresolved_file_miss()
    if pending is None:
        return 0
    pending_identity, unresolved_since = pending
    current_identity = _replacement_cache_identity()
    if pending_identity != current_identity:
        _clear_unresolved_file_miss_through(pending_identity, unresolved_since)
        return 0
    if unresolved_file_indexes_refreshed_since(unresolved_since):
        _clear_unresolved_file_miss_through(current_identity, unresolved_since)
        return 0

    if not _reserve_refresh(
        _UNRESOLVED_REFRESH_TIMES,
        current_identity,
        cooldown_seconds=UNRESOLVED_FILE_REFRESH_COOLDOWN_SECONDS,
    ):
        return 0

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fpr.id
            FROM folder_project_rule fpr
            JOIN project p ON p.id = fpr.project_id
            LEFT JOIN folder_rule_index_state state
              ON state.folder_rule_id = fpr.id
            WHERE fpr.enabled = 1
              AND p.enabled = 1
              AND COALESCE(p.is_archived, 0) = 0
              AND COALESCE(p.is_deleted, 0) = 0
              AND p.name NOT IN (?, ?)
              AND COALESCE(state.refresh_requested, 0) = 0
              AND COALESCE(state.build_status, '') <> 'indexing'
              AND (
                    state.valid_from IS NULL
                    OR state.valid_from <= ?
                    OR COALESCE(state.build_status, '') <> 'ready'
              )
            ORDER BY fpr.id
            """,
            (UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT, unresolved_since),
        ).fetchall()
    queued = _queue_rule_ids([int(row["id"]) for row in rows])
    if queued:
        _mark_refresh_success(_UNRESOLVED_REFRESH_TIMES, current_identity)
        return queued

    # All stale candidates may already be pending/indexing. Keep the signal until
    # a generation that began strictly after the miss is actually published.
    if unresolved_file_indexes_refreshed_since(unresolved_since):
        _clear_unresolved_file_miss_through(current_identity, unresolved_since)
    return 0


def request_refresh_for_hot_projects() -> int:
    """Queue only stale indexes belonging to currently hot projects.

    Hot projects are the union of projects used during the last seven days and
    the ten most recently used projects. A ready index is not rebuilt more often
    than every 15 minutes. The historical last-used aggregation itself is
    throttled to once per five minutes per database generation, but only after
    a successful candidate query/enqueue pass.
    """

    database_key, replacement_epoch = _replacement_cache_identity()
    cache_key = (database_key, replacement_epoch)
    if not _reserve_refresh(
        _HOT_REFRESH_TIMES,
        cache_key,
        cooldown_seconds=HOT_REFRESH_QUERY_COOLDOWN_SECONDS,
    ):
        return 0

    current = datetime.strptime(now_str(), TIME_FORMAT)
    activity_cutoff = (current - timedelta(days=HOT_PROJECT_ACTIVITY_DAYS)).strftime(
        TIME_FORMAT
    )
    freshness_cutoff = (
        current - timedelta(minutes=HOT_INDEX_FRESHNESS_MINUTES)
    ).strftime(TIME_FORMAT)
    with get_connection() as conn:
        rows = conn.execute(
            """
            WITH last_used AS (
                SELECT apa.project_id AS project_id,
                       MAX(COALESCE(al.end_time, al.start_time)) AS last_used_at
                FROM activity_log al
                JOIN activity_project_assignment apa
                  ON apa.activity_id = al.id
                WHERE al.is_deleted = 0
                  AND apa.project_id IS NOT NULL
                GROUP BY apa.project_id
            ),
            hot_projects AS (
                SELECT project_id
                FROM last_used
                WHERE last_used_at >= ?
                UNION
                SELECT project_id
                FROM (
                    SELECT project_id
                    FROM last_used
                    WHERE last_used_at IS NOT NULL
                    ORDER BY last_used_at DESC, project_id
                    LIMIT ?
                )
            )
            SELECT fpr.id
            FROM folder_project_rule fpr
            JOIN project p ON p.id = fpr.project_id
            JOIN hot_projects hp ON hp.project_id = fpr.project_id
            LEFT JOIN folder_rule_index_state state
              ON state.folder_rule_id = fpr.id
            WHERE fpr.enabled = 1
              AND p.enabled = 1
              AND COALESCE(p.is_archived, 0) = 0
              AND COALESCE(p.is_deleted, 0) = 0
              AND p.name NOT IN (?, ?)
              AND COALESCE(state.refresh_requested, 0) = 0
              AND COALESCE(state.build_status, '') <> 'indexing'
              AND (
                    state.last_indexed_at IS NULL
                    OR state.last_indexed_at <= ?
              )
            ORDER BY fpr.id
            """,
            (
                activity_cutoff,
                HOT_PROJECT_LIMIT,
                UNCATEGORIZED_PROJECT,
                EXCLUDED_PROJECT,
                freshness_cutoff,
            ),
        ).fetchall()
    queued = _queue_rule_ids([int(row["id"]) for row in rows])
    _mark_refresh_success(_HOT_REFRESH_TIMES, cache_key)
    return queued


def reconcile_open_unclassified_activities() -> int:
    """Converge open auto-unclassified rows after a new index is published."""

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT al.id
            FROM activity_log al
            LEFT JOIN activity_project_assignment apa
              ON apa.activity_id = al.id
            WHERE al.end_time IS NULL
              AND al.status = ?
              AND COALESCE(al.is_hidden, 0) = 0
              AND COALESCE(al.is_deleted, 0) = 0
              AND (
                    apa.activity_id IS NULL
                    OR (
                        COALESCE(apa.is_manual, 0) = 0
                        AND COALESCE(apa.source, '') IN (
                            '', 'uncategorized', 'suggested_project_name'
                        )
                    )
              )
            ORDER BY al.id
            """,
            (STATUS_NORMAL,),
        ).fetchall()
    if not rows:
        return 0

    from . import project_inference_service

    reconciled = 0
    for row in rows:
        activity_id = int(row["id"])
        try:
            project_inference_service.sync_persisted_open_activity_from_current_folder_index(
                activity_id
            )
            reconciled += 1
        except Exception:
            # Index maintenance is best-effort. A classification retry must not
            # make the folder-index worker unhealthy or roll back a ready index.
            logging.exception(
                "open activity convergence after folder index refresh failed activity_id=%s",
                activity_id,
            )
    return reconciled


__all__ = [
    "HOT_INDEX_FRESHNESS_MINUTES",
    "HOT_PROJECT_ACTIVITY_DAYS",
    "HOT_PROJECT_LIMIT",
    "HOT_REFRESH_QUERY_COOLDOWN_SECONDS",
    "UNRESOLVED_FILE_REFRESH_COOLDOWN_SECONDS",
    "note_unresolved_file_miss",
    "reconcile_open_unclassified_activities",
    "request_refresh_for_hot_projects",
    "request_refresh_for_unresolved_file_misses",
    "unresolved_file_indexes_refreshed_since",
]
