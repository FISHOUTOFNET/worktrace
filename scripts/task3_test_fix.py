from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Retry backoff belongs to the worker stop event; ordinary idle waits still use the
# folder wake event. Match by call shape rather than fixed indentation.
path = ROOT / "worktrace/services/folder_index_runtime_service.py"
source = path.read_text(encoding="utf-8")
pattern = re.compile(
    r"(?m)^(?P<indent>\s*)_core\._wait_for_worker\(\n"
    r"\s*max\(_core\._WORKER_IDLE_SECONDS, retry\.delay_seconds\)\n"
    r"\s*\)"
)


def replace_retry_wait(match: re.Match[str]) -> str:
    indent = match.group("indent")
    return (
        f"{indent}stop_event.wait(\n"
        f"{indent}    max(_core._WORKER_IDLE_SECONDS, retry.delay_seconds)\n"
        f"{indent})"
    )


source, count = pattern.subn(replace_retry_wait, source)
if count != 2:
    raise RuntimeError(f"expected two folder retry waits, found {count}")
path.write_text(source, encoding="utf-8")

# Test the captured core scanner directly; the compatibility runtime wrapper performs
# an eligibility database read before delegating to the core implementation.
path = ROOT / "tests/test_worker_retry_health_contract.py"
source = path.read_text(encoding="utf-8")
anchor = "from worktrace.services import folder_index_service\n"
if source.count(anchor) != 1:
    raise RuntimeError("folder_index_service import anchor changed")
source = source.replace(
    anchor,
    anchor + "from worktrace.services import folder_index_runtime_service\n",
    1,
)
old_call = "        folder_index_service.rebuild_folder_index(3)\n"
new_call = "        folder_index_runtime_service._CORE_REBUILD_FOLDER_INDEX(3)\n"
if source.count(old_call) != 1:
    raise RuntimeError(f"expected one core rebuild test call, found {source.count(old_call)}")
path.write_text(source.replace(old_call, new_call, 1), encoding="utf-8")

# The startup liveness regression now asserts the stable database-busy code and lets
# the explicit reconciliation phase terminate the synthetic worker iteration.
path = ROOT / "tests/test_database_worker_liveness_regressions.py"
source = path.read_text(encoding="utf-8")
old = '''    def validate(_stop) -> None:
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
new = '''    def validate(_stop) -> None:
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
if source.count(old) != 1:
    raise RuntimeError("folder startup liveness regression shape changed")
path.write_text(source.replace(old, new, 1), encoding="utf-8")
