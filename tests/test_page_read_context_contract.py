from __future__ import annotations

import threading

import pytest

from tests.support.activity_factory import create_closed_activity
from worktrace.db import get_connection, now_str
from worktrace.services.page_read_context import (
    current_page_read_context,
    page_read_scope,
)
from worktrace.services.report_projection_snapshot_service import build_visible_snapshot
from worktrace.services.report_revision_service import get_report_structure_revision
from worktrace.services.runtime_activity_state_service import (
    publish_runtime_activity_snapshot,
    sample_runtime_activity_state,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.serial]

DATE = "2026-07-16"


def test_page_scope_freezes_runtime_sample_and_snapshot_cache(temp_db):
    publish_runtime_activity_snapshot(
        {"status": "normal", "start_time": f"{DATE} 09:00:00", "app_name": "A"},
        "page_context_test_initial",
    )

    with page_read_scope() as context:
        assert current_page_read_context() is context
        first_sample = sample_runtime_activity_state()
        first_snapshot = build_visible_snapshot(DATE, DATE)

        publish_runtime_activity_snapshot(
            {"status": "normal", "start_time": f"{DATE} 10:00:00", "app_name": "B"},
            "page_context_test_update",
        )

        assert sample_runtime_activity_state() == first_sample
        assert build_visible_snapshot(DATE, DATE) is first_snapshot

    assert sample_runtime_activity_state().snapshot["app_name"] == "B"


def test_page_revision_and_projection_share_one_read_transaction(temp_db):
    activity_id = create_closed_activity(
        day=DATE,
        start="09:00:00",
        end="09:30:00",
        window_title="Contract.docx",
    )
    writer_errors: list[BaseException] = []

    with page_read_scope():
        revision_before = get_report_structure_revision(DATE)
        snapshot_before = build_visible_snapshot(DATE, DATE)

        def write_structure_change() -> None:
            try:
                with get_connection() as conn:
                    conn.execute(
                        "UPDATE activity_log SET status = ?, updated_at = ? WHERE id = ?",
                        ("idle", now_str(), activity_id),
                    )
            except BaseException as exc:  # pragma: no cover - assertion reports it
                writer_errors.append(exc)

        writer = threading.Thread(target=write_structure_change)
        writer.start()
        writer.join(timeout=5)

        assert not writer.is_alive()
        assert writer_errors == []
        assert get_report_structure_revision(DATE) == revision_before
        assert build_visible_snapshot(DATE, DATE) is snapshot_before

    assert get_report_structure_revision(DATE) != revision_before
