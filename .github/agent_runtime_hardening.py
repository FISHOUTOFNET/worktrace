from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str, *, marker: str | None = None) -> None:
    text = read(path)
    if marker and marker in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one literal replacement, found {count}")
    write(path, text.replace(old, new, 1))


def replace_regex(path: str, pattern: str, replacement: str, *, marker: str | None = None, flags: int = 0) -> None:
    text = read(path)
    if marker and marker in text:
        return
    updated, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex replacement, found {count}: {pattern[:80]}")
    write(path, updated)


# ---------------------------------------------------------------------------
# Collector command lifecycle, paused maintenance, retention and cadence.
# ---------------------------------------------------------------------------
replace_regex(
    "worktrace/collector/collector.py",
    r"class CollectorControl:\n.*?\n\ndef run_collector\(",
    '''class CollectorControl:
    """Small cancellable command channel owned by the runtime."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake_event = threading.Event()
        self._pause_requested = False
        self._pause_done = threading.Event()
        self._pause_result: dict[str, Any] = {"ok": False, "pause_pending": False}
        self._reset_requested = False
        self._reset_done = threading.Event()
        self._reset_result: dict[str, Any] = {"ok": False, "reset_pending": False}

    def request_pause(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
        with self._lock:
            self._pause_requested = True
            self._pause_done.clear()
            self._pause_result = {"ok": False, "pause_pending": True}
            self._wake_event.set()
        if not self._pause_done.wait(timeout_seconds):
            with self._lock:
                self._pause_requested = False
                self._refresh_wake_event_locked()
            return {"ok": False, "pause_pending": False, "timed_out": True}
        with self._lock:
            return dict(self._pause_result)

    def take_pause_request(self) -> bool:
        with self._lock:
            if not self._pause_requested:
                return False
            self._pause_requested = False
            self._refresh_wake_event_locked()
            return True

    def complete_pause(self, result: dict[str, Any]) -> None:
        with self._lock:
            self._pause_result = dict(result)
            self._pause_done.set()

    def request_reset(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
        with self._lock:
            self._reset_requested = True
            self._reset_done.clear()
            self._reset_result = {"ok": False, "reset_pending": True}
            self._wake_event.set()
        if not self._reset_done.wait(timeout_seconds):
            with self._lock:
                self._reset_requested = False
                self._refresh_wake_event_locked()
            return {"ok": False, "reset_pending": False, "timed_out": True}
        with self._lock:
            return dict(self._reset_result)

    def take_reset_request(self) -> bool:
        with self._lock:
            if not self._reset_requested:
                return False
            self._reset_requested = False
            self._refresh_wake_event_locked()
            return True

    def complete_reset(self, result: dict[str, Any]) -> None:
        with self._lock:
            self._reset_result = dict(result)
            self._reset_done.set()

    def _refresh_wake_event_locked(self) -> None:
        if self._pause_requested or self._reset_requested:
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


def run_collector(''',
    marker="def request_reset(self, timeout_seconds",
    flags=re.S,
)

replace_once(
    "worktrace/collector/collector.py",
    '''            now = now_str()
            phase = "gate_check"
            idle_threshold_seconds = get_int_setting("idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD_SECONDS)
            if last_loop_time:
''',
    '''            now = now_str()
            phase = "gate_check"
            idle_threshold_seconds = get_int_setting("idle_threshold_seconds", DEFAULT_IDLE_THRESHOLD_SECONDS)
            maintenance_active = is_secure_import_in_progress()
            prune_counter += 1
            if prune_counter >= 20 and not maintenance_active:
                clipboard_service.prune_old_events()
                prune_counter = 0
            if control is not None and control.take_reset_request():
                _set_clipboard_capture_enabled(adapter, False)
                machine.reset_runtime_state("database_generation_changed")
                control.complete_reset({"ok": True, "reset_pending": False})
                next_poll_deadline = _sleep_until_next_poll(stop_event, control, next_poll_deadline)
                last_loop_time = now
                continue
            if last_loop_time:
''',
    marker="machine.reset_runtime_state(\"database_generation_changed\")",
)

for old, new in [
    ('if not get_bool_setting("first_run_notice_accepted", False):\n                _pause_machine_then_expose(machine, now)', 'if not get_bool_setting("first_run_notice_accepted", False):\n                _set_clipboard_capture_enabled(adapter, False)\n                _pause_machine_then_expose(machine, now)'),
    ('if get_bool_setting("user_paused", False):\n                _pause_machine_then_expose(machine, now)', 'if get_bool_setting("user_paused", False):\n                _set_clipboard_capture_enabled(adapter, False)\n                _pause_machine_then_expose(machine, now)'),
    ('if is_secure_import_in_progress():\n                _pause_machine_then_expose(machine, now)', 'if maintenance_active:\n                _set_clipboard_capture_enabled(adapter, False)\n                _pause_machine_then_expose(machine, now)'),
]:
    replace_once("worktrace/collector/collector.py", old, new, marker=new)

