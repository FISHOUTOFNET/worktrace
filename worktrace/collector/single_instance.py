from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Callable, Protocol

from ..config import resolve_paths

_mutex_handle = None
_lock_file: Path | None = None
_lock_fd: int | None = None


class SingleInstanceError(RuntimeError):
    pass


def _windows_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateEventW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.OpenEventW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.SetEvent.argtypes = [ctypes.c_void_p]
    kernel32.SetEvent.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    return kernel32


def acquire_single_instance() -> bool:
    global _mutex_handle, _lock_file, _lock_fd
    if _mutex_handle or _lock_fd is not None:
        return False
    if os.name == "nt":
        kernel32 = _windows_kernel32()
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, _windows_mutex_name())
        error_code = int(ctypes.get_last_error())
        if not handle:
            raise SingleInstanceError(
                f"single_instance_mutex_create_failed:{error_code}"
            )
        already_exists = error_code == 183
        if already_exists:
            try:
                kernel32.CloseHandle(handle)
            finally:
                handle = None
            return False
        _mutex_handle = handle
        return True

    lock = resolve_paths().base_dir / "worktrace.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        os.ftruncate(fd, 0)
        payload = str(os.getpid()).encode("ascii")
        written = os.write(fd, payload)
        if written != len(payload):
            raise OSError("single_instance_pid_write_incomplete")
        os.fsync(fd)
    except (BlockingIOError, OSError):
        if acquired:
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                logging.warning("single instance partial unlock failed")
        try:
            os.close(fd)
        except OSError:
            logging.warning("single instance partial descriptor close failed")
        if acquired:
            raise
        return False
    except Exception:
        if acquired:
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                logging.warning("single instance partial unlock failed")
        try:
            os.close(fd)
        except OSError:
            logging.warning("single instance partial descriptor close failed")
        raise
    _lock_file = lock
    _lock_fd = fd
    return True


def _windows_mutex_name() -> str:
    base = str(resolve_paths().base_dir.resolve()).casefold()
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
    return f"Local\\WorkTrace_Instance_{digest}"


def _windows_activation_event_name() -> str:
    base = str(resolve_paths().base_dir.resolve()).casefold()
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
    return f"Local\\WorkTrace_Activate_{digest}"


def release_single_instance() -> None:
    global _mutex_handle, _lock_file, _lock_fd
    handle = _mutex_handle
    fd = _lock_fd
    _mutex_handle = None
    _lock_fd = None
    _lock_file = None

    if os.name == "nt" and handle:
        try:
            if not _windows_kernel32().CloseHandle(handle):
                logging.warning("single instance mutex release failed")
        except Exception:
            logging.warning("single instance mutex release failed")
    if fd is not None:
        try:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                logging.warning("single instance file unlock failed")
        finally:
            try:
                os.close(fd)
            except OSError:
                logging.warning("single instance descriptor close failed")
    # The pathname is diagnostic only. The kernel lock is released after crashes,
    # so a stale file never blocks a later process.


class ActivationKernel(Protocol):
    def create_activation_event(self, name: str): ...
    def signal_prepared_activation(self, event) -> bool: ...
    def signal_activation_event(self, name: str) -> bool: ...
    def wait_for_activation(self, event, timeout_seconds: float) -> bool: ...
    def wake_activation_waiter(self, event) -> None: ...
    def close_activation_event(self, event) -> None: ...


class WindowsActivationKernel:
    EVENT_MODIFY_STATE = 0x0002
    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0

    @staticmethod
    def _kernel32():
        return _windows_kernel32()

    def create_activation_event(self, name: str):
        handle = self._kernel32().CreateEventW(None, False, False, name)
        if not handle:
            raise SingleInstanceError(
                f"single_instance_activation_event_create_failed:"
                f"{int(ctypes.get_last_error())}"
            )
        return handle

    def signal_activation_event(self, name: str) -> bool:
        kernel32 = self._kernel32()
        handle = kernel32.OpenEventW(
            self.EVENT_MODIFY_STATE | self.SYNCHRONIZE,
            False,
            name,
        )
        if not handle:
            return False
        try:
            return bool(kernel32.SetEvent(handle))
        finally:
            kernel32.CloseHandle(handle)

    def signal_prepared_activation(self, event) -> bool:
        return bool(self._kernel32().SetEvent(event))

    def wait_for_activation(self, event, timeout_seconds: float) -> bool:
        result = self._kernel32().WaitForSingleObject(
            event,
            max(1, int(timeout_seconds * 1000)),
        )
        return int(result) == self.WAIT_OBJECT_0

    def wake_activation_waiter(self, event) -> None:
        self._kernel32().SetEvent(event)

    def close_activation_event(self, event) -> None:
        self._kernel32().CloseHandle(event)


