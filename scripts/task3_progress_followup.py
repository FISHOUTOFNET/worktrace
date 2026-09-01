from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    source = target.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(f"{path}: expected one match, found {source.count(old)}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


# Health progress is a liveness signal only: it must not clear a degraded/failure episode.
replace_once(
    "worktrace/worker_health.py",
    '''    def mark_success(self, name: str) -> None:\n''',
    '''    def mark_progress(self, name: str) -> None:\n        with self._lock:\n            current = self._states.setdefault(name, WorkerHealthSnapshot(name))\n            self._states[name] = replace(\n                current,\n                started=True,\n                running=True,\n                served=True,\n                last_progress_monotonic=self._monotonic(),\n            )\n\n    def mark_success(self, name: str) -> None:\n''',
)
replace_once(
    "worktrace/worker_health.py",
    '''    def succeeded(self) -> None:\n        self._registry.mark_success(self.name)\n\n    def failed(self, code: str | WorkerFailure) -> None:\n''',
    '''    def progressed(self) -> None:\n        self._registry.mark_progress(self.name)\n\n    def succeeded(self) -> None:\n        self._registry.mark_success(self.name)\n\n    def failed(self, code: str | WorkerFailure) -> None:\n''',
)

# AppRuntime owns the serving handshake. A partial/degraded iteration is still proof
# that the worker is serving; ordinary hard failures remain non-serving until recovery.
replace_once(
    "worktrace/runtime/app_runtime.py",
    '''from ..worker_health import WorkerHealthRegistry, WorkerHealthReporter\n''',
    '''from ..worker_health import WorkerFailure, WorkerHealthRegistry, WorkerHealthReporter\n''',
)
replace_once(
    "worktrace/runtime/app_runtime.py",
    '''    def succeeded(self) -> None:\n        self._handle.serving_event.set()\n        self._health.succeeded()\n        self._on_health_change()\n\n    def failed(self, code: str) -> None:\n        self._health.failed(code)\n        self._on_health_change()\n''',
    '''    def progressed(self) -> None:\n        self._handle.serving_event.set()\n        self._health.progressed()\n        self._on_health_change()\n\n    def succeeded(self) -> None:\n        self._handle.serving_event.set()\n        self._health.succeeded()\n        self._on_health_change()\n\n    def failed(self, code: str | WorkerFailure) -> None:\n        self._health.failed(code)\n        if isinstance(code, WorkerFailure) and code.immediate_degraded:\n            self._handle.serving_event.set()\n        self._on_health_change()\n''',
)

# While durable failed jobs are waiting for next_attempt_at, polling is progress but
# not success. Refresh the lease without clearing the truthful degraded state.
replace_once(
    "worktrace/services/activity_inference_job_service.py",
    '''            if failed_backlog:\n                if not backlog_degraded:\n                    health.failed(degraded_failure("inference_job_failures"))\n                    backlog_degraded = True\n            else:\n''',
    '''            if failed_backlog:\n                if not backlog_degraded:\n                    health.failed(degraded_failure("inference_job_failures"))\n                    backlog_degraded = True\n                else:\n                    health.progressed()\n            else:\n''',
)

# Contract: progress advances the liveness lease and served state without hiding the
# partial failure that made the worker degraded.
path = ROOT / "tests/test_worker_retry_health_contract.py"
source = path.read_text(encoding="utf-8")
marker = '''def test_inference_batch_stops_after_first_database_busy(monkeypatch) -> None:\n'''
if source.count(marker) != 1:
    raise RuntimeError("worker retry contract insertion marker changed")
new_test = '''def test_progress_refreshes_lease_without_clearing_degraded_failure() -> None:\n    now = {"value": 10.0}\n    registry = WorkerHealthRegistry(monotonic_func=lambda: now["value"])\n    reporter = registry.reporter("inference")\n    reporter.started()\n    reporter.failed(degraded_failure("inference_job_failures"))\n\n    before = registry.snapshots()["inference"]\n    now["value"] = 25.0\n    reporter.progressed()\n    after = registry.snapshots()["inference"]\n\n    assert before.last_failure_code == "inference_job_failures"\n    assert after.last_failure_code == "inference_job_failures"\n    assert after.explicit_degraded is True\n    assert after.served is True\n    assert after.last_progress_monotonic == 25.0\n    assert registry.degraded_workers() == ("inference",)\n\n\n'''
path.write_text(source.replace(marker, new_test + marker, 1), encoding="utf-8")
