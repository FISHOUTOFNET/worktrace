from __future__ import annotations

from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8", newline="\n")


def replace_once(path: str, old: str, new: str) -> None:
    content = read(path)
    count = content.count(old)
    if count != 1:
        raise AssertionError(f"{path}: expected one replacement, found {count}: {old[:120]!r}")
    write(path, content.replace(old, new, 1))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    content = read(path)
    start_index = content.find(start)
    if start_index < 0:
        raise AssertionError(f"{path}: start marker missing: {start!r}")
    end_index = content.find(end, start_index)
    if end_index < 0:
        raise AssertionError(f"{path}: end marker missing: {end!r}")
    end_index += len(end)
    write(path, content[:start_index] + replacement + content[end_index:])


def migrate_collector_control() -> None:
    path = "worktrace/collector/collector.py"
    replace_once(path, "import logging\n", "import logging\nfrom dataclasses import dataclass, field\nfrom enum import Enum\n")
    replace_once(path, "import time\n", "import time\nimport uuid\n")
    control = textwrap.dedent(
        '''\
        class CollectorCommandState(str, Enum):
            PENDING = "pending"
            TAKEN = "taken"
            COMPLETED = "completed"
            CANCELLED = "cancelled"
            UNKNOWN = "unknown"


        @dataclass
        class _CollectorCommand:
            command_id: str
            kind: str
            state: CollectorCommandState = CollectorCommandState.PENDING
            done_event: threading.Event = field(default_factory=threading.Event)
            result: dict[str, Any] = field(default_factory=dict)


        class CollectorControl:
            """Cancellable command channel with identity and an explicit terminal state."""

            def __init__(self) -> None:
                self._lock = threading.Lock()
                self._wake_event = threading.Event()
                self._commands: dict[str, _CollectorCommand] = {}
                self._pending_ids: dict[str, str] = {}

            def request_pause(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
                return self._request("pause", timeout_seconds)

            def take_pause_request(self) -> str | None:
                return self._take("pause")

            def complete_pause(self, command_id: str, result: dict[str, Any]) -> bool:
                return self._complete(command_id, "pause", result)

            def request_reset(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
                return self._request("reset", timeout_seconds)

            def take_reset_request(self) -> str | None:
                return self._take("reset")

            def complete_reset(self, command_id: str, result: dict[str, Any]) -> bool:
                return self._complete(command_id, "reset", result)

            def _request(self, kind: str, timeout_seconds: float) -> dict[str, Any]:
                command = _CollectorCommand(
                    command_id=uuid.uuid4().hex,
                    kind=kind,
                    result={"ok": False, f"{kind}_pending": True},
                )
                with self._lock:
                    previous_id = self._pending_ids.get(kind)
                    if previous_id:
                        previous = self._commands.get(previous_id)
                        if previous is not None and previous.state is CollectorCommandState.PENDING:
                            return {
                                "ok": False,
                                f"{kind}_pending": True,
                                "error": "command_already_pending",
                                "command_id": previous.command_id,
                                "command_state": previous.state.value,
                                "command_state_unknown": False,
                            }
                    self._commands[command.command_id] = command
                    self._pending_ids[kind] = command.command_id
                    self._wake_event.set()

                if command.done_event.wait(max(0.0, float(timeout_seconds))):
                    with self._lock:
                        return dict(command.result)

                with self._lock:
                    if command.state is CollectorCommandState.COMPLETED:
                        return dict(command.result)
                    if command.state is CollectorCommandState.PENDING:
                        command.state = CollectorCommandState.CANCELLED
                        self._pending_ids.pop(kind, None)
                        self._refresh_wake_event_locked()
                        return {
                            "ok": False,
                            f"{kind}_pending": False,
                            "timed_out": True,
                            "command_id": command.command_id,
                            "command_state": command.state.value,
                            "command_state_unknown": False,
                        }
                    if command.state is CollectorCommandState.TAKEN:
                        command.state = CollectorCommandState.UNKNOWN
                    return {
                        "ok": False,
                        f"{kind}_pending": False,
                        "timed_out": True,
                        "command_id": command.command_id,
                        "command_state": command.state.value,
                        "command_state_unknown": command.state is CollectorCommandState.UNKNOWN,
                    }

            def _take(self, kind: str) -> str | None:
                with self._lock:
                    command_id = self._pending_ids.get(kind)
                    command = self._commands.get(command_id or "")
                    if command is None or command.state is not CollectorCommandState.PENDING:
                        self._pending_ids.pop(kind, None)
                        self._refresh_wake_event_locked()
                        return None
                    command.state = CollectorCommandState.TAKEN
                    self._pending_ids.pop(kind, None)
                    self._refresh_wake_event_locked()
                    return command.command_id

            def _complete(
                self,
                command_id: str,
                kind: str,
                result: dict[str, Any],
            ) -> bool:
                with self._lock:
                    command = self._commands.get(str(command_id or ""))
                    if command is None or command.kind != kind:
                        return False
                    if command.state not in {
                        CollectorCommandState.TAKEN,
                        CollectorCommandState.UNKNOWN,
                    }:
                        return False
                    command.state = CollectorCommandState.COMPLETED
                    command.result = {
                        **dict(result),
                        "command_id": command.command_id,
                        "command_state": command.state.value,
                        "command_state_unknown": False,
                    }
                    command.done_event.set()
                    return True

            def _refresh_wake_event_locked(self) -> None:
                if self._pending_ids:
                    self._wake_event.set()
                else:
                    self._wake_event.clear()

            def wait(self, stop_event: threading.Event, timeout_seconds: float) -> None:
                deadline = time.monotonic() + max(0.0, timeout_seconds)
                while not stop_event.is_set():
                    if self._wake_event.wait(timeout=0.1):
                        return
                    if time.monotonic() >= deadline:
                        return


        '''
    )
    replace_between(path, "class CollectorControl:", "def run_collector(", control + "def run_collector(")

    replace_once(
        path,
        '''            if control is not None and control.take_reset_request():
                _set_clipboard_capture_enabled(adapter, False)
                machine.reset_runtime_state("database_generation_changed")
                control.complete_reset({"ok": True, "reset_pending": False})
''',
        '''            reset_command_id = control.take_reset_request() if control is not None else None
            if reset_command_id is not None:
                _set_clipboard_capture_enabled(adapter, False)
                machine.reset_runtime_state("database_generation_changed")
                control.complete_reset(
                    reset_command_id,
                    {"ok": True, "reset_pending": False},
                )
''',
    )
    replace_once(
        path,
        '''            if control is not None and control.take_pause_request():
                _set_clipboard_capture_enabled(adapter, False)
                _pause_machine_then_expose(
                    machine,
                    now,
                    set_user_paused=True,
                )
                control.complete_pause({"ok": True, "pause_pending": False})
''',
        '''            pause_command_id = control.take_pause_request() if control is not None else None
            if pause_command_id is not None:
                _set_clipboard_capture_enabled(adapter, False)
                _pause_machine_then_expose(
                    machine,
                    now,
                    set_user_paused=True,
                )
                control.complete_pause(
                    pause_command_id,
                    {"ok": True, "pause_pending": False},
                )
''',
    )


