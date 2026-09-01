from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The folder runtime keeps the wake-event path for ordinary idle waits, while retry
# backoff is owned by the worker stop event. This preserves the existing fault-
# injection seam and makes retry delay independently cancellable on shutdown.
path = ROOT / "worktrace/services/folder_index_runtime_service.py"
source = path.read_text(encoding="utf-8")
old_reconciliation_wait = '''                        _core._wait_for_worker(
                            max(_core._WORKER_IDLE_SECONDS, retry.delay_seconds)
                        )'''
new_reconciliation_wait = '''                        stop_event.wait(
                            max(_core._WORKER_IDLE_SECONDS, retry.delay_seconds)
                        )'''
if source.count(old_reconciliation_wait) != 1:
    raise RuntimeError(
        f"expected one reconciliation retry wait, found {source.count(old_reconciliation_wait)}"
    )
source = source.replace(old_reconciliation_wait, new_reconciliation_wait, 1)
old_iteration_wait = '''                _core._wait_for_worker(
                    max(_core._WORKER_IDLE_SECONDS, retry.delay_seconds)
                )'''
new_iteration_wait = '''                stop_event.wait(
                    max(_core._WORKER_IDLE_SECONDS, retry.delay_seconds)
                )'''
if source.count(old_iteration_wait) != 1:
    raise RuntimeError(
        f"expected one iteration retry wait, found {source.count(old_iteration_wait)}"
    )
path.write_text(source.replace(old_iteration_wait, new_iteration_wait, 1), encoding="utf-8")

# The core transient-failure regression must bypass the compatibility runtime wrapper
# because the wrapper intentionally performs an eligibility database read first.
path = ROOT / "tests/test_worker_retry_health_contract.py"
source = path.read_text(encoding="utf-8")
import_anchor = "from worktrace.services import folder_index_service\n"
if source.count(import_anchor) != 1:
    raise RuntimeError("folder_index_service import anchor changed")
source = source.replace(
    import_anchor,
    import_anchor + "from worktrace.services import folder_index_runtime_service\n",
    1,
)
old_call = "        folder_index_service.rebuild_folder_index(3)\n"
new_call = "        folder_index_runtime_service._CORE_REBUILD_FOLDER_INDEX(3)\n"
if source.count(old_call) != 1:
    raise RuntimeError(f"expected one core rebuild test call, found {source.count(old_call)}")
path.write_text(source.replace(old_call, new_call, 1), encoding="utf-8")

# Existing liveness regression now asserts the stable infrastructure code and lets the
# new startup reconciliation phase be the point that stops the synthetic worker.
path = ROOT / "tests/test_database_worker_liveness_regressions.py"
source = path.read_text(encoding="utf-8")
old_validate = '''    def validate(_stop) -> None:
        stop.set()

    monkeypatch.setattr(
        folder_index_runtime_service,
        "validate_ready_indexes",
        validate,
    )

    folder_index_runtime_service.run_folder_index_worker(stop, health=health)

    assert ensure_attempts == 2
    assert health.failures == ["folder_index_startup_failed"]
    assert health.successes == 1
'''
new_validate = '''    def validate(_stop) -> None:
        return None

    monkeypatch.setattr(
        folder_index_runtime_service,
        "validate_ready_indexes",
        validate,
    )

    def reconcile():
        stop.set()
        return (
            folder_index_runtime_service.folder_index_maintenance_service.FolderReconciliationOutcome()
        )

    monkeypatch.setattr(
        folder_index_runtime_service.folder_index_maintenance_service,
        "reconcile_open_unclassified_activities_outcome",
        reconcile,
    )

    folder_index_runtime_service.run_folder_index_worker(stop, health=health)

    assert ensure_attempts == 2
    assert health.failures == ["database_busy"]
    assert health.successes == 1
'''
if source.count(old_validate) != 1:
    raise RuntimeError("folder startup liveness regression shape changed")
path.write_text(source.replace(old_validate, new_validate, 1), encoding="utf-8")
