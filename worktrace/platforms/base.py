from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ActiveWindow:
    app_name: str
    process_name: str
    window_title: str
    file_path_hint: str | None = None


class PlatformAdapter(Protocol):
    def get_active_window(self) -> ActiveWindow:
        ...

    def get_idle_seconds(self) -> int:
        ...