replace_once(
    "worktrace/collector/collector.py",
    '''            phase = "clipboard"
            clipboard_events = _clipboard_events(adapter) if clipboard_service.is_capture_enabled() else []
            phase = "idle"
''',
    '''            phase = "clipboard"
            capture_enabled = clipboard_service.is_capture_enabled()
            _set_clipboard_capture_enabled(adapter, capture_enabled)
            clipboard_events = _clipboard_events(adapter) if capture_enabled else []
            phase = "idle"
''',
    marker="_set_clipboard_capture_enabled(adapter, capture_enabled)",
)

replace_regex(
    "worktrace/collector/collector.py",
    r'''            phase = "prune"\n            prune_counter \+= 1\n            if prune_counter >= 20:\n                clipboard_service\.prune_old_events\(\)\n                prune_counter = 0\n''',
    '',
    marker="maintenance_active = is_secure_import_in_progress()",
)

replace_once(
    "worktrace/collector/collector.py",
    '''    if delay > 0:
        wait_func(stop_event, control, delay)
    else:
        logging.debug("collector loop exceeded 1s cadence by %.3fs", abs(delay))
    return float(next_poll_deadline) + POLL_CADENCE_SECONDS
''',
    '''    if delay > 0:
        wait_func(stop_event, control, delay)
        return float(next_poll_deadline) + POLL_CADENCE_SECONDS
    logging.debug("collector loop exceeded 1s cadence by %.3fs; rebasing", abs(delay))
    return float(now) + POLL_CADENCE_SECONDS
''',
    marker="exceeded 1s cadence by %.3fs; rebasing",
)

replace_once(
    "worktrace/collector/collector.py",
    '''def _clipboard_events(adapter: PlatformAdapter):
''',
    '''def _set_clipboard_capture_enabled(adapter: PlatformAdapter, enabled: bool) -> None:
    setter = getattr(adapter, "set_clipboard_capture_enabled", None)
    if setter is None:
        return
    try:
        setter(bool(enabled))
    except Exception as exc:
        collector_health.record_transient_failure("clipboard_lifecycle", exc, now_str())


def _clipboard_events(adapter: PlatformAdapter):
''',
    marker="def _set_clipboard_capture_enabled",
)

# Recorder/state-machine generation reset without touching the replaced DB.
replace_once(
    "worktrace/collector/activity_session_recorder.py",
    '''    def clear_runtime_state(self, reason: str) -> None:
        self.project_ownership_state = clear_ownership_state()
        clear_runtime_activity_state(reason)
''',
    '''    def clear_runtime_state(self, reason: str) -> None:
        self.current_payload = None
        self.current_signature = None
        self.current_start_time = None
        self.current_last_seen_time = None
        self.persisted_activity_id = None
        self.project_ownership_state = clear_ownership_state()
        self.clear_snapshot()
        clear_runtime_activity_state(reason)
''',
    marker="self.persisted_activity_id = None\n        self.project_ownership_state = clear_ownership_state()\n        self.clear_snapshot()",
)

replace_once(
    "worktrace/collector/state_machine.py",
    '''    def split_at_midnight(self, at_time: str) -> None:
''',
    '''    def reset_runtime_state(self, reason: str = "runtime_reset") -> None:
        """Forget all process-local activity identity after DB replacement."""
        self.recorder.clear_runtime_state(reason)
        self.state = "stopped"
        self.active_signature = None

    def split_at_midnight(self, at_time: str) -> None:
''',
    marker="def reset_runtime_state(self, reason",
)

# ---------------------------------------------------------------------------
# Runtime owns adapter and serializes worker lifecycle.
# ---------------------------------------------------------------------------
replace_once(
    "worktrace/runtime/app_runtime.py",
    '''from ..services.secure_backup_service import (
    clear_collector_pause_handler,
    register_collector_pause_handler,
)
''',
    '''from ..services.secure_backup_service import (
    clear_collector_pause_handler,
    clear_collector_reset_handler,
    register_collector_pause_handler,
    register_collector_reset_handler,
)
''',
    marker="register_collector_reset_handler",
)

replace_once(
    "worktrace/runtime/app_runtime.py",
    '''        self.stop_event = threading.Event()
        self.owns_collector = False
        self.collector_control = CollectorControl()
''',
    '''        self.stop_event = threading.Event()
        self.owns_collector = False
        self.collector_control = CollectorControl()
        self._lifecycle_lock = threading.RLock()
        self._adapter = _choose_adapter()
''',
    marker="self._lifecycle_lock = threading.RLock()",
)

replace_regex(
    "worktrace/runtime/app_runtime.py",
    r'''    def start_background_workers\(self\) -> bool:\n.*?\n    def start_collector\(self\) -> dict\[str, object\]:''',
    '''    def start_background_workers(self) -> bool:
        """Start or replace the folder-index worker under the lifecycle lock."""
        with self._lifecycle_lock:
            if not self.owns_collector or self._shutdown or self.stop_event.is_set():
                return False
            if self._index_thread is not None and self._index_thread.is_alive():
                return False
            self._index_thread = folder_index_service.start_folder_index_worker(self.stop_event)
            return self._index_thread is not None

    def start_collector(self) -> dict[str, object]:''',
    marker="Start or replace the folder-index worker",
    flags=re.S,
)

