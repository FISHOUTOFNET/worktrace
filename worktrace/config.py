from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path
    data_dir: Path
    log_dir: Path
    db_path: Path
    log_path: Path
    export_dir: Path


def get_local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))


def get_default_export_dir() -> Path:
    return Path.home() / "Documents" / "WorkTrace Exports"


def resolve_paths() -> AppPaths:
    base_dir = get_local_appdata() / "WorkTrace"
    data_dir = base_dir / "data"
    log_dir = base_dir / "logs"
    return AppPaths(
        base_dir=base_dir,
        data_dir=data_dir,
        log_dir=log_dir,
        db_path=data_dir / "worktrace.db",
        log_path=log_dir / "worktrace.log",
        export_dir=get_default_export_dir(),
    )


def ensure_directories(paths: AppPaths) -> None:
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    paths.export_dir.mkdir(parents=True, exist_ok=True)
