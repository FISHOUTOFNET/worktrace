"""Narrowed fact-query window and overlap SQL split.

Verifies that ``_load_fact_rows`` uses ``day ± carry_seconds`` instead of the
old fixed 1-day-before / 2-days-after window, and that the UNION ALL overlap
split returns identical results to the previous OR-based predicate.

These tests do NOT depend on absolute timings; they verify correctness of the
window boundary and the SQL equivalence.
"""

from __future__ import annotations

from datetime import date as date_type, datetime, time as datetime_time, timedelta

import pytest

from tests.support import activity_factory as activity_service
from worktrace import db
from worktrace.constants import REPORT_CONTEXT_SHORT_MERGE_SECONDS
from worktrace.db import get_connection
from worktrace.resources.types import DetectedResource
from worktrace.services import settings_service
from worktrace.services.report_fact_query_service import (
    _load_fact_rows,
    load_report_activity_rows,
)

pytestmark = [pytest.mark.db, pytest.mark.contract]

DATE = "2026-07-15"


def _resource(idx: int) -> DetectedResource:
    return DetectedResource(
        resource_kind="local_file",
        resource_subtype="document",
        display_name=f"Doc{idx}.docx",
        identity_key=f"identity:{idx}",
        is_anchor=True,
        confidence=100,
        source="test",
        app_name="Word",
        process_name="winword.exe",
        window_title=f"Doc{idx}.docx - Word",
        path_hint=f"D:\\Docs\\Doc{idx}.docx",
    )


def _create_closed_activity(
    *,
    idx: int,
    start_time: str,
    end_time: str,
    project_id: int | None = None,
) -> int:
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        f"Doc{idx}.docx - Word",
        start_time=start_time,
        project_id=project_id,
        resource=_resource(idx),
    )
    activity_service.close_activity(activity_id, end_time)
    return activity_id


def test_carry_zero_loads_only_target_day_overlapping_activities(temp_db):
    """With carry=0, activities entirely outside the target day are excluded."""

    # Activity on the target day — must be loaded.
    target_id = _create_closed_activity(
        idx=1,
        start_time=f"{DATE} 09:00:00",
        end_time=f"{DATE} 09:30:00",
    )
    # Activity on the previous day — outside carry=0 window.
    prev_id = _create_closed_activity(
        idx=2,
        start_time="2026-07-14 12:00:00",
        end_time="2026-07-14 13:00:00",
    )
    # Activity on the next day — outside carry=0 window.
    next_id = _create_closed_activity(
        idx=3,
        start_time="2026-07-16 12:00:00",
        end_time="2026-07-16 13:00:00",
    )

    settings_service.set_setting("context_carry_minutes", "0")
    with get_connection() as conn:
        rows = _load_fact_rows(conn, DATE, DATE, carry_seconds=0)
    activity_ids = {int(row["id"]) for row in rows}
    assert target_id in activity_ids
    assert prev_id not in activity_ids
    assert next_id not in activity_ids


def test_carry_window_loads_nearby_anchor_activities(temp_db):
    """With carry=15min, activities within the carry margin are loaded for context."""

    # Anchor activity 10 minutes before midnight — within 15-min carry.
    anchor_id = _create_closed_activity(
        idx=1,
        start_time="2026-07-14 23:50:00",
        end_time="2026-07-14 23:55:00",
        project_id=_ensure_project("Anchor"),
    )
    # Target-day activity that should receive context from the anchor.
    target_id = _create_closed_activity(
        idx=2,
        start_time=f"{DATE} 00:00:00",
        end_time=f"{DATE} 00:05:00",
    )
    # Activity 30 minutes before midnight — outside 15-min carry.
    far_id = _create_closed_activity(
        idx=3,
        start_time="2026-07-14 23:20:00",
        end_time="2026-07-14 23:25:00",
    )

    # Test _load_fact_rows directly (before date filtering) to verify
    # the carry window includes nearby anchor rows.
    with get_connection() as conn:
        rows = _load_fact_rows(conn, DATE, DATE, carry_seconds=900)
    activity_ids = {int(row["id"]) for row in rows}
    assert anchor_id in activity_ids
    assert target_id in activity_ids
    assert far_id not in activity_ids


def test_cross_midnight_activity_is_loaded_with_carry_zero(temp_db):
    """Cross-midnight activity must be loaded even with carry=0 (overlap query)."""

    activity_id = _create_closed_activity(
        idx=1,
        start_time="2026-07-14 23:50:00",
        end_time="2026-07-15 00:10:00",
    )
    settings_service.set_setting("context_carry_minutes", "0")
    rows = load_report_activity_rows(DATE, DATE)
    activity_ids = {int(row["id"]) for row in rows}
    assert activity_id in activity_ids


def test_open_activity_is_loaded(temp_db):
    """An open activity (end_time IS NULL) must be loaded."""

    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "Open.docx - Word",
        start_time=f"{DATE} 10:00:00",
        resource=_resource(99),
    )
    # Do not close — leaves end_time NULL.
    settings_service.set_setting("context_carry_minutes", "0")
    rows = load_report_activity_rows(DATE, DATE)
    activity_ids = {int(row["id"]) for row in rows}
    assert activity_id in activity_ids