replace_regex(
    "worktrace/runtime/app_runtime.py",
    r'''    def start_collector\(self\) -> dict\[str, object\]:\n.*?\n    def pause_collection_now\(''',
    '''    def start_collector(self) -> dict[str, object]:
        """Start the collector exactly once under the lifecycle lock."""
        with self._lifecycle_lock:
            if self._shutdown or self.stop_event.is_set():
                return {"ok": False, "error": "runtime_stopping"}
            if not self.owns_collector:
                return {"ok": False, "error": "collector_not_owned"}
            if self._collector_thread is not None and self._collector_thread.is_alive():
                register_collector_pause_handler(self.pause_collection_now)
                register_collector_reset_handler(self.reset_collection_runtime_now)
                return {"ok": True, "started": False, "already_running": True}
            if self._collector_thread is not None:
                collector_health.record_health_code("thread_dead_replaced")
                self._collector_thread = None
                self.collector_control = CollectorControl()
            try:
                self._collector_thread = threading.Thread(
                    target=run_collector,
                    args=(self._adapter, self.stop_event, self.collector_control),
                    name="WorkTraceCollector",
                    daemon=True,
                )
                self._collector_thread.start()
            except Exception:
                logging.exception("collector thread start failed")
                self._collector_thread = None
                return {"ok": False, "error": "collector_start_failed"}
            set_setting("collector_status", "running")
            set_setting("collector_health_state", "healthy")
            register_collector_pause_handler(self.pause_collection_now)
            register_collector_reset_handler(self.reset_collection_runtime_now)
            return {"ok": True, "started": True, "already_running": False}

    def pause_collection_now(''',
    marker="Start the collector exactly once under the lifecycle lock",
    flags=re.S,
)

replace_once(
    "worktrace/runtime/app_runtime.py",
    '''        return self.collector_control.request_pause(timeout_seconds=timeout_seconds)

    def request_shutdown(self) -> None:
''',
    '''        return self.collector_control.request_pause(timeout_seconds=timeout_seconds)

    def reset_collection_runtime_now(self, timeout_seconds: float = 5.0) -> dict[str, object]:
        if (
            not self.owns_collector
            or self._collector_thread is None
            or not self._collector_thread.is_alive()
        ):
            resetter = getattr(self._adapter, "reset_runtime_state", None)
            if resetter is not None:
                resetter()
            return {"ok": True, "reset_pending": False, "collector_active": False}
        result = self.collector_control.request_reset(timeout_seconds=timeout_seconds)
        if bool(result.get("ok")):
            resetter = getattr(self._adapter, "reset_runtime_state", None)
            if resetter is not None:
                resetter()
        return result

    def set_clipboard_capture_enabled(self, enabled: bool) -> None:
        setter = getattr(self._adapter, "set_clipboard_capture_enabled", None)
        if setter is not None:
            setter(bool(enabled))

    def request_shutdown(self) -> None:
''',
    marker="def reset_collection_runtime_now",
)

replace_once(
    "worktrace/runtime/app_runtime.py",
    '''        clear_collector_pause_handler(self.pause_collection_now)
        self.stop_event.set()
''',
    '''        clear_collector_pause_handler(self.pause_collection_now)
        clear_collector_reset_handler(self.reset_collection_runtime_now)
        self.stop_event.set()
''',
    marker="clear_collector_reset_handler",
)

replace_once(
    "worktrace/runtime/app_runtime.py",
    '''        if self.owns_collector:
            activity_lifecycle_service.close_all_open_activities()
            set_setting("collector_status", "stopped")
            release_single_instance()
        logging.info("app shutdown")
''',
    '''        if self.owns_collector:
            activity_lifecycle_service.close_all_open_activities()
            set_setting("collector_status", "stopped")
            release_single_instance()
        shutdown_adapter = getattr(self._adapter, "shutdown", None)
        if shutdown_adapter is not None:
            shutdown_adapter()
        logging.info("app shutdown")
''',
    marker="shutdown_adapter = getattr",
)

# App API exposes immediate clipboard lifecycle control.
replace_once(
    "worktrace/api/app_api.py",
    '''def request_shutdown() -> None:
''',
    '''def set_clipboard_capture_enabled(enabled: bool) -> None:
    if _runtime is not None:
        _runtime.set_clipboard_capture_enabled(bool(enabled))


def request_shutdown() -> None:
''',
    marker="def set_clipboard_capture_enabled",
)
replace_once(
    "worktrace/api/app_api.py",
    '''    "set_runtime",
''',
    '''    "set_runtime",
    "set_clipboard_capture_enabled",
''',
    marker='"set_clipboard_capture_enabled"',
)
replace_once(
    "worktrace/api/settings_api.py",
    '''def set_clipboard_capture_enabled(value: bool) -> None:
    set_setting("clipboard_capture_enabled", "true" if value else "false")
''',
    '''def set_clipboard_capture_enabled(value: bool) -> None:
    from . import app_api

    app_api.set_clipboard_capture_enabled(bool(value))
    set_setting("clipboard_capture_enabled", "true" if value else "false")
''',
    marker="app_api.set_clipboard_capture_enabled",
)

# ---------------------------------------------------------------------------
# One destructive-operation coordinator, with reset-before-replacement.
# ---------------------------------------------------------------------------
replace_once(
    "worktrace/services/secure_backup_service.py",
    '''BACKUP_FILE_SUFFIX = ".wtbackup"
''',
    '''BACKUP_FILE_SUFFIX = ".wtbackup"
MAX_BACKUP_FILE_BYTES = 512 * 1024 * 1024
MAX_BACKUP_PAYLOAD_BYTES = 384 * 1024 * 1024
''',
    marker="MAX_BACKUP_FILE_BYTES",
)