def migrate_app_runtime() -> None:
    path = "worktrace/runtime/app_runtime.py"
    replace_once(path, '    DEGRADED = "degraded"\n', '    DEGRADED = "degraded"\n    RECOVERABLE_FAILURE = "recoverable_failure"\n')
    replace_once(
        path,
        "from ..services.settings_service import get_bool_setting, get_setting, set_setting\n",
        "from ..services.runtime_activity_state_service import clear_runtime_activity_state\nfrom ..services.settings_service import get_bool_setting, get_setting, set_setting\n",
    )
    replace_once(
        path,
        "        self._collector_thread: threading.Thread | None = None\n",
        "        self._collector_thread: threading.Thread | None = None\n        self._collector_stop_event: threading.Event | None = None\n        self._collector_generation = 0\n",
    )
    replace_once(
        path,
        '''        if not bool(collector_result.get("ok")):
            self.phase = RuntimePhase.FAILED
''',
        '''        if not bool(collector_result.get("ok")):
            error_code = str(collector_result.get("error") or "collector_start_failed")
            self.phase = (
                RuntimePhase.FAILED
                if error_code in {"collector_stop_timeout", "runtime_stopping"}
                else RuntimePhase.RECOVERABLE_FAILURE
            )
''',
    )
    replace_once(
        path,
        '''                error_code=str(
                    collector_result.get("error") or "collector_start_failed"
                ),
''',
        '''                error_code=error_code,
''',
    )

    start_collector = textwrap.dedent(
        '''\
            def start_collector(
                self,
                *,
                startup_timeout_seconds: float = 5.0,
            ) -> dict[str, object]:
                with self._lifecycle_lock:
                    if self._shutdown or self.stop_event.is_set():
                        return {"ok": False, "error": "runtime_stopping"}
                    if not self.owns_application_instance:
                        return {"ok": False, "error": "collector_not_owned"}
                    if _thread_reference_is_alive(self._collector_thread):
                        if self._collector_stop_event is not None and self._collector_stop_event.is_set():
                            return {"ok": False, "error": "collector_stopping"}
                        self._register_collector_write_thread()
                        self._register_maintenance_handlers()
                        return {"ok": True, "started": False, "already_running": True}
                    if self._collector_thread is not None:
                        collector_health.record_health_code("thread_dead_replaced")
                        self._clear_collector_write_thread()
                        self._collector_thread = None
                        self._collector_stop_event = None

                    ready_event = threading.Event()
                    failed_event = threading.Event()
                    attempt_stop_event = threading.Event()
                    attempt_control = CollectorControl()
                    self._collector_generation += 1
                    attempt_generation = self._collector_generation
                    self._collector_stop_event = attempt_stop_event
                    self.collector_control = attempt_control
                    try:
                        thread = threading.Thread(
                            target=run_collector,
                            args=(
                                self._adapter,
                                attempt_stop_event,
                                attempt_control,
                                ready_event,
                                failed_event,
                            ),
                            name="WorkTraceCollector",
                            daemon=True,
                        )
                        self._collector_thread = thread
                        thread.start()
                    except Exception:
                        logging.exception("collector thread start failed")
                        self._clear_collector_write_thread()
                        self._collector_thread = None
                        self._collector_stop_event = None
                        self.collector_control = CollectorControl()
                        self.phase = RuntimePhase.RECOVERABLE_FAILURE
                        return {"ok": False, "error": "collector_start_failed"}

                deadline = time.monotonic() + max(0.1, float(startup_timeout_seconds))
                startup_ready = False
                while time.monotonic() < deadline:
                    if ready_event.wait(timeout=0.05):
                        startup_ready = True
                        break
                    if failed_event.is_set() or not _thread_reference_is_alive(thread):
                        break

                if startup_ready:
                    with self._lifecycle_lock:
                        if (
                            attempt_generation != self._collector_generation
                            or self._collector_thread is not thread
                        ):
                            attempt_stop_event.set()
                            return {"ok": False, "error": "collector_attempt_superseded"}
                        self._register_collector_write_thread()
                        self._register_maintenance_handlers()
                        return {"ok": True, "started": True, "already_running": False}

                collector_health.record_health_code("collector_startup_not_ready")
                attempt_stop_event.set()
                joiner = getattr(thread, "join", None)
                if joiner is not None:
                    joiner(timeout=2)
                still_alive = _thread_reference_is_alive(thread)
                with self._lifecycle_lock:
                    if attempt_generation == self._collector_generation:
                        self._clear_collector_write_thread()
                        if still_alive:
                            self.phase = RuntimePhase.FAILED
                            return {"ok": False, "error": "collector_stop_timeout"}
                        self._collector_thread = None
                        self._collector_stop_event = None
                        self.collector_control = CollectorControl()
                        self.phase = RuntimePhase.RECOVERABLE_FAILURE
                return {"ok": False, "error": "collector_start_failed"}

        '''
    )
    replace_between(
        path,
        "    def start_collector(\n",
        "    def _register_maintenance_handlers(self) -> None:",
        start_collector + "    def _register_maintenance_handlers(self) -> None:",
    )

    replace_once(
        path,
        '''        result = self.pause_collection_now(timeout_seconds=timeout_seconds)
        if bool(result.get("ok")):
            set_setting(
                "user_paused",
                "true" if prior_user_paused else "false",
            )
            set_setting("collector_status", prior_collector_status)
        return result
''',
        '''        result = self.pause_collection_now(timeout_seconds=timeout_seconds)
        if bool(result.get("ok")):
            set_setting(
                "user_paused",
                "true" if prior_user_paused else "false",
            )
            set_setting("collector_status", prior_collector_status)
        elif bool(result.get("command_state_unknown")):
            set_setting("user_paused", "true")
            set_setting("collector_status", "paused")
            clear_runtime_activity_state("collector_pause_state_unknown")
        return result
''',
    )
    replace_once(
        path,
        '''        if bool(result.get("ok")):
            self._reset_adapter_runtime_state()
        return result
''',
        '''        if bool(result.get("ok")):
            self._reset_adapter_runtime_state()
        elif bool(result.get("command_state_unknown")):
            set_setting("user_paused", "true")
            set_setting("collector_status", "paused")
            clear_runtime_activity_state("collector_reset_state_unknown")
        return result
''',
    )
    replace_once(
        path,
        '''    def request_shutdown(self) -> None:
        self.phase = RuntimePhase.STOPPING
        self.stop_event.set()
''',
        '''    def request_shutdown(self) -> None:
        self.phase = RuntimePhase.STOPPING
        self.stop_event.set()
        collector_stop_event = self._collector_stop_event
        if collector_stop_event is not None:
            collector_stop_event.set()
''',
    )
    replace_once(
        path,
        '''            self.set_clipboard_capture_enabled(False)
            self.stop_event.set()
            workers = [
''',
        '''            self.set_clipboard_capture_enabled(False)
            self.stop_event.set()
            if self._collector_stop_event is not None:
                self._collector_stop_event.set()
            workers = [
''',
    )


