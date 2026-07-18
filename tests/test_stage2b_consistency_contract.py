from __future__ import annotations

import threading
from contextlib import contextmanager

import pytest

from worktrace.services import system_project_service

from worktrace import generation_clock
from worktrace.collector.activity_session_recorder import ActivitySessionRecorder
from worktrace.collector.state_machine import CollectorStateMachine
from worktrace.collector.transition_types import ActivityEndReason
from worktrace.data_generation_repository import DataGenerationNamespace
from worktrace.services import (
    folder_rule_service,
    privacy_service,
    project_inference_service,
    project_service,
    rule_service,
    settings_service,
)


def _active_recorder() -> ActivitySessionRecorder:
    recorder = ActivitySessionRecorder()
    recorder.current_payload = {
        "status": "normal",
        "app_name": "Word",
        "process_name": "WINWORD.EXE",
        "window_title": "Contract.docx - Word",
    }
    recorder.current_signature = ("normal", "word", "contract.docx")
    recorder.current_start_time = "2026-07-18 09:00:00"
    recorder.current_last_seen_time = "2026-07-18 09:01:00"
    recorder.persisted_activity_id = 42
    recorder.persisted_checkpoint_seconds = 30
    return recorder


@pytest.mark.unit
@pytest.mark.contract
def test_close_failure_keeps_recorder_state_and_snapshot(monkeypatch):
    recorder = _active_recorder()
    clears: list[str] = []
    monkeypatch.setattr(recorder.snapshot_publisher, "clear", clears.append)

    def fail_close(*args, **kwargs):
        raise RuntimeError("close_failed")

    monkeypatch.setattr(
        "worktrace.collector.activity_session_recorder.lifecycle_close_activity",
        fail_close,
    )

    with pytest.raises(RuntimeError, match="close_failed"):
        recorder.finish_current_activity(
            "2026-07-18 09:02:00",
            ActivityEndReason.RESOURCE_SWITCH,
        )

    assert recorder.current_payload is not None
    assert recorder.current_signature == ("normal", "word", "contract.docx")
    assert recorder.current_start_time == "2026-07-18 09:00:00"
    assert recorder.persisted_activity_id == 42
    assert clears == []


@pytest.mark.unit
@pytest.mark.contract
def test_boundary_failure_keeps_recorder_state(monkeypatch):
    recorder = _active_recorder()
    machine = CollectorStateMachine(recorder=recorder)
    prepared = recorder.stop_for_boundary(
        "2026-07-18 09:02:00",
        ActivityEndReason.STOP_BOUNDARY,
    )

    def fail_boundary(*args, **kwargs):
        raise RuntimeError("boundary_failed")

    monkeypatch.setattr(
        "worktrace.collector.state_machine.activity_lifecycle_service.close_at_boundary",
        fail_boundary,
    )

    with pytest.raises(RuntimeError, match="boundary_failed"):
        machine._commit_boundary("2026-07-18 09:02:00", "user_stop", prepared)

    assert recorder.current_payload is not None
    assert recorder.persisted_activity_id == 42


@pytest.mark.unit
@pytest.mark.contract
def test_stale_prepared_close_cannot_clear_a_new_session():
    recorder = _active_recorder()
    prepared = recorder.prepare_current_activity_close(
        "2026-07-18 09:02:00",
        ActivityEndReason.RESOURCE_SWITCH,
    )
    assert prepared is not None

    recorder._session_serial += 1
    recorder.current_payload = {"status": "normal", "window_title": "New.docx"}
    recorder.current_signature = ("normal", "word", "new.docx")
    recorder.current_start_time = "2026-07-18 09:03:00"
    recorder.persisted_activity_id = 99

    assert recorder.finalize_prepared_close(prepared) is False
    assert recorder.current_payload["window_title"] == "New.docx"
    assert recorder.persisted_activity_id == 99


@pytest.mark.unit
@pytest.mark.contract
def test_generation_load_cannot_overwrite_newer_publication(monkeypatch):
    namespace = DataGenerationNamespace.SETTINGS
    generation_clock.clear()
    read_started = threading.Event()
    allow_old_read = threading.Event()

    @contextmanager
    def fake_connection():
        yield object()

    def load_old(_conn, _namespace):
        read_started.set()
        assert allow_old_read.wait(timeout=5)
        return 1

    monkeypatch.setattr(generation_clock, "get_db_key", lambda: "test-db")
    monkeypatch.setattr(generation_clock, "get_connection", fake_connection)
    monkeypatch.setattr(
        generation_clock.DataGenerationRepository,
        "get",
        staticmethod(load_old),
    )
    monkeypatch.setattr(
        generation_clock.DataGenerationRepository,
        "get_many",
        staticmethod(lambda _conn, _namespaces: {namespace: 2}),
    )

    result: list[int] = []
    thread = threading.Thread(
        target=lambda: result.append(generation_clock.generation(namespace))
    )
    thread.start()
    assert read_started.wait(timeout=5)
    generation_clock.publish_committed(object(), (namespace,))
    allow_old_read.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert result == [2]
    assert generation_clock.generation(namespace) == 2


@pytest.mark.db
@pytest.mark.integration
@pytest.mark.contract
def test_settings_cache_retains_only_current_generation(temp_db):
    settings_service.clear_settings_cache()
    for index in range(25):
        settings_service.set_setting("stage2b_cache_probe", str(index))
        assert settings_service.get_setting("stage2b_cache_probe") == str(index)

    assert settings_service._SETTING_CACHE == {"stage2b_cache_probe": "24"}
    assert settings_service._SETTING_CACHE_DATABASE_KEY is not None
    assert settings_service._SETTING_CACHE_GENERATION is not None


@pytest.mark.db
@pytest.mark.integration
@pytest.mark.contract
def test_rule_caches_replace_their_snapshot_instead_of_accumulating(temp_db):
    project_id = project_service.create_project("Cache Project")
    folder_rule_service.invalidate_folder_rule_cache()
    project_inference_service.invalidate_keyword_rule_cache()

    for index in range(4):
        rule_service.create_rule(f"cache-token-{index}", project_id)
        folder_rule_service.create_or_update_folder_rule(
            rf"D:\CacheProject\{index}",
            project_id,
        )
        project_inference_service._enabled_keyword_rules()
        folder_rule_service._enabled_folder_rules()

    assert isinstance(project_inference_service._KEYWORD_RULE_CACHE, list)
    assert isinstance(folder_rule_service._FOLDER_RULE_CACHE, list)
    assert project_inference_service._KEYWORD_RULE_CACHE_GENERATION is not None
    assert folder_rule_service._FOLDER_RULE_CACHE_GENERATION is not None


@pytest.mark.db
@pytest.mark.integration
@pytest.mark.contract
def test_privacy_cache_replaces_its_snapshot_instead_of_accumulating(temp_db):
    excluded_project_id = system_project_service.require_excluded_project_id()
    project_service.set_project_enabled(excluded_project_id, True)
    privacy_service.clear_exclude_rules_cache()

    for index in range(4):
        rule_service.create_rule(f"private-token-{index}", excluded_project_id)
        snapshot = privacy_service._exclude_rules()
        assert len(snapshot["keywords"]) == index + 1

    assert isinstance(privacy_service._EXCLUDE_RULE_CACHE, dict)
    assert set(privacy_service._EXCLUDE_RULE_CACHE) == {"keywords", "folders"}
    assert privacy_service._EXCLUDE_RULE_CACHE_DATABASE_KEY is not None
    assert privacy_service._EXCLUDE_RULE_CACHE_GENERATION is not None