class ApplicationInstanceCoordinator:
    """Own the named activation Event across the process startup lifecycle."""

    def __init__(self, kernel: ActivationKernel | None = None) -> None:
        self._kernel = kernel if kernel is not None else WindowsActivationKernel()
        self._lock = threading.RLock()
        self._event = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._callback: Callable[[], object] | None = None
        self._pending_activation = False
        self._generation = 0
        self._active_callbacks = 0
        self._callback_condition = threading.Condition(self._lock)

    def _supported(self) -> bool:
        return not (
            os.name != "nt" and isinstance(self._kernel, WindowsActivationKernel)
        )

    def prepare_activation_event(self) -> None:
        if not self._supported():
            return
        with self._lock:
            if self._event is not None:
                return
            try:
                event = self._kernel.create_activation_event(
                    _windows_activation_event_name()
                )
            except Exception:
                logging.exception("activation event preparation failed")
                raise
            if event is None:
                logging.error("activation event preparation returned no handle")
                raise SingleInstanceError(
                    "single_instance_activation_event_create_failed:no_handle"
                )
            self._event = event
            self._stop_event.clear()
            self._generation += 1

    def start_activation_listener(self) -> None:
        if not self._supported():
            return
        with self._lock:
            if self._thread is not None:
                return
            if self._event is None:
                raise SingleInstanceError("activation_event_not_prepared")
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._wait_loop,
                name="WorkTraceInstanceActivation",
                daemon=True,
            )
            self._thread.start()

    def bind_activation_handler(self, callback: Callable[[], object]) -> None:
        if not callable(callback):
            raise TypeError("activation callback must be callable")
        with self._lock:
            self._callback = callback
            dispatch_pending = (
                self._pending_activation
                and self._event is not None
                and not self._stop_event.is_set()
            )
            if dispatch_pending:
                self._pending_activation = False
                generation = self._generation
            else:
                generation = -1
        if dispatch_pending:
            self._dispatch_callback(callback, generation)

    def signal_existing_instance(self) -> bool:
        if not self._supported():
            return False
        with self._lock:
            event = self._event
        if event is not None:
            try:
                if self._kernel.signal_prepared_activation(event):
                    return True
                logging.warning("prepared activation Event signal failed")
            except Exception:
                logging.warning(
                    "prepared activation Event signal raised",
                    exc_info=True,
                )
        try:
            signaled = self._kernel.signal_activation_event(
                _windows_activation_event_name()
            )
            if signaled:
                logging.warning("activation used named Event compatibility fallback")
                return True
            return False
        except Exception:
            logging.warning("named activation Event fallback failed", exc_info=True)
            return False

    def stop_activation_listener(self) -> None:
        with self._lock:
            thread = self._thread
            event = self._event
            self._thread = None
            self._event = None
            self._callback = None
            self._pending_activation = False
            self._generation += 1
            self._stop_event.set()
        if event is not None:
            try:
                self._kernel.wake_activation_waiter(event)
            except Exception:
                logging.warning("activation listener wake failed")
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            while self._active_callbacks:
                self._callback_condition.wait(timeout=0.1)
        if event is not None:
            try:
                self._kernel.close_activation_event(event)
            except Exception:
                logging.warning("activation event close failed")

    def _dispatch_callback(
        self,
        callback: Callable[[], object],
        generation: int,
    ) -> None:
        with self._lock:
            if (
                self._event is None
                or self._stop_event.is_set()
                or self._generation != generation
                or self._callback is not callback
            ):
                return
            self._active_callbacks += 1
        try:
            callback()
        except Exception:
            logging.exception("activation callback failed")
        finally:
            with self._lock:
                self._active_callbacks -= 1
                self._callback_condition.notify_all()

    def _wait_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                event = self._event
            if event is None:
                return
            try:
                signaled = self._kernel.wait_for_activation(event, 0.25)
            except Exception:
                logging.exception("activation listener wait failed")
                return
            if not signaled:
                continue
            with self._lock:
                if (
                    self._stop_event.is_set()
                    or self._event is not event
                    or self._thread is not threading.current_thread()
                ):
                    continue
                callback = self._callback
                generation = self._generation
                if callback is None:
                    self._pending_activation = True
                    continue
            self._dispatch_callback(callback, generation)


_application_instance_coordinator = ApplicationInstanceCoordinator()


def get_application_instance_coordinator() -> ApplicationInstanceCoordinator:
    return _application_instance_coordinator


def signal_existing_instance() -> bool:
    return _application_instance_coordinator.signal_existing_instance()


__all__ = [
    "ApplicationInstanceCoordinator",
    "SingleInstanceError",
    "acquire_single_instance",
    "get_application_instance_coordinator",
    "release_single_instance",
    "signal_existing_instance",
]