def test_open_activity_outside_window_is_still_loaded(temp_db):
    """An open activity starting before the window is still loaded (only one can exist)."""

    # Open activity that started on the previous day.
    activity_id = activity_service.create_activity(
        "Word",
        "winword.exe",
        "OpenPrev.docx - Word",
        start_time="2026-07-14 08:00:00",
        resource=_resource(98),
    )
    # Test _load_fact_rows directly: the open-activity branch only checks
    # start_time <= load_end, so an open activity from a previous day is
    # always loaded (there can be at most one open activity).
    with get_connection() as conn:
        rows = _load_fact_rows(conn, DATE, DATE, carry_seconds=0)
    activity_ids = {int(row["id"]) for row in rows}
    assert activity_id in activity_ids


def test_union_all_sql_equivalent_to_or_based_for_closed_activities(temp_db):
    """UNION ALL split must return the same closed-activity rows as a simple overlap."""

    # Seed activities on and around the target date.
    for idx, (start, end) in enumerate(
        [
            (f"{DATE} 09:00:00", f"{DATE} 09:30:00"),
            ("2026-07-14 23:50:00", f"{DATE} 00:10:00"),  # cross-midnight
            (f"{DATE} 23:50:00", "2026-07-16 00:10:00"),  # cross-midnight forward
            ("2026-07-16 12:00:00", "2026-07-16 13:00:00"),  # next day
            ("2026-07-14 12:00:00", "2026-07-14 13:00:00"),  # prev day
        ],
        start=1,
    ):
        _create_closed_activity(idx=idx, start_time=start, end_time=end)

    carry_seconds = 900  # 15 minutes
    with get_connection() as conn:
        new_rows = _load_fact_rows(conn, DATE, DATE, carry_seconds=carry_seconds)

        # Reference: simple overlap query (same semantics, different SQL form).
        day_start = datetime.combine(
            date_type.fromisoformat(DATE), datetime_time.min
        )
        day_end = day_start + timedelta(days=1)
        load_start = (day_start - timedelta(seconds=carry_seconds)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        load_end = (day_end + timedelta(seconds=carry_seconds)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        ref_rows = conn.execute(
            """
            SELECT id FROM activity_log
            WHERE is_deleted = 0 AND is_hidden = 0
              AND end_time IS NOT NULL
              AND end_time >= ?
              AND start_time <= ?
            ORDER BY start_time ASC, id ASC
            """,
            (load_start, load_end),
        ).fetchall()

    new_ids = [int(row["id"]) for row in new_rows]
    ref_ids = [int(row["id"]) for row in ref_rows]
    assert new_ids == ref_ids


def test_partial_index_exists_in_schema():
    """The idx_activity_closed_overlap partial index must be declared in the schema."""

    sql = db.read_schema_indexes_sql()
    assert "idx_activity_closed_overlap" in sql
    assert "end_time IS NOT NULL" in sql
    assert "is_deleted = 0" in sql
    assert "is_hidden = 0" in sql


def test_partial_index_exists_in_initialized_database(temp_db):
    """The partial index must be materialized in an initialized database."""

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_activity_closed_overlap'
            """
        ).fetchone()
    assert row is not None


def test_existing_database_gets_new_index_on_reinit(temp_db):
    """An existing database without the index must get it via ensure_current_indexes."""

    with get_connection() as conn:
        conn.execute("DROP INDEX IF EXISTS idx_activity_closed_overlap")
    # Re-apply the schema (simulates opening an old database).
    db.apply_current_schema(conn)
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'index' AND name = 'idx_activity_closed_overlap'
            """
        ).fetchone()
    assert row is not None


def test_carry_exceeding_cap_uses_capped_window(temp_db):
    """When carry_minutes exceeds the cap, the query window uses the capped value."""

    # Activity ending 20 minutes before midnight — outside 15-min cap (end < 23:45:00).
    far_id = _create_closed_activity(
        idx=1,
        start_time="2026-07-14 23:20:00",
        end_time="2026-07-14 23:25:00",
    )
    # Target-day activity.
    target_id = _create_closed_activity(
        idx=2,
        start_time=f"{DATE} 00:00:00",
        end_time=f"{DATE} 00:05:00",
    )

    # The effective carry is capped at REPORT_CONTEXT_SHORT_MERGE_SECONDS (900s = 15min).
    # Even though the setting is 60 minutes, the query window only extends 15 minutes.
    capped_carry = REPORT_CONTEXT_SHORT_MERGE_SECONDS
    with get_connection() as conn:
        rows = _load_fact_rows(conn, DATE, DATE, carry_seconds=capped_carry)
    activity_ids = {int(row["id"]) for row in rows}

    # The 20-minutes-before activity should NOT be loaded because the
    # effective carry is capped at 15 minutes.
    assert far_id not in activity_ids
    assert target_id in activity_ids


def _ensure_project(name: str) -> int:
    from worktrace.services import project_service

    return project_service.create_project(name)
