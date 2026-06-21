from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .base import ActiveWindow, ClipboardTextEvent


@dataclass
class FakeAdapter:
    windows: list[ActiveWindow] | None = None
    idle_values: list[int] | None = None
    clipboard_events: list[ClipboardTextEvent] | None = None
    default_window: ActiveWindow = ActiveWindow("FakeApp", "fake.exe", "Fake Window")
    default_idle_seconds: int = 0
    _window_queue: deque[ActiveWindow] = field(init=False)
    _idle_queue: deque[int] = field(init=False)
    _clipboard_queue: deque[ClipboardTextEvent] = field(init=False)

    def __post_init__(self) -> None:
        self._window_queue = deque(self.windows or [])
        self._idle_queue = deque(self.idle_values or [])
        self._clipboard_queue = deque(self.clipboard_events or [])

    def get_active_window(self) -> ActiveWindow:
        if self._window_queue:
            return self._window_queue.popleft()
        return self.default_window

    def get_idle_seconds(self) -> int:
        if self._idle_queue:
            return self._idle_queue.popleft()
        return self.default_idle_seconds

    def get_clipboard_events(self) -> list[ClipboardTextEvent]:
        if self._clipboard_queue:
            return [self._clipboard_queue.popleft()]
        return []

    def push_window(self, window: ActiveWindow) -> None:
        self._window_queue.append(window)

    def push_idle(self, seconds: int) -> None:
        self._idle_queue.append(seconds)

    def push_clipboard_event(self, event: ClipboardTextEvent) -> None:
        self._clipboard_queue.append(event)
