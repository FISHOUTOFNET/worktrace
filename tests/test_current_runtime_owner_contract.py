from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.collector_runtime]

ROOT = Path(__file__).resolve().parents[1]


def test_current_runtime_has_no_retired_secondary_owners() -> None:
    assert not (ROOT / "worktrace/runtime/app_runtime_core.py").exists()
    assert not (ROOT / "worktrace/services/secure_backup_core.py").exists()
    assert not (ROOT / "worktrace/schema_migrations.py").exists()


def test_closed_activity_inference_has_one_consumer_boundary() -> None:
    runtime = (ROOT / "worktrace/runtime/app_runtime.py").read_text(encoding="utf-8")
    lifecycle = (
        ROOT / "worktrace/services/activity_lifecycle_service.py"
    ).read_text(encoding="utf-8")
    clipboard = (ROOT / "worktrace/services/clipboard_service.py").read_text(
        encoding="utf-8"
    )
    resources = (
        ROOT / "worktrace/services/activity_resource_command_service.py"
    ).read_text(encoding="utf-8")

    assert runtime.count("start_inference_worker(") == 1
    assert "process_pending_inference_jobs(" not in runtime
    assert "process_new_activity(" not in lifecycle
    assert "process_pending_inference_jobs(" not in clipboard
    assert "process_pending_inference_jobs(" not in resources
