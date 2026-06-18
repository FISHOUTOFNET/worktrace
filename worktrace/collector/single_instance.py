from __future__ import annotations

import ctypes
import os
from pathlib import Path

from ..config import resolve_paths

_mutex_handle = None
_lock_file: Path | None = None


class SingleInstanceError(RuntimeError):
    pass


def acquire_single_instance() -> bool:
    global _mutex_handle, _lock_file
    if _mutex_handle or _lock_file:
        return False
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Local\\WorkTrace_v0_1_Lite")
        already_exists = kernel32.GetLastError() == 183
        if already_exists:
            kernel32.CloseHandle(handle)
            return False
        _mutex_handle = handle
        return True

    lock = resolve_paths().base_dir / "worktrace.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii"))
        os.close(fd)
        _lock_file = lock
        return True
    except FileExistsError:
        return False


def release_single_instance() -> None:
    global _mutex_handle, _lock_file
    if os.name == "nt" and _mutex_handle:
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None
    if _lock_file and _lock_file.exists():
        try:
            _lock_file.unlink()
        finally:
            _lock_file = None
