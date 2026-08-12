from __future__ import annotations

import pytest

from worktrace.db import get_connection
from worktrace.integrations.fd_work.binding_repository import FDWorkBindingRepository
from worktrace.integrations.fd_work.guarded_binding_service import GuardedFDWorkBindingService
from worktrace.platforms.base import ActiveWindow
from worktrace.runtime.external_state_warning_services import _surface_external_warning
from worktrace.services import (
    folder_index_maintenance_service,
    folder_index_service,
    folder_rule_service,
    privacy_service,
    project_service,
    rule_catalog_command_service,
)

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def _index_state(rule_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM folder_rule_index_state WHERE folder_rule_id = ?",
            (int(rule_id),),
        ).fetchone()
    return dict(row) if row else None


def test_folder_index_lifecycle_follows_rule_enablement(temp_db):
    project_id = project_service.create_project("Lifecycle Rule")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\LifecycleRule",
        project_id,
        True,
    )
    folder_index_service.ensure_index_states_for_folder_rules()
    assert _index_state(rule_id) is not None

    assert rule_catalog_command_service.set_folder_rule_enabled(rule_id, False)
    folder_index_service.ensure_index_states_for_folder_rules()
    assert _index_state(rule_id) is None

    assert rule_catalog_command_service.set_folder_rule_enabled(rule_id, True)
    folder_index_service.ensure_index_states_for_folder_rules()
    state = _index_state(rule_id)
    assert state is not None
    assert state["active_generation"] is None
    assert int(state["refresh_requested"] or 0) == 1


def test_folder_index_lifecycle_follows_project_enablement(temp_db):
    project_id = project_service.create_project("Lifecycle Project")
    rule_id = folder_rule_service.create_or_update_folder_rule(
        r"D:\LifecycleProject",
        project_id,
        True,
    )
    folder_index_service.ensure_index_states_for_folder_rules()
    assert _index_state(rule_id) is not None

    project_service.set_project_enabled(project_id, False)
    folder_index_service.ensure_index_states_for_folder_rules()
    assert _index_state(rule_id) is None

    project_service.set_project_enabled(project_id, True)
    folder_index_service.ensure_index_states_for_folder_rules()
    state = _index_state(rule_id)
    assert state is not None
    assert state["active_generation"] is None
    assert int(state["refresh_requested"] or 0) == 1


def test_failed_project_refresh_does_not_consume_cooldown(
    temp_db,
    monkeypatch,
):
    project_id = project_service.create_project("Retryable Refresh")
    folder_rule_service.create_or_update_folder_rule(
        r"D:\RetryableRefresh",
        project_id,
        True,
    )
    with folder_index_maintenance_service._REFRESH_CACHE_LOCK:
        folder_index_maintenance_service._PROJECT_REFRESH_TIMES.clear()

    calls: list[tuple[int, ...]] = []

    def fail_queue(rule_ids):
        calls.append(tuple(rule_ids))
        raise RuntimeError("transient enqueue failure")

    monkeypatch.setattr(
        folder_index_maintenance_service,
        "_queue_rule_ids",
        fail_queue,
    )
    with pytest.raises(RuntimeError, match="transient enqueue failure"):
        folder_index_maintenance_service.request_refresh_for_project(project_id)

    monkeypatch.setattr(
        folder_index_maintenance_service,
        "_queue_rule_ids",
        lambda rule_ids: calls.append(tuple(rule_ids)) or len(rule_ids),
    )
    assert folder_index_maintenance_service.request_refresh_for_project(project_id) == 1
    assert len(calls) == 2


def _binding_service(repository, epoch: int):
    project = {
        "id": 7,
        "name": "26IP0165 IPDD_Miragene",
        "created_at": "2026-08-01T00:00:00+00:00",
    }
    return GuardedFDWorkBindingService(
        repository,
        database_identity_reader=lambda: ("C:/WorkTrace/worktrace.db", epoch),
        project_reader=lambda project_id: project if int(project_id) == 7 else None,
        project_list_reader=lambda: [project],
    )


def test_fd_work_binding_cannot_survive_main_database_epoch_change(tmp_path):
    repository = FDWorkBindingRepository(tmp_path / "state.db")
    before = _binding_service(repository, 1)
    before.bind_project(7, "26IP0165 IPDD_Miragene")
    assert before.is_project_bound(7, "26IP0165 IPDD_Miragene")

    after_restart = _binding_service(repository, 2)

    assert not after_restart.is_project_bound(7, "26IP0165 IPDD_Miragene")
    assert repository.get_binding(7) is None


def test_external_state_warning_is_visible_in_normal_success_message():
    result = _surface_external_warning(
        {
            "ok": True,
            "message": "加密备份已导入",
            "external_state_warning": "旧外部项目关联清理失败",
        }
    )

    assert result["message"] == "加密备份已导入；旧外部项目关联清理失败"


def test_uncertain_path_probe_fails_closed_when_folder_privacy_rules_exist(temp_db):
    project_service.set_excluded_project_enabled(True)
    rule_catalog_command_service.create_or_update_excluded_folder_rule(
        r"D:\Private",
        recursive=True,
    )

    decision = privacy_service.evaluate_exclusion(
        ActiveWindow(
            app_name="Word",
            process_name="winword.exe",
            window_title="Confidential - Word",
            path_resolution_uncertain=True,
        )
    )

    assert decision.excluded is True
    assert decision.resolution_pending is True
    assert decision.refresh_required is False


def test_uncertain_path_probe_is_not_privacy_blocking_without_folder_rules(temp_db):
    decision = privacy_service.evaluate_exclusion(
        ActiveWindow(
            app_name="Word",
            process_name="winword.exe",
            window_title="Document1 - Word",
            path_resolution_uncertain=True,
        )
    )

    assert decision.excluded is False
    assert decision.resolution_pending is False
