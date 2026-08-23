"""Cooperative Windows shutdown channel for install and uninstall maintenance."""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Protocol

logger = logging.getLogger(__name__)

UPDATE_SHUTDOWN_EVENT_NAME = r"Local\WorkTrace_UpdateShutdown_v1"


class UpdateShutdownError(RuntimeError):
    pass


def _windows_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
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


class UpdateShutdownKernel(Protocol):
    def create_event(self, name: str): ...
    def event_exists(self, name: str) -> bool: ...
    def signal_event(self, name: str) -> bool: ...
    def wait_for_signal(self, event, timeout_seconds: float) -> bool: ...
    def wake_waiter(self, event) -> None: ...
    def close_event(self, event) -> None: ...


class MaintenanceProcessProbe(Protocol):
    def snapshot_other_same_executable_pids(self) -> set[int]: ...
    def any_alive(self, pids: set[int]) -> bool: ...


class WindowsUpdateShutdownKernel:
    EVENT_MODIFY_STATE = 0x0002
    SYNCHRONIZE = 0x00100000
    WAIT_OBJECT_0 = 0

    @staticmethod
    def _kernel32():
        return _windows_kernel32()

    def create_event(self, name: str):
        handle = self._kernel32().CreateEventW(None, False, False, name)
        if not handle:
            raise UpdateShutdownError(
                f"update_shutdown_event_create_failed:{int(ctypes.get_last_error())}"
            )
        return handle

    def event_exists(self, name: str) -> bool:
        kernel32 = self._kernel32()
        handle = kernel32.OpenEventW(self.SYNCHRONIZE, False, name)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True

    def signal_event(self, name: str) -> bool:
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

    def wait_for_signal(self, event, timeout_seconds: float) -> bool:
        result = self._kernel32().WaitForSingleObject(
            event,
            max(1, int(timeout_seconds * 1000)),
        )
        return int(result) == self.WAIT_OBJECT_0

    def wake_waiter(self, event) -> None:
        self._kernel32().SetEvent(event)

    def close_event(self, event) -> None:
        self._kernel32().CloseHandle(event)


class FrozenExecutableProcessProbe:
    """Track pre-existing processes backed by the same frozen executable."""

    def snapshot_other_same_executable_pids(self) -> set[int]:
        if os.name != "nt" or not bool(getattr(sys, "frozen", False)):
            return set()
        try:
            import psutil

            current = psutil.Process(os.getpid())
            excluded = {current.pid, *(parent.pid for parent in current.parents())}
            target = Path(sys.executable).resolve()
            matching: set[int] = set()
            for process in psutil.process_iter(("pid", "exe")):
                pid = int(process.info.get("pid") or 0)
                if pid <= 0 or pid in excluded:
                    continue
                executable = process.info.get("exe")
                if not executable:
                    continue
                try:
                    if Path(str(executable)).resolve() == target:
                        matching.add(pid)
                except (OSError, RuntimeError):
                    continue
            return matching
        except Exception:
            logger.warning("maintenance process snapshot failed", exc_info=True)
            return set()

    def any_alive(self, pids: set[int]) -> bool:
        if not pids:
            return False
        try:
            import psutil

            for pid in tuple(pids):
                try:
                    process = psutil.Process(pid)
                    if process.is_running():
                        return True
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
            return False
        except Exception:
            logger.warning("maintenance process liveness check failed", exc_info=True)
            return True