replace_once(
    "worktrace/services/secure_backup_service.py",
    '''    with SECURE_IMPORT_COORDINATOR.acquire() as guard:
        blob = Path(input_path).read_bytes()
''',
    '''    input_file = Path(input_path)
    if input_file.stat().st_size > MAX_BACKUP_FILE_BYTES:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    with SECURE_IMPORT_COORDINATOR.acquire(reason="secure_import") as guard:
        blob = input_file.read_bytes()
''',
    marker="MAX_BACKUP_FILE_BYTES:\n        raise BackupCorruptedError",
)
replace_once(
    "worktrace/services/secure_backup_service.py",
    '''def parse_encrypted_backup_manifest(input_path: str | Path) -> BackupManifestInfo:
    blob = Path(input_path).read_bytes()
''',
    '''def parse_encrypted_backup_manifest(input_path: str | Path) -> BackupManifestInfo:
    input_file = Path(input_path)
    if input_file.stat().st_size > MAX_BACKUP_FILE_BYTES:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    blob = input_file.read_bytes()
''',
    marker="def parse_encrypted_backup_manifest(input_path: str | Path) -> BackupManifestInfo:\n    input_file",
)
replace_once(
    "worktrace/services/secure_backup_service.py",
    '''def _parse_and_validate_payload(payload: bytes) -> dict[str, Any]:
    try:
''',
    '''def _parse_and_validate_payload(payload: bytes) -> dict[str, Any]:
    if len(payload) > MAX_BACKUP_PAYLOAD_BYTES:
        raise BackupCorruptedError("backup file is invalid or corrupted")
    try:
''',
    marker="if len(payload) > MAX_BACKUP_PAYLOAD_BYTES",
)

replace_regex(
    "worktrace/services/secure_backup_service.py",
    r'''class SecureImportCoordinator:\n.*?\n\nSECURE_IMPORT_COORDINATOR = SecureImportCoordinator\(\)''',
    '''class SecureImportCoordinator:
    """Single process coordinator for every destructive database replacement."""

    def __init__(self) -> None:
        self._import_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._write_gate = False
        self._pause_handler: Any = None
        self._reset_handler: Any = None

    def register_collector_pause_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._pause_handler = handler

    def clear_collector_pause_handler(self, handler: Any | None = None) -> None:
        with self._state_lock:
            if handler is None or self._pause_handler == handler:
                self._pause_handler = None

    def register_collector_reset_handler(self, handler: Any) -> None:
        with self._state_lock:
            self._reset_handler = handler

    def clear_collector_reset_handler(self, handler: Any | None = None) -> None:
        with self._state_lock:
            if handler is None or self._reset_handler == handler:
                self._reset_handler = None

    def write_gate_active(self) -> bool:
        with self._state_lock:
            return self._write_gate or DATABASE_WRITE_GATE.active()

    @contextmanager
    def acquire(self, *, reason: str = "secure_import") -> Iterator[_ImportGuardState]:
        if not self._import_lock.acquire(blocking=False):
            logging.warning("runtime maintenance rejected reason=%s", reason)
            raise BackupImportInProgressError("another destructive operation is already in progress")

        from ..collector.snapshot_publisher import DEFAULT_SNAPSHOT_PUBLISHER

        prior_user_paused = get_bool_setting("user_paused", False)
        prior_collector_status = get_setting("collector_status", "stopped") or "stopped"
        prior_snapshot = DEFAULT_SNAPSHOT_PUBLISHER.read_raw()
        state = _ImportGuardState(prior_user_paused, prior_collector_status, prior_snapshot)
        pause_state_changed = False
        try:
            with self._state_lock:
                pause_handler = self._pause_handler
                reset_handler = self._reset_handler
            if pause_handler is not None:
                result = pause_handler(timeout_seconds=5.0)
                if not bool(result.get("ok")):
                    raise SecureBackupError("collector_pause_not_acknowledged")
            if reset_handler is not None:
                result = reset_handler(timeout_seconds=5.0)
                if not bool(result.get("ok")):
                    raise SecureBackupError("collector_reset_not_acknowledged")

            set_setting("user_paused", "true")
            set_setting("collector_status", "paused")
            clear_runtime_activity_state(f"{reason}_guard_enter")
            pause_state_changed = True

            with DATABASE_WRITE_GATE.acquire():
                with self._state_lock:
                    self._write_gate = True
                try:
                    yield state
                except Exception:
                    if not state.succeeded:
                        set_setting("user_paused", "true" if prior_user_paused else "false")
                        set_setting("collector_status", prior_collector_status)
                        DEFAULT_SNAPSHOT_PUBLISHER.restore_raw(prior_snapshot)
                    raise
                else:
                    clear_runtime_activity_state(f"{reason}_success")
                    logging.info("runtime maintenance completed reason=%s paused=true", reason)
                finally:
                    with self._state_lock:
                        self._write_gate = False
        except Exception as exc:
            if pause_state_changed and not state.succeeded and not DATABASE_WRITE_GATE.active():
                set_setting("user_paused", "true" if prior_user_paused else "false")
                set_setting("collector_status", prior_collector_status)
                DEFAULT_SNAPSHOT_PUBLISHER.restore_raw(prior_snapshot)
            logging.warning("runtime maintenance failed reason=%s exc_type=%s", reason, type(exc).__name__)
            raise
        finally:
            clear_settings_cache()
            self._import_lock.release()


SECURE_IMPORT_COORDINATOR = SecureImportCoordinator()''',
    marker="Single process coordinator for every destructive database replacement",
    flags=re.S,
)

