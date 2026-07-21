from __future__ import annotations

import ctypes
import hashlib
import logging
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
        if not handle:
            error_code = int(kernel32.GetLastError())
            raise SingleInstanceError(
                f"single_instance_mutex_create_failed:{error_code}"
            )
        already_exists = int(kernel32.GetLastError()) == 183
        if already_exists:
            try:
                kernel32.CloseHandle(handle)
            finally:
                handle = None
            return False
        _mutex_handle = handle
        return True

    lock = resolve_paths().base_dir / "worktrace.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        os.ftruncate(fd, 0)
        payload = str(os.getpid()).encode("ascii")
        written = os.write(fd, payload)
        if written != len(payload):
            raise OSError("single_instance_pid_write_incomplete")
        os.fsync(fd)
    except (BlockingIOError, OSError):
        if acquired:
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                logging.warning("single instance partial unlock failed")
        try:
            os.close(fd)
        except OSError:
            logging.warning("single instance partial descriptor close failed")
        if acquired:
            raise
        return False
    except Exception:
        if acquired:
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                logging.warning("single instance partial unlock failed")
        try:
            os.close(fd)
        except OSError:
            logging.warning("single instance partial descriptor close failed")
        raise
    _lock_file = lock
    _lock_fd = fd
    return True


def _windows_mutex_name() -> str:
    base = str(resolve_paths().base_dir.resolve()).casefold()
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
    return f"Local\\WorkTrace_v0_1_Lite_{digest}"


def release_single_instance() -> None:
    global _mutex_handle, _lock_file, _lock_fd
    handle = _mutex_handle
    fd = _lock_fd
    _mutex_handle = None
    _lock_fd = None
    _lock_file = None

    if os.name == "nt" and handle:
        try:
            if not ctypes.windll.kernel32.CloseHandle(handle):
                logging.warning("single instance mutex release failed")
        except Exception:
            logging.warning("single instance mutex release failed")
    if fd is not None:
        try:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except Exception:
                logging.warning("single instance file unlock failed")
        finally:
            try:
                os.close(fd)
            except OSError:
                logging.warning("single instance descriptor close failed")
    # The pathname is diagnostic only. The kernel lock is released after crashes,
    # so a stale file never blocks a later process.
