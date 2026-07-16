from __future__ import annotations

import ctypes
import hashlib
import os
from pathlib import Path

from ..config import resolve_paths

_mutex_handle = None
_lock_file: Path | None = None
_lock_fd: int | None = None


class SingleInstanceError(RuntimeError):
    pass


def acquire_single_instance() -> bool:
    global _mutex_handle, _lock_file, _lock_fd
    if _mutex_handle or _lock_fd is not None:
        return False
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, _windows_mutex_name())
        already_exists = kernel32.GetLastError() == 183
        if already_exists:
            kernel32.CloseHandle(handle)
            return False
        _mutex_handle = handle
        return True

    lock = resolve_paths().base_dir / "worktrace.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        return False
    except Exception:
        os.close(fd)
        raise
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode("ascii"))
    _lock_file = lock
    _lock_fd = fd
    return True


def _windows_mutex_name() -> str:
    base = str(resolve_paths().base_dir.resolve()).casefold()
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
    return f"Local\\WorkTrace_v0_1_Lite_{digest}"


def release_single_instance() -> None:
    global _mutex_handle, _lock_file, _lock_fd
    if os.name == "nt" and _mutex_handle:
        ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        _mutex_handle = None
    if _lock_fd is not None:
        try:
            import fcntl

            fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(_lock_fd)
            _lock_fd = None
    # The file is diagnostic only. The kernel lock is released automatically
    # after crashes, so a stale pathname cannot block the next process.
    _lock_file = None
