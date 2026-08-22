"""Thread-safe gate for the first on-demand desktop UI creation."""

from __future__ import annotations

import threading
from enum import Enum
from typing import Protocol


class InitialUIRequest(str, Enum):
    OPEN = "open"
    EXIT = "exit"


class DeferredShell(Protocol):
    def show_window(self) -> bool: ...

    def exit_application(self) -> bool: ...


class DeferredUIGate:
    """Coalesce pre-UI desktop requests and late-bind the real shell."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._request_event = threading.Event()
        self._shell: DeferredShell | None = None
        self._open_pending = False
        self._bootstrap_in_progress = False
        self._exit_requested = False

    def request_open(self) -> bool:
        with self._lock:
            if self._exit_requested:
                return False
            shell = self._shell
            if shell is None:
                if self._open_pending or self._bootstrap_in_progress:
                    return False
                self._open_pending = True
                self._request_event.set()
                return True
        return bool(shell.show_window())

    def request_exit(self) -> bool:
        with self._lock:
            if self._exit_requested:
                return False
            self._exit_requested = True
            self._open_pending = False
            self._request_event.set()
            shell = self._shell
        if shell is not None:
            shell.exit_application()
        return True

    def wait_for_initial_request(
        self,
        *,
        timeout: float | None = None,
    ) -> InitialUIRequest | None:
        if not self._request_event.wait(timeout):
            return None
        with self._lock:
            if self._exit_requested:
                return InitialUIRequest.EXIT
            if (
                self._shell is None
                and self._open_pending
                and not self._bootstrap_in_progress
            ):
                self._open_pending = False
                self._bootstrap_in_progress = True
                self._request_event.clear()
                return InitialUIRequest.OPEN
            self._request_event.clear()
            return None

    def bind_shell(self, shell: DeferredShell) -> bool:
        if shell is None:
            raise TypeError("shell is required")
        with self._lock:
            if self._shell is shell:
                return False
            if self._shell is not None:
                raise RuntimeError("deferred_ui_shell_already_bound")
            self._shell = shell
            self._bootstrap_in_progress = False
            exit_requested = self._exit_requested
        if exit_requested:
            shell.exit_application()
        return True

    def mark_initial_open_failed(self) -> None:
        with self._lock:
            if self._shell is None:
                self._bootstrap_in_progress = False


__all__ = ["DeferredUIGate", "InitialUIRequest"]
