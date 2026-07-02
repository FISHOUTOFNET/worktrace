"""privacy gate tests for the unified startup entry.

These tests verify the folder index worker is NOT started during
``AppRuntime.initialize()`` and is only started via the unified
``app_api.start_collection_after_privacy_gate()`` entry, which enforces
the first-run privacy notice in exactly one place. The worker probes
local ``os.path.exists(file_path)`` paths for ready indexes, which is
privacy-relevant local path probing; it must not start before the user
has accepted the first-run privacy notice. The bridge /
``webview_main`` MUST NOT duplicate the gate read or the start ordering:
they route through the unified entry so the gate is enforced once.
"""

from __future__ import annotations

from unittest.mock import patch

from worktrace.runtime.app_runtime import AppRuntime
from worktrace.services import folder_index_service


def _make_paths(temp_db, tmp_path):
    """Build a minimal paths object with ``db_path`` and ``log_path``."""
    return type(
        "P",
        (),
        {
            "db_path": str(temp_db),
            "log_path": str(tmp_path / "test.log"),
        },
    )()


def _fake_thread():
    """Return a fake thread object with a ``join`` method (for shutdown)."""
    return type("T", (), {"join": lambda self, timeout=None: None})()


def test_initialize_does_not_start_folder_index_worker(temp_db, tmp_path, monkeypatch):
    """``AppRuntime.initialize()`` must NOT call
    ``folder_index_service.start_folder_index_worker``.

    Privacy gate: ``initialize`` only does DB init, single-instance
    lock, and recovery. The folder index worker is started separately via
    ``start_background_workers()`` only after the first-run privacy notice
    has been accepted.
    """
    # Mock single-instance so initialize() does not touch the OS mutex.
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance", lambda: True
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance", lambda: None
    )

    paths = _make_paths(temp_db, tmp_path)
    runtime = AppRuntime(paths)
    try:
        with patch(
            "worktrace.services.folder_index_service.start_folder_index_worker"
        ) as mock_start:
            runtime.initialize()
            mock_start.assert_not_called()
    finally:
        runtime.shutdown()


def test_start_background_workers_returns_true_on_first_call(
    temp_db, tmp_path, monkeypatch
):
    """``start_background_workers()`` returns ``True`` on first call when
    ``owns_collector`` is True and the worker starts, and actually starts
    the worker."""
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance", lambda: True
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance", lambda: None
    )

    start_calls = {"count": 0}

    def _fake_start(stop_event):
        start_calls["count"] += 1
        return _fake_thread()

    monkeypatch.setattr(
        folder_index_service, "start_folder_index_worker", _fake_start
    )

    paths = _make_paths(temp_db, tmp_path)
    runtime = AppRuntime(paths)
    try:
        runtime.initialize()
        result = runtime.start_background_workers()
        assert result is True
        assert start_calls["count"] == 1
    finally:
        runtime.shutdown()


def test_start_background_workers_is_idempotent(temp_db, tmp_path, monkeypatch):
    """``start_background_workers()`` is idempotent: second call returns
    ``False`` and the worker is not started twice."""
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance", lambda: True
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance", lambda: None
    )

    start_calls = {"count": 0}

    def _fake_start(stop_event):
        start_calls["count"] += 1
        return _fake_thread()

    monkeypatch.setattr(
        folder_index_service, "start_folder_index_worker", _fake_start
    )

    paths = _make_paths(temp_db, tmp_path)
    runtime = AppRuntime(paths)
    try:
        runtime.initialize()
        first = runtime.start_background_workers()
        second = runtime.start_background_workers()
        assert first is True
        assert second is False
        assert start_calls["count"] == 1
    finally:
        runtime.shutdown()


def test_start_background_workers_returns_false_when_not_owns_collector(
    temp_db, tmp_path, monkeypatch
):
    """``start_background_workers()`` returns ``False`` when
    ``not owns_collector`` (no-op). The worker is not started."""
    # Mock acquire_single_instance to return False so owns_collector is False
    # after initialize().
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance", lambda: False
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance", lambda: None
    )

    start_calls = {"count": 0}

    def _fake_start(stop_event):
        start_calls["count"] += 1
        return _fake_thread()

    monkeypatch.setattr(
        folder_index_service, "start_folder_index_worker", _fake_start
    )

    paths = _make_paths(temp_db, tmp_path)
    runtime = AppRuntime(paths)
    try:
        runtime.initialize()
        assert runtime.owns_collector is False
        result = runtime.start_background_workers()
        assert result is False
        assert start_calls["count"] == 0
    finally:
        runtime.shutdown()


def test_start_background_workers_returns_false_when_worker_start_returns_none(
    temp_db, tmp_path, monkeypatch
):
    """``start_background_workers()`` returns ``False`` when
    ``start_folder_index_worker`` returns ``None`` (worker failed to start)."""
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.acquire_single_instance", lambda: True
    )
    monkeypatch.setattr(
        "worktrace.runtime.app_runtime.release_single_instance", lambda: None
    )

    monkeypatch.setattr(
        folder_index_service, "start_folder_index_worker", lambda stop_event: None
    )

    paths = _make_paths(temp_db, tmp_path)
    runtime = AppRuntime(paths)
    try:
        runtime.initialize()
        result = runtime.start_background_workers()
        assert result is False
    finally:
        runtime.shutdown()