replace_once(
    "worktrace/services/secure_backup_service.py",
    '''def clear_collector_pause_handler(handler: Any | None = None) -> None:
    SECURE_IMPORT_COORDINATOR.clear_collector_pause_handler(handler)


def is_secure_import_in_progress() -> bool:
''',
    '''def clear_collector_pause_handler(handler: Any | None = None) -> None:
    SECURE_IMPORT_COORDINATOR.clear_collector_pause_handler(handler)


def register_collector_reset_handler(handler: Any) -> None:
    SECURE_IMPORT_COORDINATOR.register_collector_reset_handler(handler)


def clear_collector_reset_handler(handler: Any | None = None) -> None:
    SECURE_IMPORT_COORDINATOR.clear_collector_reset_handler(handler)


def is_secure_import_in_progress() -> bool:
''',
    marker="def register_collector_reset_handler",
)

# Clear-all now uses the same acknowledged pause/reset/write gate.
replace_once(
    "worktrace/services/export_service.py",
    '''import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
''',
    '''import os
from pathlib import Path
''',
    marker="from pathlib import Path\n\nfrom ..db",
)
replace_once(
    "worktrace/services/export_service.py",
    '''from .runtime_activity_state_service import clear_runtime_activity_state
''',
    '',
    marker="from . import statistics_service",
)
replace_regex(
    "worktrace/services/export_service.py",
    r'''def export_all_local_data\(path: str\) -> str:\n.*?\n\ndef clear_all_local_data''',
    '''def export_all_local_data(path: str) -> str:
    from openpyxl import Workbook
    from .secure_backup_service import EXPORT_TABLES

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    default = wb.active
    wb.remove(default)
    with get_connection() as conn:
        conn.execute("BEGIN")
        try:
            for table in EXPORT_TABLES:
                ws = wb.create_sheet(table)
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                columns = [item["name"] for item in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                ws.append(columns)
                for row in rows:
                    ws.append([row[col] for col in columns])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    wb.save(out)
    logging.info("all local data export success")
    return str(out)


def clear_all_local_data''',
    marker="from .secure_backup_service import EXPORT_TABLES",
    flags=re.S,
)
replace_regex(
    "worktrace/services/export_service.py",
    r'''def clear_all_local_data\(confirm: bool\) -> None:\n.*?\n\ndef _invalidate_clear_all_caches''',
    '''def clear_all_local_data(confirm: bool) -> None:
    """Clear all local data through the process maintenance coordinator."""
    if not confirm:
        raise ValueError("confirmation is required")
    from .secure_backup_service import BackupImportInProgressError, SECURE_IMPORT_COORDINATOR

    try:
        with SECURE_IMPORT_COORDINATOR.acquire(reason="clear_all") as guard:
            reset_database()
            guard.mark_succeeded()
    except BackupImportInProgressError as exc:
        raise ValueError("operation_in_progress") from exc
    _invalidate_clear_all_caches()
    logging.info("all local data cleared at %s", now_str())


def _invalidate_clear_all_caches''',
    marker="through the process maintenance coordinator",
    flags=re.S,
)

