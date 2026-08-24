"""Single-owner FIFO execution for FD Work helper window commands."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import queue
import threading
import time
from typing import Any, Callable


WindowCommandCallback = Callable[[Any], None]
WindowCommand = Callable[[WindowCommandCallback], None]
WindowCommandGuard = Callable[[], bool]


@dataclass(frozen=True)
class FDWorkWindowCommandResult:
    ok: bool
    value: Any = None
    error_kind: str | None = None
    callback_executed: bool = False


class _Request:
    def __init__(
        self,
        command: WindowCommand,
        guard: WindowCommandGuard,
        timeout: float,
    ) -> None:
        self.command = command
        self.guard = guard
        self.timeout = max(0.01, float(timeout))
        self.deadline = time.monotonic() + self.timeout
        self.callback_event = threading.Event()
        self.command_returned = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.callback_executed = False
        self.callback_value: Any = None
        self.terminal = False
        self.result: FDWorkWindowCommandResult | None = None

    def remaining(self) -> float:
        return max(0.0, self.deadline - time.monotonic())

    def accept_callback(self, value: Any) -> None:
        with self.lock:
            if self.terminal:
                return
            self.callback_executed = True
            self.callback_value = value
            self.callback_event.set()

    def finish(self, result: FDWorkWindowCommandResult) -> bool:
        with self.lock:
            if self.terminal:
                return False
            self.terminal = True
            self.result = result
            self.callback_event.set()
            self.finished.set()
            return True

    def is_terminal(self) -> bool:
        with self.lock:
            return self.terminal


class FDWorkWindowExecutor:
    """Run callback-based window commands on one bounded FIFO worker.

    A command that returns but never invokes its callback is a recoverable
    callback timeout. A synchronous window command that itself never returns is
    different: Python cannot safely cancel that pywebview mutation. The executor
    therefore latches ``stalled`` and fails closed instead of starting a second
    worker that could mutate the same window concurrently.
    """

    def __init__(
        self,
        *,
        queue_capacity: int = 32,
        name: str = "fd-work-window-executor",
    ) -> None:
        self._queue: queue.Queue[_Request | object] = queue.Queue(
            maxsize=max(1, int(queue_capacity))
        )
        self._sentinel = object()
        self._lock = threading.Lock()
        self._pending_condition = threading.Condition(self._lock)
        self._shutdown = False
        self._stalled = False
        self._current: _Request | None = None
        self._worker = threading.Thread(target=self._run, name=name, daemon=True)
        self._worker.start()

    def submit(
        self,
        command: WindowCommand,
        guard: WindowCommandGuard,
        timeout: float,
    ) -> FDWorkWindowCommandResult:
        if threading.current_thread() is self._worker:
            return self._rejected()
        request = _Request(command, guard, timeout)
        with self._pending_condition:
            if self._shutdown:
                return self._rejected()
            if self._stalled:
                return self._stalled_result()
            try:
                self._queue.put_nowait(request)
            except queue.Full:
                return self._rejected()
            self._pending_condition.notify_all()

        if not request.finished.wait(timeout=request.remaining()):
            self._expire_request(request)
        return request.result or self._rejected()

    def _expire_request(self, request: _Request) -> None:
        with self._pending_condition:
            if request.finished.is_set():
                return
            is_current = self._current is request
            command_returned = request.command_returned.is_set()
            if is_current and not command_returned:
                # The synchronous pywebview mutation (or its guard) is still on
                # the owner thread. We cannot prove it stopped, so permanently
                # fail this executor generation closed and reject queued work.
                self._stalled = True
                request.finish(self._stalled_result())
                self._drain_queued_locked(self._stalled_result())
                self._pending_condition.notify_all()
                return
            if is_current:
                # The command returned; only the callback/settlement phase missed
                # the absolute deadline. This is recoverable and must not poison
                # the single owner for subsequent commands.
                request.finish(
                    FDWorkWindowCommandResult(
                        ok=False,
                        error_kind="callback_timeout",
                    )
                )
                return

            # The request exhausted its absolute budget while waiting in the FIFO.
            # Leave its terminal shell in the queue; the worker will skip it without
            # executing the mutation when it reaches the head.
            request.finish(
                FDWorkWindowCommandResult(
                    ok=False,
                    error_kind="request_timeout",
                )
            )

    def _drain_queued_locked(self, result: FDWorkWindowCommandResult) -> None:
        saw_sentinel = False
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if item is self._sentinel:
                    saw_sentinel = True
                elif isinstance(item, _Request):
                    item.finish(result)
            finally:
                self._queue.task_done()
        if saw_sentinel:
            self._queue.put_nowait(self._sentinel)

    def shutdown(self, *, timeout: float = 2.0) -> bool:
        with self._pending_condition:
            if self._shutdown and not self._worker.is_alive():
                return True
            if not self._shutdown:
                self._shutdown = True
            current = self._current
            self._drain_queued_locked(self._rejected())
            if current is not None:
                # Release the submitting thread even if the underlying native
                # command cannot be interrupted. The owner worker is still never
                # replaced while that command may be in flight.
                current.finish(self._rejected())
                current.callback_event.set()
            try:
                self._queue.put_nowait(self._sentinel)
            except queue.Full:
                pass
            self._pending_condition.notify_all()
        self._worker.join(timeout=max(0.0, float(timeout)))
        return not self._worker.is_alive()

    @property
    def worker_alive(self) -> bool:
        return self._worker.is_alive()

    @property
    def stalled(self) -> bool:
        with self._lock:
            return self._stalled

    def wait_for_pending_count(self, count: int, *, timeout: float) -> bool:
        expected = max(0, int(count))
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._pending_condition:
            while self._queue.qsize() < expected:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._pending_condition.wait(timeout=remaining)
            return True

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            with self._pending_condition:
                self._pending_condition.notify_all()
            try:
                if item is self._sentinel:
                    return
                if not isinstance(item, _Request):
                    continue
                if item.is_terminal():
                    continue
                with self._lock:
                    self._current = item
                    shutdown = self._shutdown
                    stalled = self._stalled
                if shutdown:
                    item.finish(self._rejected())
                    continue
                if stalled:
                    item.finish(self._stalled_result())
                    return
                if not self._guard_valid(item.guard):
                    item.finish(
                        FDWorkWindowCommandResult(
                            ok=False,
                            error_kind="guard_rejected",
                        )
                    )
                    continue
                try:
                    item.command(item.accept_callback)
                except Exception:
                    item.command_returned.set()
                    item.finish(
                        FDWorkWindowCommandResult(
                            ok=False,
                            error_kind="command_exception",
                        )
                    )
                    continue
                item.command_returned.set()

                with self._lock:
                    stalled = self._stalled
                    shutdown = self._shutdown
                if stalled:
                    item.finish(self._stalled_result())
                    return
                if shutdown:
                    item.finish(self._rejected())
                    return

                if not item.callback_event.wait(timeout=item.remaining()):
                    item.finish(
                        FDWorkWindowCommandResult(
                            ok=False,
                            error_kind="callback_timeout",
                        )
                    )
                    continue
                with item.lock:
                    callback_executed = item.callback_executed
                    value = item.callback_value
                    terminal = item.terminal
                if terminal:
                    continue
                with self._lock:
                    shutdown = self._shutdown
                    stalled = self._stalled
                if stalled:
                    item.finish(self._stalled_result())
                    return
                if shutdown:
                    item.finish(self._rejected())
                elif not self._guard_valid(item.guard):
                    item.finish(
                        FDWorkWindowCommandResult(
                            ok=False,
                            error_kind="guard_rejected",
                            callback_executed=callback_executed,
                        )
                    )
                else:
                    item.finish(
                        FDWorkWindowCommandResult(
                            ok=True,
                            value=value,
                            callback_executed=callback_executed,
                        )
                    )
            finally:
                with self._lock:
                    if self._current is item:
                        self._current = None
                self._queue.task_done()

    @staticmethod
    def _guard_valid(guard: WindowCommandGuard) -> bool:
        try:
            return guard() is True
        except Exception:
            return False

    @staticmethod
    def _rejected() -> FDWorkWindowCommandResult:
        return FDWorkWindowCommandResult(ok=False, error_kind="executor_rejected")

    @staticmethod
    def _stalled_result() -> FDWorkWindowCommandResult:
        return FDWorkWindowCommandResult(ok=False, error_kind="executor_stalled")


class FDWorkWindowCommandError(RuntimeError):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class FDWorkExecutorWindow:
    """Guarded window view whose operations all use one executor."""

    def __init__(
        self,
        window: Any,
        executor: FDWorkWindowExecutor,
        guard: WindowCommandGuard,
        *,
        default_timeout: float = 5.0,
    ) -> None:
        self._window = window
        self._executor = executor
        self._guard = guard
        self._default_timeout = max(0.01, float(default_timeout))

    @property
    def identity(self) -> Any:
        return self._window

    def execute_window_js(
        self,
        script: str,
        *,
        timeout: float,
    ) -> FDWorkWindowCommandResult:
        def command(done: WindowCommandCallback) -> None:
            completion_lock = threading.Lock()
            completion_seen = False

            def accept(value: Any) -> None:
                nonlocal completion_seen
                with completion_lock:
                    if completion_seen:
                        return
                    completion_seen = True
                done(value)

            try:
                returned = self._window.evaluate_js(script, callback=accept)
            except TypeError:
                accept(self._window.evaluate_js(script))
                return
            # pywebview returns synchronous JavaScript values directly. For
            # Promises it returns the boolean ``True`` sentinel and resolves
            # the real value through ``callback`` later.
            if returned is not True:
                accept(returned)

        return self._executor.submit(command, self._guard, timeout)

    def evaluate_js(
        self,
        script: str,
        callback: WindowCommandCallback | None = None,
    ) -> Any:
        result = self._require(
            self.execute_window_js(script, timeout=self._default_timeout)
        )
        if callback is not None:
            callback(result.value)
            return None
        return result.value

    def get_current_url(self) -> Any:
        result = self._executor.submit(
            lambda done: done(self._window.get_current_url()),
            self._guard,
            self._default_timeout,
        )
        return self._require(result).value

    def invoke(self, action: str, *, timeout: float = 2.0) -> bool:
        def command(done: WindowCommandCallback) -> None:
            callback = getattr(self._window, action, None)
            if callable(callback):
                callback()
            done(True)

        return bool(
            self._require(
                self._executor.submit(command, self._guard, timeout)
            ).value
        )

    @staticmethod
    def _require(result: FDWorkWindowCommandResult) -> FDWorkWindowCommandResult:
        if result.ok is not True:
            raise FDWorkWindowCommandError(result.error_kind or "executor_rejected")
        return result


class FDWorkCallbackScheduler:
    """One reusable delay thread for non-window lifecycle callbacks."""

    def __init__(self, *, name: str = "fd-work-callback-scheduler") -> None:
        self._condition = threading.Condition()
        self._items: list[tuple[float, int, Callable[[], None]]] = []
        self._sequence = 0
        self._shutdown = False
        self._worker = threading.Thread(target=self._run, name=name, daemon=True)
        self._worker.start()

    def schedule(self, delay_seconds: float, callback: Callable[[], None]) -> bool:
        due = time.monotonic() + max(0.0, float(delay_seconds))
        with self._condition:
            if self._shutdown:
                return False
            self._sequence += 1
            heapq.heappush(self._items, (due, self._sequence, callback))
            self._condition.notify_all()
            return True

    def shutdown(self, *, timeout: float = 2.0) -> bool:
        with self._condition:
            self._shutdown = True
            self._items.clear()
            self._condition.notify_all()
        if threading.current_thread() is self._worker:
            return False
        self._worker.join(timeout=max(0.0, float(timeout)))
        return not self._worker.is_alive()

    def _run(self) -> None:
        while True:
            with self._condition:
                while not self._shutdown and not self._items:
                    self._condition.wait()
                if self._shutdown:
                    return
                due, _sequence, callback = self._items[0]
                remaining = due - time.monotonic()
                if remaining > 0:
                    self._condition.wait(timeout=remaining)
                    continue
                heapq.heappop(self._items)
            try:
                callback()
            except Exception:
                pass


__all__ = [
    "FDWorkCallbackScheduler",
    "FDWorkExecutorWindow",
    "FDWorkWindowCommandError",
    "FDWorkWindowCommandResult",
    "FDWorkWindowExecutor",
]
