from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from ..worker_health import WorkerHealthReporter


@dataclass(frozen=True)
class ActiveWindow:
    app_name: str
    process_name: str
    window_title: str
    file_path_hint: str | None = None
    pid: int | None = None
    hwnd: int | None = None
    window_class: str | None = None
    activity_start_time: str | None = None
    # True only when the platform adapter has identified this as a local-file
    # application whose path is required for folder-exclusion privacy.
    privacy_path_required: bool = False


@dataclass(frozen=True)
class ClipboardTextEvent:
    text: str
    source_window: ActiveWindow
    copied_at: str | None = None
    sequence_number: int | None = None


class RuntimePlatformAdapter(Protocol):
    """Complete platform capability required by the shipping runtime."""

    def get_active_window(self) -> ActiveWindow: ...

    def get_idle_seconds(self) -> int: ...

    def get_clipboard_events(self) -> list[ClipboardTextEvent]: ...

    def set_clipboard_capture_enabled(self, enabled: bool) -> None: ...

    def reset_runtime_state(self) -> None: ...

    def run_clipboard_capture(
        self,
        stop_event: threading.Event,
        *,
        health: WorkerHealthReporter,
    ) -> None: ...

    def shutdown(self) -> None: ...


# Public name retained as the current protocol name used by collector-facing code.
PlatformAdapter = RuntimePlatformAdapter


__all__ = [
    "ActiveWindow",
    "ClipboardTextEvent",
    "PlatformAdapter",
    "RuntimePlatformAdapter",
]