# ---------------------------------------------------------------------------
# Windows adapter lifecycle, bounded queues/calls, TTL path cache and idle API.
# ---------------------------------------------------------------------------
replace_once(
    "worktrace/platforms/windows_adapter.py",
    '''_COM_FAILURE_COOLDOWN_SECONDS = 30.0
_OPEN_FILES_FAILURE_COOLDOWN_SECONDS = 30.0
''',
    '''_COM_FAILURE_COOLDOWN_SECONDS = 30.0
_OPEN_FILES_FAILURE_COOLDOWN_SECONDS = 30.0
_PATH_CACHE_SUCCESS_TTL_SECONDS = 3.0
_PATH_CACHE_FAILURE_TTL_SECONDS = 0.75
_MAX_CLIPBOARD_QUEUE = 100
_TIMEOUT_CALL_SLOTS = threading.BoundedSemaphore(2)
''',
    marker="_PATH_CACHE_SUCCESS_TTL_SECONDS",
)
replace_once(
    "worktrace/platforms/windows_adapter.py",
    '''_active_file_path_cache: dict[tuple[int | None, int | None, str, str], str | None] = {}
''',
    '''_active_file_path_cache: dict[tuple[int | None, int | None, str, str], tuple[float, str | None]] = {}
''',
    marker="tuple[float, str | None]",
)
replace_regex(
    "worktrace/platforms/windows_adapter.py",
    r'''def _run_with_timeout\(func, timeout_seconds: float, \*args\):\n.*?\n\nclass WindowsAdapter:''',
    '''def _run_with_timeout(func, timeout_seconds: float, *args):
    """Run a blocking call with a process-wide cap on abandoned workers."""
    if not _TIMEOUT_CALL_SLOTS.acquire(blocking=False):
        raise TimeoutError("blocking resolver capacity exhausted")
    result_box: list = [None]
    exc_box: list = [None]
    done = threading.Event()

    def _worker():
        try:
            result_box[0] = func(*args)
        except Exception as exc:
            exc_box[0] = exc
        finally:
            done.set()
            _TIMEOUT_CALL_SLOTS.release()

    threading.Thread(target=_worker, daemon=True).start()
    if not done.wait(timeout=timeout_seconds):
        raise TimeoutError(f"call timed out after {timeout_seconds:.1f}s")
    if exc_box[0] is not None:
        raise exc_box[0]
    return result_box[0]


class WindowsAdapter:''',
    marker="process-wide cap on abandoned workers",
    flags=re.S,
)
replace_regex(
    "worktrace/platforms/windows_adapter.py",
    r'''class WindowsAdapter:\n.*?\n\nclass _ClipboardMonitor:''',
    '''class WindowsAdapter:
    def __init__(self) -> None:
        self._clipboard_monitor = _ClipboardMonitor()

    def get_active_window(self) -> ActiveWindow:
        return _get_foreground_active_window()

    def get_idle_seconds(self) -> int:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        last_input = LASTINPUTINFO()
        last_input.cbSize = ctypes.sizeof(last_input)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(last_input)):
            return 0
        get_tick_count64 = ctypes.windll.kernel32.GetTickCount64
        get_tick_count64.restype = ctypes.c_ulonglong
        tick_count = int(get_tick_count64())
        last_input_tick = int(last_input.dwTime)
        current_low = tick_count & 0xFFFFFFFF
        elapsed_ms = (current_low - last_input_tick) & 0xFFFFFFFF
        return max(0, int(elapsed_ms / 1000))

    def set_clipboard_capture_enabled(self, enabled: bool) -> None:
        self._clipboard_monitor.set_enabled(enabled)

    def get_clipboard_events(self) -> list[ClipboardTextEvent]:
        return self._clipboard_monitor.drain()

    def reset_runtime_state(self) -> None:
        self._clipboard_monitor.set_enabled(False)
        self._clipboard_monitor.clear()
        with _active_file_path_lock:
            _active_file_path_cache.clear()
            _active_file_path_inflight.clear()

    def shutdown(self) -> None:
        self._clipboard_monitor.shutdown()


class _ClipboardMonitor:''',
    marker="def set_clipboard_capture_enabled(self, enabled",
    flags=re.S,
)
replace_regex(
    "worktrace/platforms/windows_adapter.py",
    r'''class _ClipboardMonitor:\n.*?\n\ndef _get_foreground_active_window''',
    '''class _ClipboardMonitor:
    def __init__(self) -> None:
        self._events: deque[ClipboardTextEvent] = deque(maxlen=_MAX_CLIPBOARD_QUEUE)
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._started = False
        self._enabled = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_sequence: int | None = None

    def set_enabled(self, enabled: bool) -> None:
        with self._lifecycle_lock:
            enabled = bool(enabled)
            if not enabled:
                self._enabled = False
                self.clear()
                self._last_sequence = None
                return
            self._enabled = True
            if not self._started:
                self._started = True
                self._stop_event.clear()
                self._thread = threading.Thread(target=self._run, name="WorkTraceClipboardMonitor", daemon=True)
                self._thread.start()

    def drain(self) -> list[ClipboardTextEvent]:
        if not self._enabled:
            self.clear()
            return []
        with self._lock:
            events = list(self._events)
            self._events.clear()
        return events

    def clear(self) -> None:
        with self._lock:
            self._events.clear()

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            self._enabled = False
            self._stop_event.set()
            thread = self._thread
        self.clear()
        if thread is not None:
            thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop_event.wait(0.25):
            if not self._enabled:
                continue
            try:
                sequence = _clipboard_sequence_number()
                if sequence is None:
                    continue
                if self._last_sequence is None:
                    self._last_sequence = sequence
                    continue
                if sequence != self._last_sequence:
                    self._last_sequence = sequence
                    self._capture(sequence)
            except Exception:
                logging.debug("clipboard monitor loop failed", exc_info=True)

    def _capture(self, sequence: int) -> None:
        if not self._enabled:
            return
        text = _read_clipboard_unicode_text()
        if not text or not self._enabled:
            return
        event = ClipboardTextEvent(
            text=text,
            source_window=_get_foreground_active_window(),
            copied_at=datetime.now().strftime(TIME_FORMAT),
            sequence_number=sequence,
        )
        with self._lock:
            if self._enabled:
                self._events.append(event)


def _get_foreground_active_window''',
    marker="_MAX_CLIPBOARD_QUEUE",
    flags=re.S,
)
replace_once(
    "worktrace/platforms/windows_adapter.py",
    '''    if not file_path_hint:
        with _active_file_path_lock:
            file_path_hint = _active_file_path_cache.get(cache_key)
    if not file_path_hint:
        _schedule_active_file_path_resolution(cache_key, process_name, title, pid)
''',
    '''    if not file_path_hint:
        with _active_file_path_lock:
            cached = _active_file_path_cache.get(cache_key)
            if cached is not None and cached[0] > time.monotonic():
                file_path_hint = cached[1]
            elif cached is not None:
                _active_file_path_cache.pop(cache_key, None)
    if not file_path_hint:
        _schedule_active_file_path_resolution(cache_key, process_name, title, pid)
''',
    marker="cached[0] > time.monotonic()",
)
replace_once(
    "worktrace/platforms/windows_adapter.py",
    '''        if cache_key in _active_file_path_cache:
            return
''',
    '''        cached = _active_file_path_cache.get(cache_key)
        if cached is not None and cached[0] > time.monotonic():
            return
        _active_file_path_cache.pop(cache_key, None)
''',
    marker="cached = _active_file_path_cache.get(cache_key)",
)
replace_once(
    "worktrace/platforms/windows_adapter.py",
    '''                _active_file_path_cache[cache_key] = resolved
                _active_file_path_inflight.discard(cache_key)
''',
    '''                ttl = _PATH_CACHE_SUCCESS_TTL_SECONDS if resolved else _PATH_CACHE_FAILURE_TTL_SECONDS
                _active_file_path_cache[cache_key] = (time.monotonic() + ttl, resolved)
                _active_file_path_inflight.discard(cache_key)
''',
    marker="_PATH_CACHE_FAILURE_TTL_SECONDS",
)

