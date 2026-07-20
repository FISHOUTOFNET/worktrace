from __future__ import annotations

import threading
from pathlib import Path

import pytest

from worktrace import db
from worktrace.collector.collector import CollectorControl, CollectorHoldState
from worktrace.constants import EXCLUDED_PROJECT, UNCATEGORIZED_PROJECT
from worktrace.platforms.base import ActiveWindow
from worktrace.runtime.contracts import (
    RuntimeStartResult,
    WorkerStartupState,
    WorkerStartupStatus,
)
from worktrace.services import (
    privacy_service,
    project_service,
    rule_catalog_command_service,
    rule_service,
)
from worktrace.services.keyword_rule_policy import ProjectRuleWriteError
from worktrace.services.project_command_policy import ProjectLifecycleError

pytestmark = [pytest.mark.db, pytest.mark.integration, pytest.mark.contract]


def test_keyword_normalizer_is_durable_and_unique(temp_db):
    project_id = project_service.create_project("Keyword Owner")
    rule_id = rule_service.create_rule("  Client Matter  ", project_id)
    row = rule_service.get_rule(rule_id)
    assert row is not None
    assert row["keyword"] == "Client Matter"
    assert row["normalized_pattern"] == "client matter"
    with pytest.raises(ProjectRuleWriteError, match="duplicate_rule"):
        rule_service.create_rule("CLIENT MATTER", project_id)


def test_keyword_uniqueness_applies_to_direct_command_and_self_update(temp_db):
    project_id = project_service.create_project("Direct Command")
    first = rule_catalog_command_service.create_keyword_rule("Alpha", project_id)
    assert rule_catalog_command_service.update_keyword_rule(first, " alpha ") is True
    with pytest.raises(ProjectRuleWriteError, match="duplicate_rule"):
        rule_catalog_command_service.create_keyword_rule("ALPHA", project_id)


def test_same_normalized_keyword_is_allowed_in_different_projects(temp_db):
    first_project = project_service.create_project("First Project")
    second_project = project_service.create_project("Second Project")
    rule_service.create_rule("Matter", first_project)
    rule_service.create_rule(" matter ", second_project)