class ApplicationUpdateShutdownCoordinator:
    """Own one named maintenance event for the complete process lifetime."""

    def __init__(
        self,
        kernel: UpdateShutdownKernel | None = None,
        process_probe: MaintenanceProcessProbe | None = None,
    ) -> None:
        self._kernel = kernel if kernel is not None else WindowsUpdateShutdownKernel()
        self._process_probe = (
            process_probe if process_probe is not None else FrozenExecutableProcessProbe()
        )
        self._lock = threading.RLock()
        self._event = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._callback: Callable[[], object] | None = None
        self._pending_shutdown = False
        self._generation = 0
        self._active_callbacks = 0
        self._callback_condition = threading.Condition(self._lock)

    def _supported(self) -> bool:
        return not (
            os.name != "nt" and isinstance(self._kernel, WindowsUpdateShutdownKernel)
        )

    def prepare(self) -> None:
        if not self._supported():
            return
        with self._lock:
            if self._event is not None:
                return
            event = self._kernel.create_event(UPDATE_SHUTDOWN_EVENT_NAME)
            if event is None:
                raise UpdateShutdownError("update_shutdown_event_create_failed:no_handle")
            self._event = event
            self._stop_event.clear()
            self._generation += 1

    def start_listener(self) -> None:
        if not self._supported():
            return
        with self._lock:
            if self._thread is not None:
                return
            if self._event is None:
                raise UpdateShutdownError("update_shutdown_event_not_prepared")
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._wait_loop,
                name="WorkTraceUpdateShutdown",
                daemon=True,
            )
            self._thread.start()

    def bind_shutdown_handler(self, callback: Callable[[], object]) -> None:
        if not callable(callback):
            raise TypeError("shutdown callback must be callable")
        with self._lock:
            self._callback = callback
            dispatch_pending = (
                self._pending_shutdown
                and self._event is not None
                and not self._stop_event.is_set()
            )
            if dispatch_pending:
                self._pending_shutdown = False
                generation = self._generation
            else:
                generation = -1
        if dispatch_pending:
            self._dispatch_callback(callback, generation)

    def signal_running_instance(self) -> bool:
        if not self._supported():
            return False
        try:
            return self._kernel.signal_event(UPDATE_SHUTDOWN_EVENT_NAME)
        except Exception:
            logger.warning("named update shutdown Event signal failed", exc_info=True)
            return False

    def request_running_instance_shutdown(
        self,
        *,
        timeout_seconds: float = 20.0,
        poll_interval_seconds: float = 0.1,
    ) -> bool:
        """Request graceful exit and wait for the complete frozen process tree.

        PyInstaller one-file applications have an outer bootloader process and an
        inner Python application process. The named Event is held by the inner
        process, so Event disappearance alone is not sufficient for an installer to
        replace the executable. Snapshotting the exact same-executable processes
        before signaling lets this control client wait until the old bootloader has
        also completed its cleanup, while excluding its own one-file parent/child.
        """

        if not self._supported():
            return True
        timeout = max(0.0, float(timeout_seconds))
        poll_interval = max(0.01, float(poll_interval_seconds))
        deadline = time.monotonic() + timeout
        prior_pids = self._process_probe.snapshot_other_same_executable_pids()
        try:
            if not self._kernel.event_exists(UPDATE_SHUTDOWN_EVENT_NAME):
                return self._wait_for_prior_processes(
                    prior_pids,
                    deadline=deadline,
                    poll_interval_seconds=poll_interval,
                )
            if not self._kernel.signal_event(UPDATE_SHUTDOWN_EVENT_NAME):
                if self._kernel.event_exists(UPDATE_SHUTDOWN_EVENT_NAME):
                    return False
            while self._kernel.event_exists(UPDATE_SHUTDOWN_EVENT_NAME):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    logger.error("maintenance shutdown timed out waiting for Event")
                    return False
                time.sleep(min(poll_interval, remaining))
            return self._wait_for_prior_processes(
                prior_pids,
                deadline=deadline,
                poll_interval_seconds=poll_interval,
            )
        except Exception:
            logger.exception("maintenance shutdown request failed")
            return False

    def _wait_for_prior_processes(
        self,
        pids: set[int],
        *,
        deadline: float,
        poll_interval_seconds: float,
    ) -> bool:
        while self._process_probe.any_alive(pids):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.error("maintenance shutdown timed out waiting for executable release")
                return False
            time.sleep(min(poll_interval_seconds, remaining))
        return True

    def stop_listener(self) -> None:
        """Stop dispatching but retain the named Event as a process-alive marker."""

        with self._lock:
            thread = self._thread
            event = self._event
            self._thread = None
            self._callback = None
            self._pending_shutdown = False
            self._generation += 1
            self._stop_event.set()
        if event is not None:
            try:
                self._kernel.wake_waiter(event)
            except Exception:
                logger.warning("update shutdown listener wake failed", exc_info=True)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._lock:
            while self._active_callbacks:
                self._callback_condition.wait(timeout=0.1)

    def close(self) -> None:
        self.stop_listener()
        with self._lock:
            event = self._event
            self._event = None
            self._generation += 1
        if event is not None:
            try:
                self._kernel.close_event(event)
            except Exception:
                logger.warning("update shutdown Event close failed", exc_info=True)

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
            logger.exception("update shutdown callback failed")
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
                signaled = self._kernel.wait_for_signal(event, 0.25)
            except Exception:
                logger.exception("update shutdown listener wait failed")
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
                    self._pending_shutdown = True
                    continue
            self._dispatch_callback(callback, generation)


_application_update_shutdown_coordinator = ApplicationUpdateShutdownCoordinator()


def get_application_update_shutdown_coordinator() -> ApplicationUpdateShutdownCoordinator:
    return _application_update_shutdown_coordinator


def request_running_instance_shutdown(*, timeout_seconds: float = 20.0) -> bool:
    """Process-control entry point used by the installed maintenance client."""

    return _application_update_shutdown_coordinator.request_running_instance_shutdown(
        timeout_seconds=timeout_seconds
    )


__all__ = [
    "ApplicationUpdateShutdownCoordinator",
    "FrozenExecutableProcessProbe",
    "UPDATE_SHUTDOWN_EVENT_NAME",
    "UpdateShutdownError",
    "get_application_update_shutdown_coordinator",
    "request_running_instance_shutdown",
]