# ---------------------------------------------------------------------------
# Privacy fail-closed and late-path transactional anonymisation.
# ---------------------------------------------------------------------------
replace_once(
    "worktrace/collector/resource_identity_resolver.py",
    '''        except Exception:
            return False

    def _supplement_path_if_needed(
''',
    '''        except Exception:
            return True

    def _supplement_path_if_needed(
''',
    marker="except Exception:\n            return True\n\n    def _supplement_path_if_needed",
)
replace_regex(
    "worktrace/services/privacy_service.py",
    r'''def _matches_indexed_exclude_folder\(window_title: str \| None\) -> bool:\n    if not \(window_title or ""\)\.strip\(\):\n        return False\n    try:\n        from \.folder_index_service import resolve_unique_path_from_title\n\n        path = resolve_unique_path_from_title\(window_title, include_excluded=True\)\n    except Exception:\n        return False\n    return _matches_exclude_folder\(path\)''',
    '''def _matches_indexed_exclude_folder(window_title: str | None) -> bool:
    if not (window_title or "").strip():
        return False
    from .folder_index_service import resolve_unique_path_from_title

    path = resolve_unique_path_from_title(window_title, include_excluded=True)
    return _matches_exclude_folder(path)''',
    marker="from .folder_index_service import resolve_unique_path_from_title\n\n    path =",
)

replace_once(
    "worktrace/services/activity_service.py",
    '''def update_activity_file_path_hint(activity_id: int, file_path_hint: str) -> None:
    if not (file_path_hint or "").strip():
        return
    with get_connection() as conn:
        conn.execute(
            "UPDATE activity_log SET file_path_hint = ?, updated_at = ? WHERE id = ?",
            (file_path_hint, now_str(), activity_id),
        )
        _sync_activity_resource_after_path_update(conn, activity_id, file_path_hint)
    from .project_inference_service import assign_project_for_activity

    assign_project_for_activity(activity_id)
''',
    '''def update_activity_file_path_hint(activity_id: int, file_path_hint: str) -> None:
    if not (file_path_hint or "").strip():
        return
    excluded = False
    with get_connection() as conn:
        row = conn.execute(
            "SELECT app_name, process_name, window_title FROM activity_log WHERE id = ?",
            (activity_id,),
        ).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE activity_log SET file_path_hint = ?, updated_at = ? WHERE id = ?",
            (file_path_hint, now_str(), activity_id),
        )
        _sync_activity_resource_after_path_update(conn, activity_id, file_path_hint)
        from . import privacy_service

        excluded = privacy_service.is_excluded(
            ActiveWindow(
                app_name=str(row["app_name"] or ""),
                process_name=str(row["process_name"] or ""),
                window_title=str(row["window_title"] or ""),
                file_path_hint=file_path_hint,
            )
        )
        if excluded:
            payload = privacy_service.make_excluded_activity_payload()
            conn.execute(
                """
                UPDATE activity_log
                SET app_name = ?, process_name = ?, window_title = ?, file_path_hint = NULL,
                    status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload["app_name"], payload["process_name"], payload["window_title"],
                    STATUS_EXCLUDED, now_str(), activity_id,
                ),
            )
            conn.execute("DELETE FROM activity_clipboard_event WHERE activity_id = ?", (activity_id,))
            create_or_update_activity_resource(
                activity_id,
                make_system_resource(STATUS_EXCLUDED),
                conn=conn,
            )
    if not excluded:
        from .project_inference_service import assign_project_for_activity

        assign_project_for_activity(activity_id)
''',
    marker="DELETE FROM activity_clipboard_event WHERE activity_id",
)

