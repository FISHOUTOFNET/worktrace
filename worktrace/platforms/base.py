from dataclasses import dataclass
from typing import Protocol


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


class PlatformAdapter(Protocol):
    def get_active_window(self) -> ActiveWindow:
        ...

    def get_idle_seconds(self) -> int:
        ...

    def get_clipboard_events(self) -> list[ClipboardTextEvent]:
        ...