def migrate_secure_import_fail_closed() -> None:
    path = "worktrace/services/secure_backup_service.py"
    replace_once(
        path,
        "    succeeded: bool = False\n",
        "    succeeded: bool = False\n    fail_closed: bool = False\n",
    )
    helper = textwrap.dedent(
        '''\
            def _require_command_ack(
                self,
                result: dict[str, Any],
                *,
                kind: str,
                state: _ImportGuardState,
                reason: str,
            ) -> None:
                if bool(result.get("ok")):
                    return
                if bool(result.get("command_state_unknown")):
                    state.fail_closed = True
                    set_setting("user_paused", "true")
                    set_setting("collector_status", "paused")
                    clear_runtime_activity_state(f"{reason}_{kind}_state_unknown")
                raise SecureBackupError(f"collector_{kind}_not_acknowledged")

        '''
    )
    replace_once(
        path,
        "    @contextmanager\n    def acquire(\n",
        helper + "    @contextmanager\n    def acquire(\n",
    )
    replace_once(
        path,
        '''                    if pause_handler is not None:
                        result = pause_handler(timeout_seconds=5.0)
                        if not bool(result.get("ok")):
                            raise SecureBackupError(
                                "collector_pause_not_acknowledged"
                            )
                    if reset_handler is not None:
                        result = reset_handler(timeout_seconds=5.0)
                        if not bool(result.get("ok")):
                            raise SecureBackupError(
                                "collector_reset_not_acknowledged"
                            )
''',
        '''                    if pause_handler is not None:
                        result = pause_handler(timeout_seconds=5.0)
                        self._require_command_ack(
                            result,
                            kind="pause",
                            state=state,
                            reason=reason,
                        )
                    if reset_handler is not None:
                        result = reset_handler(timeout_seconds=5.0)
                        self._require_command_ack(
                            result,
                            kind="reset",
                            state=state,
                            reason=reason,
                        )
''',
    )
    replace_once(
        path,
        "                    if not state.succeeded:\n",
        "                    if not state.succeeded and not state.fail_closed:\n",
    )