replace_once(
    "worktrace/services/activity_service.py",
    '''    duration, is_error = _duration_seconds(row["start_time"], end_time)
    existing = int(row["duration_seconds"] or 0)
''',
    '''    duration, is_error = _duration_seconds(row["start_time"], end_time)
    safe_end_time = row["start_time"] if is_error else end_time
    existing = int(row["duration_seconds"] or 0)
''',
    marker="safe_end_time = row[\"start_time\"] if is_error",
)
replace_once(
    "worktrace/services/activity_service.py",
    '''        (end_time, duration, status, now_str(), activity_id),
''',
    '''        (safe_end_time, duration, status, now_str(), activity_id),
''',
    marker="(safe_end_time, duration, status",
)

# ---------------------------------------------------------------------------
# Folder-index crash recovery and canonical deleted-project boundaries.
# ---------------------------------------------------------------------------
replace_once(
    "worktrace/services/folder_index_service.py",
    '''def rebuild_folder_index(rule_id: int, stop_event: threading.Event | None = None) -> bool:
''',
    '''def recover_interrupted_indexes() -> None:
    """Return process-interrupted indexing states to the pending queue."""
    ts = now_str()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE folder_rule_index_state
            SET status = ?, refresh_requested = 1, error_message = NULL, updated_at = ?
            WHERE status = ?
            """,
            (INDEX_STATUS_PENDING, ts, INDEX_STATUS_INDEXING),
        )


def rebuild_folder_index(rule_id: int, stop_event: threading.Event | None = None) -> bool:
''',
    marker="def recover_interrupted_indexes",
)
replace_once(
    "worktrace/services/folder_index_service.py",
    '''        ensure_index_states_for_folder_rules()
        validate_ready_indexes(stop_event)
''',
    '''        ensure_index_states_for_folder_rules()
        recover_interrupted_indexes()
        validate_ready_indexes(stop_event)
''',
    marker="recover_interrupted_indexes()",
)

replace_once(
    "worktrace/services/report_projection_snapshot_service.py",
    '''    reportable_rows = [
        row
        for row in rows
        if not bool(row.get("effective_project_is_deleted") or row.get("report_project_is_deleted"))
    ]
    boundaries = timeline_service._boundary_times_for_rows(reportable_rows, conn=conn)
''',
    '''    deleted_rows = [
        row
        for row in rows
        if bool(row.get("effective_project_is_deleted") or row.get("report_project_is_deleted"))
    ]
    reportable_rows = [row for row in rows if row not in deleted_rows]
    boundaries = list(timeline_service._boundary_times_for_rows(rows, conn=conn))
    for row in deleted_rows:
        for value in (row.get("start_time"), row.get("end_time")):
            if value:
                boundaries.append(str(value))
    boundaries = sorted(set(boundaries))
''',
    marker="deleted_rows = [",
)

# ---------------------------------------------------------------------------
# Backup resource limits, KDF limits, startup result and failure classification.
# ---------------------------------------------------------------------------
replace_once(
    "worktrace/security/kdf.py",
    '''MIN_SALT_BYTES = 16
''',
    '''MIN_SALT_BYTES = 16
MAX_SCRYPT_N = 2**18
MAX_SCRYPT_R = 32
MAX_SCRYPT_P = 8
''',
    marker="MAX_SCRYPT_N",
)
replace_once(
    "worktrace/security/kdf.py",
    '''    if params.r < 1 or params.p < 1:
        raise KdfError("Invalid scrypt parameters")
''',
    '''    if params.r < 1 or params.p < 1:
        raise KdfError("Invalid scrypt parameters")
    if params.n > MAX_SCRYPT_N or params.r > MAX_SCRYPT_R or params.p > MAX_SCRYPT_P:
        raise KdfError("Unsupported scrypt resource parameters")
''',
    marker="Unsupported scrypt resource parameters",
)
replace_once(
    "worktrace/collector/collector_health.py",
    '''import logging
from datetime import datetime
''',
    '''import logging
import sqlite3
from datetime import datetime
''',
    marker="import sqlite3",
)
replace_once(
    "worktrace/collector/collector_health.py",
    '''def is_transient_failure(exc: BaseException) -> bool:
    return not isinstance(exc, (SystemExit, KeyboardInterrupt, MemoryError))
''',
    '''def is_transient_failure(exc: BaseException) -> bool:
    if isinstance(exc, (SystemExit, KeyboardInterrupt, MemoryError, AssertionError, TypeError, AttributeError, KeyError)):
        return False
    if isinstance(exc, sqlite3.DatabaseError):
        message = str(exc).lower()
        return any(token in message for token in ("locked", "busy", "secure_import_in_progress", "database_generation_changed"))
    return True
''',
    marker="database_generation_changed",
)
replace_once(
    "worktrace/webview_main.py",
    '''    try:
        app_api.start_collection_after_privacy_gate()
    except Exception:
''',
    '''    try:
        startup_result = app_api.start_collection_after_privacy_gate()
        if not startup_result.get("ok"):
            logging.error("collector startup rejected error=%s", startup_result.get("error", "unknown"))
    except Exception:
''',
    marker="startup_result = app_api.start_collection_after_privacy_gate()",
)

# Update existing cadence expectation to the rebase contract.
replace_once(
    "tests/test_collector.py",
    '''    assert next_deadline == pytest.approx(2.0)
''',
    '''    assert next_deadline == pytest.approx(2.2)
''',
    marker="assert next_deadline == pytest.approx(2.2)",
)

print("runtime hardening transformations applied")
