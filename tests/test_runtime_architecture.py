from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from worktrace import db
from worktrace.collector.activity_session_recorder import (
    ActivitySessionRecorder,
    OPEN_ACTIVITY_CHECKPOINT_SECONDS,
)
from worktrace.runtime.app_runtime import AppRuntime
from worktrace.services.runtime_activity_state_service import (
    clear_runtime_activity_state,
    publish_runtime_activity_snapshot,
    sample_runtime_activity_state,
)

pytestmark = [
    pytest.mark.collector_runtime,
    pytest.mark.integration,
    pytest.mark.db,
    pytest.mark.serial,
]


def test_duplicate_runtime_does_not_initialize_database(tmp_path, monkeypatch):
    paths = type(
        "Paths",
        (),
        {
            "db_path": str(tmp_path / "worktrace.db"),
            "log_path": str(tmp_path / "worktrace.log"),
        },
    )()
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance",
        lambda: False,
    )
    initialize = Mock()
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.db.initialize_database",
        initialize,
    )

    runtime = AppRuntime(paths)
    assert runtime.initialize() is False
    initialize.assert_not_called()
    assert runtime.owns_application_instance is False


def test_runtime_snapshot_is_process_local_and_typed(temp_db):
    clear_runtime_activity_state("test_start")
    publish_runtime_activity_snapshot(
        {"status": "normal", "elapsed_seconds": 7},
        "test_publish",
    )

    sample = sample_runtime_activity_state()
    assert sample.snapshot == {
        "status": "normal",
        "elapsed_seconds": 7,
    }
    assert sample.revision > 0
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'current_activity_snapshot'"
        ).fetchone()
    assert row is None


def test_runtime_sample_is_detached_from_published_mapping(temp_db):
    clear_runtime_activity_state("test_empty")
    value = {"app": "Editor", "status": "normal"}
    publish_runtime_activity_snapshot(value, "test_publish")
    value["app"] = "Mutated"

    first = sample_runtime_activity_state()
    assert first.snapshot == {"app": "Editor", "status": "normal"}
    assert first.snapshot is not None
    first.snapshot["app"] = "Local mutation"
    assert sample_runtime_activity_state().snapshot == {
        "app": "Editor",
        "status": "normal",
    }


def test_open_activity_progress_is_checkpointed(monkeypatch):
    writes: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "worktrace.collector.activity_session_recorder.persist_open_activity",
        lambda **kwargs: 41,
    )
    monkeypatch.setattr(
        "worktrace.collector.activity_session_recorder.activity_service.set_activity_duration",
        lambda activity_id, seconds: writes.append((activity_id, seconds)),
    )
    recorder = ActivitySessionRecorder()
    recorder.snapshot_publisher = Mock()
    payload = {
        "status": "idle",
        "app_name": "Editor",
        "process_name": "editor.exe",
    }
    signature = ("idle", "editor.exe", "Editor", "")

    recorder.observe(payload, signature, "2026-07-16 00:00:00")
    recorder.observe(payload, signature, "2026-07-16 00:00:29")
    assert writes == []

    recorder.observe(
        payload,
        signature,
        f"2026-07-16 00:00:{OPEN_ACTIVITY_CHECKPOINT_SECONDS:02d}",
    )
    assert writes == [(41, OPEN_ACTIVITY_CHECKPOINT_SECONDS)]


def test_view_model_api_routes_to_one_page_payload_owner():
    root = Path(__file__).resolve().parents[1]
    source = (root / "worktrace/api/view_model_api.py").read_text(
        encoding="utf-8"
    )
    assert "view_model_service" in source
    assert "refresh_state_view_model_service" in source
    assert "overview_view_model_service" not in source
    assert "timeline_view_model_service" not in source
    assert "session_detail_view_model_service" not in source
    assert "view_model_hardening_service" not in source
