"""Typed delivery from FD Work into the main WebView."""

from __future__ import annotations

from collections import OrderedDict
import json
import queue
import threading
import time
from typing import Any, Mapping


def _window_loaded(window: Any) -> bool:
    events = getattr(window, "events", None)
    if events is None:
        return True
    loaded_event = getattr(events, "loaded", None)
    is_loaded = getattr(loaded_event, "is_set", None)
    if not callable(is_loaded):
        return False
    try:
        return is_loaded() is True
    except Exception:
        return False


class FDWorkMainWindowSink:
    """Own status push and ACK-backed picker-result delivery."""

    _PICKER_RETRY_ATTEMPTS = 3
    _PICKER_PENDING_CAPACITY = 8

    def __init__(
        self,
        *,
        deliver_asynchronously: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._window = None
        self._ready = False
        self._pending_picker_scripts: OrderedDict[str, str] = OrderedDict()
        self._queued_picker_requests: set[str] = set()
        self._delivery_queue: queue.Queue[tuple[Any, str, str | None]] | None = None
        if deliver_asynchronously:
            self._delivery_queue = queue.Queue()
            threading.Thread(
                target=self._run_delivery_worker,
                name="fd-work-main-window-sink",
                daemon=True,
            ).start()

    def bind_window(self, window) -> None:
        with self._lock:
            self._window = window

    def mark_ready(self) -> None:
        with self._lock:
            self._ready = True
        self._flush_pending_picker_results()

    def mark_unavailable(self) -> None:
        with self._lock:
            self._ready = False
            self._window = None
            self._queued_picker_requests.clear()

    def status_changed(self, status: Mapping[str, Any]) -> None:
        serialized = json.dumps(dict(status), ensure_ascii=True)
        self._deliver(
            "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkStatus("
            + serialized
            + ")"
        )
        self._flush_pending_picker_results()

    def picker_result(self, result: Mapping[str, Any]) -> None:
        payload = dict(result)
        request_id = payload.get("request_id")
        serialized = json.dumps(payload, ensure_ascii=True)
        script = (
            "window.WorkTraceApp&&window.WorkTraceApp.receiveFDWorkCasePickerResult("
            + serialized
            + ")"
        )
        if not isinstance(request_id, str) or not request_id:
            self._deliver(script)
            return
        window, ready = self._current_window()
        if window is None or not ready or not _window_loaded(window):
            return
        with self._lock:
            self._pending_picker_scripts[request_id] = script
            self._pending_picker_scripts.move_to_end(request_id)
            while len(self._pending_picker_scripts) > self._PICKER_PENDING_CAPACITY:
                stale_request, _stale_script = self._pending_picker_scripts.popitem(last=False)
                self._queued_picker_requests.discard(stale_request)
        self._deliver_picker(request_id)

    def _current_window(self) -> tuple[Any, bool]:
        with self._lock:
            return self._window, self._ready

    def _deliver(self, script: str) -> None:
        window, ready = self._current_window()
        if window is None or not ready or not _window_loaded(window):
            return
        delivery_queue = self._delivery_queue
        if delivery_queue is not None:
            delivery_queue.put_nowait((window, script, None))
            return
        self._evaluate(window, script)

    def _deliver_picker(self, request_id: str) -> None:
        with self._lock:
            script = self._pending_picker_scripts.get(request_id)
            window = self._window
            ready = self._ready
            if (
                script is None
                or request_id in self._queued_picker_requests
                or window is None
                or not ready
                or not _window_loaded(window)
            ):
                return
            delivery_queue = self._delivery_queue
            if delivery_queue is not None:
                self._queued_picker_requests.add(request_id)
                delivery_queue.put_nowait((window, script, request_id))
                return
        if self._evaluate(window, script):
            self._ack_picker(request_id, script)

    def _flush_pending_picker_results(self) -> None:
        with self._lock:
            request_ids = tuple(self._pending_picker_scripts.keys())
        for request_id in request_ids:
            self._deliver_picker(request_id)

    def _ack_picker(self, request_id: str, script: str) -> None:
        with self._lock:
            if self._pending_picker_scripts.get(request_id) == script:
                self._pending_picker_scripts.pop(request_id, None)
            self._queued_picker_requests.discard(request_id)

    def _run_delivery_worker(self) -> None:
        delivery_queue = self._delivery_queue
        if delivery_queue is None:
            return
        while True:
            window, script, picker_request_id = delivery_queue.get()
            try:
                delivered = False
                attempts = (
                    self._PICKER_RETRY_ATTEMPTS
                    if picker_request_id is not None
                    else 1
                )
                for attempt in range(attempts):
                    with self._lock:
                        current_window = self._window
                        ready = self._ready
                    if (
                        current_window is not window
                        or not ready
                        or not _window_loaded(window)
                    ):
                        break
                    delivered = self._evaluate(window, script)
                    if delivered:
                        break
                    if picker_request_id is not None and attempt + 1 < attempts:
                        time.sleep(0.05 * (attempt + 1))
                if picker_request_id is not None:
                    if delivered:
                        self._ack_picker(picker_request_id, script)
                    else:
                        with self._lock:
                            self._queued_picker_requests.discard(picker_request_id)
            finally:
                delivery_queue.task_done()

    @staticmethod
    def _evaluate(window: Any, script: str) -> bool:
        try:
            return window.evaluate_js(script) is not False
        except Exception:
            return False


__all__ = ["FDWorkMainWindowSink"]