def test_app_api_start_background_workers_returns_false_when_no_runtime(monkeypatch):
    """``app_api.start_background_workers()`` facade returns ``False`` when
    no runtime is registered (before ``set_runtime``)."""
    from worktrace.api import app_api

    monkeypatch.setattr("worktrace.api.app_api._runtime", None)
    assert app_api.start_background_workers() is False


def test_app_api_exports_start_background_workers():
    """``app_api.__all__`` must export ``start_background_workers``."""
    from worktrace.api import app_api

    assert "start_background_workers" in app_api.__all__


# Unified privacy-gate entry tests


def _make_recording_runtime():
    """Build a fake runtime whose ``start_*`` methods append to
    ``calls`` so the fail-closed tests can verify the gate prevents the
    runtime-level calls (not just the module-level facades)."""
    calls: list[str] = []

    def _bg(self):
        calls.append("background_workers")

    def _collector(self):
        calls.append("collector")

    runtime = type("R", (), {
        "start_background_workers": _bg,
        "start_collector": _collector,
    })()
    return runtime, calls


def test_start_collection_after_privacy_gate_fails_closed_when_notice_not_accepted(monkeypatch):
    """When the first-run notice has NOT been accepted, the unified gate
    must return ``ok=False`` and must NOT call ``runtime.start_background_workers``
    or ``runtime.start_collector`` (verified on a real fake runtime so the
    gate, not a None runtime, is what prevents the calls)."""
    from worktrace.api import app_api

    fake_runtime, calls = _make_recording_runtime()
    monkeypatch.setattr("worktrace.api.app_api._runtime", fake_runtime)
    monkeypatch.setattr(
        "worktrace.api.settings_api.first_run_notice_accepted", lambda: False
    )

    result = app_api.start_collection_after_privacy_gate()

    assert result["ok"] is False
    assert result["error"] == "请先确认隐私说明"
    assert calls == []


def test_start_collection_after_privacy_gate_fails_closed_when_notice_read_raises(monkeypatch):
    """When ``first_run_notice_accepted`` raises, the unified gate must
    fail closed and must NOT call ``runtime.start_background_workers`` or
    ``runtime.start_collector``."""
    from worktrace.api import app_api

    fake_runtime, calls = _make_recording_runtime()
    monkeypatch.setattr("worktrace.api.app_api._runtime", fake_runtime)

    def _raise() -> bool:
        raise RuntimeError("settings read failed")

    monkeypatch.setattr("worktrace.api.settings_api.first_run_notice_accepted", _raise)

    result = app_api.start_collection_after_privacy_gate()

    assert result["ok"] is False
    assert result["error"] == "请先确认隐私说明"
    assert calls == []


def test_start_collection_after_privacy_gate_starts_workers_before_collector(monkeypatch):
    """When the notice IS accepted, the unified gate must call
    ``start_background_workers`` BEFORE ``start_collector`` so the folder
    index is warm before the collector starts matching activities."""
    from worktrace.api import app_api

    fake_runtime = type(
        "R",
        (),
        {
            "start_background_workers": lambda self: order.append("background_workers"),
            "start_collector": lambda self: order.append("collector"),
        },
    )()
    monkeypatch.setattr("worktrace.api.app_api._runtime", fake_runtime)
    monkeypatch.setattr(
        "worktrace.api.settings_api.first_run_notice_accepted", lambda: True
    )

    order: list[str] = []
    result = app_api.start_collection_after_privacy_gate()

    assert result["ok"] is True
    assert order == ["background_workers", "collector"]


def test_start_collection_after_privacy_gate_returns_ok_on_success(monkeypatch):
    """When the notice IS accepted and start succeeds, the gate returns
    ``{"ok": True}``."""
    from worktrace.api import app_api

    fake_runtime = type(
        "R",
        (),
        {
            "start_background_workers": lambda self: True,
            "start_collector": lambda self: None,
        },
    )()
    monkeypatch.setattr("worktrace.api.app_api._runtime", fake_runtime)
    monkeypatch.setattr(
        "worktrace.api.settings_api.first_run_notice_accepted", lambda: True
    )

    result = app_api.start_collection_after_privacy_gate()

    assert result["ok"] is True


def test_start_collection_after_privacy_gate_swallows_start_failures(monkeypatch):
    """When start_background_workers or start_collector raises, the gate
    must log and continue (returns ``ok=True``) so the WebView can still
    start; the user can retry via the sidebar toggle."""
    from worktrace.api import app_api

    fake_runtime = type(
        "R",
        (),
        {
            "start_background_workers": lambda self: (_ for _ in ()).throw(RuntimeError("bg failed")),
            "start_collector": lambda self: (_ for _ in ()).throw(RuntimeError("collector failed")),
        },
    )()
    monkeypatch.setattr("worktrace.api.app_api._runtime", fake_runtime)
    monkeypatch.setattr(
        "worktrace.api.settings_api.first_run_notice_accepted", lambda: True
    )

    result = app_api.start_collection_after_privacy_gate()

    assert result["ok"] is True
