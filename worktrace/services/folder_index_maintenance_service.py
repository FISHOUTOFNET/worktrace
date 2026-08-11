"""Bounded maintenance policy for durable folder-rule indexes.

This module owns refresh *selection* only. The folder-index service remains the
single scanner/index writer; callers enqueue rule rebuilds through its public
command boundary. Ordinary filename-index misses never call this module.
"""

from __future__ import annotations

import logging
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
PROJECT_REFRESH_COOLDOWN_SECONDS = 60.0

_PROJECT_REFRESH_TIMES: dict[tuple[str, int, int], float] = {}


def _replacement_cache_identity() -> tuple[str, int]:
    database_key = str(get_db_path().resolve())
    with get_connection() as conn:
        replacement_epoch = DataGenerationRepository.get(
            conn,
            DataGenerationNamespace.DATABASE_REPLACEMENT,
        )
    return database_key, replacement_epoch


def _queue_rule_ids(rule_ids: list[int]) -> int:
    if not rule_ids:
        return 0
    # Function-local import avoids a module-import cycle: folder_index_service
    # calls this maintenance policy from its worker loop.
    from . import folder_index_service

    queued = 0
    for rule_id in rule_ids:
        folder_index_service.request_rebuild_for_rule(int(rule_id))
        queued += 1
    return queued


def request_refresh_for_project(project_id: int) -> int:
    """Queue enabled folder rules for one concrete project.

    This is the strong user-signal path (for example a manual Timeline project
    correction). It deliberately bypasses the normal 15-minute freshness gate,
    but repeated requests for the same project are coalesced for 60 seconds.
    """

    value = int(project_id)
    if value <= 0:
        return 0
    database_key, replacement_epoch = _replacement_cache_identity()
    cache_key = (database_key, replacement_epoch, value)
    current = time.monotonic()
    elapsed = current - _PROJECT_REFRESH_TIMES.get(cache_key, 0.0)
    if elapsed < PROJECT_REFRESH_COOLDOWN_SECONDS:
        return 0

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT fpr.id
            FROM folder_project_rule fpr
            JOIN project p ON p.id = fpr.project_id
            WHERE fpr.project_id = ?
              AND fpr.enabled = 1
              AND p.enabled = 1
              AND COALESCE(p.is_archived, 0) = 0
              AND COALESCE(p.is_deleted, 0) = 0
              AND p.name NOT IN (?, ?)
            ORDER BY fpr.id
            """,
            (value, UNCATEGORIZED_PROJECT, EXCLUDED_PROJECT),
        ).fetchall()
    rule_ids = [int(row["id"]) for row in rows]
    if not rule_ids:
        return 0
    queued = _queue_rule_ids(rule_ids)
    if queued:
        _PROJECT_REFRESH_TIMES[cache_key] = current
    return queued


def request_refresh_for_hot_projects() -> int:
    """Queue only stale indexes belonging to currently hot projects.

    Hot projects are the union of projects used during the last seven days and
    the ten most recently used projects. A ready index is not rebuilt more often
    than every 15 minutes. New/pending rules are already covered by their durable
    refresh marker and are therefore not redundantly re-requested here.
    """

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
    return _queue_rule_ids([int(row["id"]) for row in rows])


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
    "PROJECT_REFRESH_COOLDOWN_SECONDS",
    "reconcile_open_unclassified_activities",
    "request_refresh_for_hot_projects",
    "request_refresh_for_project",
]
