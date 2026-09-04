from __future__ import annotations

import pytest

from worktrace.platforms import windows_path_resolver
from worktrace.platforms.capability_health import PathCapabilityHealth
from worktrace.platforms.windows_adapter import WindowsAdapter
from worktrace.platforms.windows_path_resolver import (
    PathResolutionResult,
    WindowsPathResolver,
)

pytestmark = [pytest.mark.unit, pytest.mark.parallel_safe]


def test_path_capability_requires_fresh_success_after_runtime_reset():
    health = PathCapabilityHealth()

    health.mark_recovering()
    assert health.snapshot().state == "recovering"

    health.observe_probe(
        route="com",
        outcome="timeout",
        attempted=True,
        path_found=False,
    )
    degraded = health.snapshot()
    assert degraded.state == "degraded"
    assert degraded.last_failure_code == "com_timeout"
    assert degraded.consecutive_failures == 1

    health.observe_probe(
        route="open_files",
        outcome="success",
        attempted=True,
        path_found=True,
    )
    recovered = health.snapshot()
    assert recovered.state == "healthy"
    assert recovered.last_failure_code == ""
    assert recovered.consecutive_failures == 0


def test_path_resolver_reset_invalidates_failure_cooldowns(monkeypatch):
    resolver = WindowsPathResolver()
    monkeypatch.setattr(
        windows_path_resolver,
        "_is_registered_prog_id",
        lambda prog_id: prog_id == "Word.Application",
    )
    monkeypatch.setattr(
        windows_path_resolver,
        "_get_com_file_path_subprocess",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("helper failed")),
    )
    monkeypatch.setattr(
        windows_path_resolver,
        "_get_process_open_file_paths",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("helper failed")),
    )

    first = resolver._resolve_active_file_path_with_diagnostics(
        "winword.exe",
        "Report.docx - Word",
        pid=1234,
    )
    assert first.attempted is True
    assert first.outcome == "helper_error"
    assert resolver._com_failure_times
    assert resolver._open_files_failure_times

    cooled = resolver._resolve_active_file_path_with_diagnostics(
        "winword.exe",
        "Report.docx - Word",
        pid=1234,
    )
    assert cooled.attempted is False
    assert cooled.outcome == "cooldown"

    resolver.reset()
    assert resolver._com_failure_times == {}
    assert resolver._open_files_failure_times == {}

    retried = resolver._resolve_active_file_path_with_diagnostics(
        "winword.exe",
        "Report.docx - Word",
        pid=1234,
    )
    assert retried.attempted is True
    assert retried.outcome == "helper_error"


def test_windows_adapter_reset_marks_path_recovering_until_authoritative_success():
    class Resolver:
        def reset(self):
            pass

        def privacy_path_required(self, *_args):
            return True

        def resolve(self, *_args):
            return None

    adapter = WindowsAdapter(path_resolver=Resolver())

    adapter.reset_runtime_state()
    snapshot = adapter.capability_health_snapshot()["path_resolution"]
    assert snapshot["state"] == "recovering"

    adapter._observe_path_probe(
        PathResolutionResult(
            r"D:\Client\Report.docx",
            route="com",
            outcome="success",
            attempted=True,
        )
    )
    snapshot = adapter.capability_health_snapshot()["path_resolution"]
    assert snapshot["state"] == "healthy"

    adapter.reset_runtime_state()
    adapter._observe_path_probe(
        PathResolutionResult(
            None,
            route="open_files",
            outcome="timeout",
            attempted=True,
        )
    )
    snapshot = adapter.capability_health_snapshot()["path_resolution"]
    assert snapshot["state"] == "degraded"
    assert snapshot["last_failure_code"] == "open_files_timeout"



def test_successful_no_match_resets_technical_failure_streak():
    health = PathCapabilityHealth(failure_threshold=3)
    health.observe_probe(route="com", outcome="timeout", attempted=True, path_found=False)
    health.observe_probe(route="open_files", outcome="helper_error", attempted=True, path_found=False)
    assert health.snapshot().consecutive_failures == 2

    health.observe_probe(route="open_files", outcome="no_match", attempted=True, path_found=False)

    snapshot = health.snapshot()
    assert snapshot.state == "healthy"
    assert snapshot.consecutive_failures == 0
    assert snapshot.last_failure_code == ""


def test_path_failure_backoff_is_short_first_and_bounded(monkeypatch):
    now = {"value": 100.0}
    monkeypatch.setattr(windows_path_resolver.time, "monotonic", lambda: now["value"])
    failures = {}

    WindowsPathResolver._mark_failed(failures, "target")
    assert WindowsPathResolver._available(failures, "target") is False
    now["value"] += 2.1
    assert WindowsPathResolver._available(failures, "target") is True

    WindowsPathResolver._mark_failed(failures, "target")
    now["value"] += 4.9
    assert WindowsPathResolver._available(failures, "target") is False
    now["value"] += 0.2
    assert WindowsPathResolver._available(failures, "target") is True

    WindowsPathResolver._mark_succeeded(failures, "target")
    assert failures == {}