def test_concurrent_duplicate_keyword_write_has_one_durable_winner(temp_db):
    project_id = project_service.create_project("Concurrent Rules")
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def writer(value: str) -> None:
        barrier.wait(timeout=5)
        try:
            rule_service.create_rule(value, project_id)
            outcomes.append("created")
        except ProjectRuleWriteError as exc:
            outcomes.append(exc.code)

    threads = [
        threading.Thread(target=writer, args=("Concurrent",), daemon=True),
        threading.Thread(target=writer, args=(" concurrent ",), daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(outcomes) == ["created", "duplicate_rule"]
    assert len(rule_service.list_rules()) == 1


def test_project_lifecycle_invariants_are_service_owned(temp_db):
    with db.get_connection() as conn:
        reserved = conn.execute(
            "SELECT id FROM project WHERE name = ?",
            (UNCATEGORIZED_PROJECT,),
        ).fetchone()
        excluded = conn.execute(
            "SELECT id FROM project WHERE name = ?",
            (EXCLUDED_PROJECT,),
        ).fetchone()
    assert reserved is not None and excluded is not None
    for project_id in (int(reserved["id"]), int(excluded["id"])):
        with pytest.raises(ProjectLifecycleError, match="system_project"):
            project_service.archive_project(project_id)
        with pytest.raises(ProjectLifecycleError, match="system_project"):
            project_service.soft_delete_project(project_id)
    with pytest.raises(ProjectLifecycleError, match="system_project"):
        project_service.set_project_enabled(int(reserved["id"]), False)


def test_archived_project_cannot_be_new_rule_target(temp_db):
    project_id = project_service.create_project("Archive Target")
    project_service.archive_project(project_id)
    with pytest.raises(ProjectRuleWriteError, match="project_not_found"):
        rule_service.create_rule("blocked", project_id)


def test_privacy_evaluation_is_read_only_and_fail_closed(temp_db, monkeypatch):
    monkeypatch.setattr(
        privacy_service,
        "get_connection",
        lambda: (_ for _ in ()).throw(AssertionError("unexpected connection")),
    )
    monkeypatch.setattr(
        privacy_service,
        "_exclude_rules",
        lambda **_kwargs: {
            "keywords": [],
            "folders": [
                {
                    "folder_path": "D:/Secret",
                    "normalized_folder_key": "d:/secret",
                    "recursive": 1,
                }
            ],
        },
    )
    window = ActiveWindow(
        "Word",
        "winword.exe",
        "Unknown.docx",
        None,
        privacy_path_required=True,
    )
    decision = privacy_service.evaluate_exclusion(window)
    assert decision.excluded is True
    assert decision.resolution_pending is True
    assert decision.refresh_required is True


def test_live_clock_contract_is_exact_key_set():
    from worktrace.services.activity_live_clock import build_suppressed_live_clock

    assert set(build_suppressed_live_clock()) == {
        "sampled_at_epoch_ms",
        "started_at_epoch_ms",
        "elapsed_seconds_at_sample",
        "aggregate_base_seconds",
        "duration_semantic",
        "is_live",
        "live_state",
        "display_span_id",
        "stable_live_key_hash",
    }


def test_runtime_start_result_is_worker_mapping_only():
    result = RuntimeStartResult(
        ok=True,
        collector_ready=True,
        workers={
            "inference": WorkerStartupStatus(
                WorkerStartupState.READY,
                True,
            )
        },
    ).to_dict()
    assert set(result["workers"]) == {"inference"}
    forbidden = {
        "folder_index_ready",
        "history_worker_ready",
        "inference_worker_ready",
        "resource_repair_worker_ready",
        "startup_recovery_worker_ready",
        "background_worker_degraded",
        "failed_workers",
    }
    assert forbidden.isdisjoint(result)


def test_collector_maintenance_hold_has_explicit_terminal_states():
    control = CollectorControl()
    assert control.hold_state is CollectorHoldState.OPERATIONAL
    assert {state.value for state in CollectorHoldState} == {
        "operational",
        "hold_requested",
        "sealing",
        "held",
        "resetting",
        "release_requested",
    }


def test_production_has_no_runtime_service_locator_or_second_coordinator():
    root = Path(__file__).resolve().parents[1]
    app_api = (root / "worktrace/api/app_api.py").read_text(encoding="utf-8")
    bridge = (root / "worktrace/webview_ui/bridge.py").read_text(encoding="utf-8")
    maintenance = (
        root / "worktrace/services/database_maintenance_service.py"
    ).read_text(encoding="utf-8")
    assert "_RUNTIME" not in app_api
    assert "get_runtime" not in app_api
    assert "ApplicationServices" in bridge
    assert maintenance.count("class RuntimeMaintenanceCoordinator") == 1


def test_shipping_frontend_contains_only_liveclock_v2_names():
    root = Path(__file__).resolve().parents[1] / "worktrace/webview_ui/js"
    source = "\n".join(
        (root / name).read_text(encoding="utf-8")
        for name in ("core.js", "init.js", "overview.js", "timeline.js")
    )
    forbidden = {
        "duration_seconds_at_sample",
        "carry_seconds",
        "live_started_at_epoch_ms",
        "sample_epoch_ms",
        "current_live_duration_seconds",
        "persisted_duration_seconds",
        "active_elapsed_at_sample",
        "current_elapsed_at_sample",
        "current_duration_live",
        "project_duration_live",
        "is_project_duration_live",
        "live_delta_eligible",
        "is_live_projected",
    }
    assert forbidden.isdisjoint(source)


def test_view_model_api_requires_explicit_runtime_context():
    root = Path(__file__).resolve().parents[1]
    source = (root / "worktrace/api/view_model_api.py").read_text(encoding="utf-8")
    assert "collector_status or {}" not in source
    assert 'raise ValueError("runtime_missing")' in source
    assert 'raise ValueError("collector_status_missing")' in source