def migrate_tests() -> None:
    path = "tests/test_collector_runtime_restart_contract.py"
    replace_once(
        path,
        '''    finally:
        runtime.stop_event.set()
        runtime._collector_thread.join(timeout=2)
''',
        '''    finally:
        runtime.request_shutdown()
        runtime._collector_thread.join(timeout=2)
''',
    )
    append = textwrap.dedent(
        '''\

        def test_collector_start_failure_is_retryable_without_stopping_runtime(
            temp_db,
            monkeypatch,
        ):
            runtime = AppRuntime(SimpleNamespace(db_path="", log_path=""), adapter=object())
            runtime.owns_application_instance = True
            attempts = {"count": 0}

            def fake_run_collector(
                _adapter,
                stop_event,
                _control,
                startup_ready_event,
                startup_failed_event,
            ):
                attempts["count"] += 1
                if attempts["count"] == 1:
                    startup_failed_event.set()
                    return
                startup_ready_event.set()
                stop_event.wait(2)

            monkeypatch.setattr(app_runtime, "run_collector", fake_run_collector)

            first = runtime.start_collector(startup_timeout_seconds=0.2)
            assert first == {"ok": False, "error": "collector_start_failed"}
            assert runtime.stop_event.is_set() is False
            assert runtime.phase is app_runtime.RuntimePhase.RECOVERABLE_FAILURE

            second = runtime.start_collector(startup_timeout_seconds=0.5)
            try:
                assert second == {
                    "ok": True,
                    "started": True,
                    "already_running": False,
                }
                assert attempts["count"] == 2
            finally:
                runtime.request_shutdown()
                assert runtime._collector_thread is not None
                runtime._collector_thread.join(timeout=2)
        '''
    )
    write(path, read(path) + append)

    path = "tests/test_runtime_maintenance_control.py"
    replace_between(
        path,
        "def test_pause_timeout_reports_unknown_command_state():",
        "def test_long_poll_gap_rebases_instead_of_replaying_ticks():",
        textwrap.dedent(
            '''\
            def test_unclaimed_pause_timeout_is_cancelled():
                control = CollectorControl()

                result = control.request_pause(timeout_seconds=0)

                assert result["ok"] is False
                assert result["pause_pending"] is False
                assert result["timed_out"] is True
                assert result["command_state"] == "cancelled"
                assert result["command_state_unknown"] is False
                assert control.take_pause_request() is None


            def test_taken_pause_timeout_reports_unknown_and_late_completion_is_identified():
                control = CollectorControl()
                result_box: dict[str, dict] = {}
                request = threading.Thread(
                    target=lambda: result_box.setdefault(
                        "result",
                        control.request_pause(timeout_seconds=0.05),
                    ),
                    daemon=True,
                )
                request.start()
                assert control._wake_event.wait(timeout=1)
                command_id = control.take_pause_request()
                assert command_id is not None
                request.join(timeout=1)

                result = result_box["result"]
                assert result["command_id"] == command_id
                assert result["command_state"] == "unknown"
                assert result["command_state_unknown"] is True
                assert control.complete_pause(
                    command_id,
                    {"ok": True, "pause_pending": False},
                ) is True


            def test_reset_command_is_acknowledged_once():
                control = CollectorControl()
                result_box: dict[str, dict] = {}
                thread = threading.Thread(
                    target=lambda: result_box.setdefault(
                        "result",
                        control.request_reset(timeout_seconds=2),
                    ),
                    daemon=True,
                )

                thread.start()
                assert control._wake_event.wait(timeout=1)
                command_id = control.take_reset_request()
                assert command_id is not None
                assert control.complete_reset(
                    command_id,
                    {"ok": True, "reset_pending": False},
                ) is True
                thread.join(timeout=2)

                assert result_box["result"]["ok"] is True
                assert result_box["result"]["command_id"] == command_id
                assert result_box["result"]["command_state"] == "completed"
                assert control.take_reset_request() is None


            def test_long_poll_gap_rebases_instead_of_replaying_ticks():
            '''
        ),
    )
    append = textwrap.dedent(
        '''\

        def test_maintenance_unknown_command_state_remains_fail_closed(temp_db):
            coordinator = SecureImportCoordinator()
            settings_service.set_setting("user_paused", "false")
            settings_service.set_setting("collector_status", "running")
            coordinator.register_collector_pause_handler(
                lambda timeout_seconds=5.0: {
                    "ok": False,
                    "pause_pending": False,
                    "command_state_unknown": True,
                    "command_state": "unknown",
                }
            )

            with pytest.raises(SecureBackupError, match="pause_not_acknowledged"):
                with coordinator.acquire(reason="unknown"):
                    pytest.fail("operation must not start")

            assert coordinator.write_gate_active() is False
            assert settings_service.get_bool_setting("user_paused", False) is True
            assert settings_service.get_setting("collector_status", "") == "paused"
        '''
    )
    write(path, read(path) + append)


def verify() -> None:
    collector = read("worktrace/collector/collector.py")
    if "_pause_requested" in collector or "_reset_requested" in collector:
        raise AssertionError("legacy boolean command channel remains")
    runtime = read("worktrace/runtime/app_runtime.py")
    if "self.stop_event.set()\n        thread = self._collector_thread" in runtime:
        raise AssertionError("collector startup still stops the application runtime")


def main() -> None:
    migrate_collector_control()
    migrate_app_runtime()
    migrate_secure_import_fail_closed()
    migrate_tests()
    verify()


if __name__ == "__main__":
    main()
